"""Narrow SIP quote verification of the selected conditional overnight exit."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fresh_overnight_quote_replay import api_headers, fetch_window


ROOT = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923")
BASE = ROOT / "research" / "fresh_strategy_competition_20260928" / "quote_replay"
SCREEN = BASE / "conditional_exit_screen"
OUT = BASE / "conditional_exit_quote"


def selected_events() -> tuple[pd.DataFrame, pd.DataFrame]:
    detail = pd.read_parquet(SCREEN / "detail.parquet")
    selected = detail[
        (detail.gate == "first5_positive")
        & (detail.exit_style == "trail")
        & (detail.trail_bps == 100)
        & (detail.hard_exit_minutes == 59)
    ].copy()
    signals = pd.read_parquet(BASE / "signals.parquet")
    forced = pd.read_parquet(BASE / "forced_exit_detail.parquet").query("bps == 5")
    attempts = signals.merge(forced[["trade_id", "entry_filled"]], on="trade_id", how="left")
    attempts["symbol"] = attempts.symbol.replace({"FB": "META", "CDAY": "DAY"})
    entry = signals[["trade_id", "governed_entry_price"]].copy()
    selected = selected.merge(entry, on="trade_id", how="left")
    selected["entry_execution"] = selected.governed_entry_price.astype(float) * 1.0005
    selected["event_ts"] = pd.to_datetime(selected.candidate_exit_ts, utc=True)
    close_event = selected.exit_reason.isin(["gate_exit", "hard_exit"])
    selected.loc[close_event, "event_ts"] += pd.Timedelta(minutes=1)
    if len(attempts) != 751 or len(selected) != 734:
        raise RuntimeError(f"Unexpected cohorts: {len(attempts)} / {len(selected)}")
    return attempts, selected


def download(events: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    headers, frames, errors = api_headers(), [], []
    quote_dir = OUT / "quotes"
    quote_dir.mkdir(parents=True, exist_ok=True)
    groups = list(events.groupby("event_ts", sort=True))
    for index, (timestamp, group) in enumerate(groups, 1):
        timestamp = pd.Timestamp(timestamp)
        path = quote_dir / f"exit_{timestamp.strftime('%Y%m%dT%H%M%S%z')}.parquet"
        symbols = sorted(group.symbol.unique())
        try:
            frame = pd.read_parquet(path) if path.exists() else pd.DataFrame()
            present = set(frame.symbol.unique()) if len(frame) else set()
            missing = sorted(set(symbols) - present)
            if missing:
                frame = pd.concat([frame, fetch_window(timestamp, missing, headers)], ignore_index=True)
                frame.to_parquet(path, index=False)
            frame["event_ts"] = timestamp
            frames.append(frame)
        except Exception as exc:
            errors.append({"timestamp": timestamp.isoformat(), "error": type(exc).__name__})
        if index % 25 == 0 or index == len(groups):
            print(f"QUOTES {index}/{len(groups)} errors={len(errors)}", flush=True)
    return pd.concat(frames, ignore_index=True), errors


def replay(attempts: pd.DataFrame, events: pd.DataFrame, quotes: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.Series]:
    valid = quotes[(quotes.bid_price > 0) & (quotes.ask_price >= quotes.bid_price)
                   & (quotes.bid_size > 0) & (quotes.ask_size > 0)].copy()
    paths = {(ts, symbol): g.sort_values("quote_ts") for (ts, symbol), g in
             valid.groupby(["event_ts", "symbol"], sort=False)}
    rows = []
    for row in events.itertuples():
        q = paths.get((row.event_ts, row.symbol))
        if q is None or q.empty:
            exit_price, status = np.nan, "missing_quotes"
        elif row.exit_reason == "trailing_stop":
            touched = q[q.bid_price <= float(row.bar_exit_price)]
            if len(touched):
                exit_price, status = float(touched.iloc[0].bid_price), "quote_stop"
            else:
                exit_price, status = float(q.iloc[-1].bid_price), "unconfirmed_stop_fallback"
        else:
            exit_price, status = float(q.iloc[0].bid_price), f"quote_{row.exit_reason}"
        ret = exit_price / float(row.entry_execution) - 1 if np.isfinite(exit_price) else np.nan
        rows.append({"trade_id": row.trade_id, "symbol": row.symbol,
                     "session_date": row.session_date, "event_ts": row.event_ts,
                     "bar_exit_reason": row.exit_reason, "quote_exit_status": status,
                     "exit_price": exit_price, "portfolio_return": ret})
    detail = pd.DataFrame(rows)
    attempts_by_day = attempts.groupby("session_date").size()
    daily = detail.groupby("session_date").portfolio_return.sum().div(attempts_by_day).fillna(0).sort_index()
    cumulative = daily.cumsum()
    monthly = daily.groupby(pd.to_datetime(daily.index).strftime("%Y-%m")).sum()
    late = detail[detail.session_date.astype(str) >= "2025-11-01"]
    summary = {
        "attempted_entries": len(attempts), "filled_entries": len(detail),
        "quote_covered_exits": int(detail.exit_price.notna().sum()),
        "mean_filled_trade_bps": float(detail.portfolio_return.mean()*10000),
        "filled_trade_win_rate": float((detail.portfolio_return > 0).mean()),
        "additive_return": float(daily.sum()), "compounded_return": float((1+daily).prod()-1),
        "max_additive_drawdown": float((cumulative-cumulative.cummax()).min()),
        "positive_months": int((monthly>0).sum()), "observed_months": len(monthly),
        "late_mean_filled_bps": float(late.portfolio_return.mean()*10000),
        "exit_status_counts": detail.quote_exit_status.value_counts().to_dict(),
    }
    return detail, summary, monthly


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    attempts, events = selected_events()
    events.to_parquet(OUT / "events.parquet", index=False)
    quotes, errors = download(events)
    quotes.to_parquet(OUT / "downloaded_quotes.parquet", index=False)
    detail, summary, monthly = replay(attempts, events, quotes)
    detail.to_parquet(OUT / "detail.parquet", index=False)
    monthly.rename("return").to_frame().to_parquet(OUT / "monthly.parquet")
    payload = {"status": "complete" if not errors and summary["quote_covered_exits"] == 734 else "partial",
               "rule": "first 5m positive and above entry; otherwise exit; 100bp trailing stop; hard exit 10:30 ET",
               "download_errors": errors, "sealed_periods_accessed": False, "summary": summary,
               "monthly": monthly.to_dict()}
    (OUT / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
