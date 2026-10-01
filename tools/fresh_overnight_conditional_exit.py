"""Quote-path test of causal conditional exits for the frozen overnight strategy."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from fresh_overnight_quote_replay import api_headers


ROOT = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923")
BASE = ROOT / "research" / "fresh_strategy_competition_20260928" / "quote_replay"
OUT = BASE / "conditional_exit"
PATH_MINUTES = 60
TRAIL_BPS = (25, 50, 100)
TAKE_PROFIT_BPS = (50, 100, 200)
HARD_EXIT_MINUTES = (29, 59)  # 10:00 and 10:30 relative to 09:31 ET.


def cohort() -> tuple[pd.DataFrame, pd.DataFrame]:
    signals = pd.read_parquet(BASE / "signals.parquet")
    detail = pd.read_parquet(BASE / "forced_exit_detail.parquet")
    detail = detail[detail.bps == 5].copy()
    merged = signals.merge(
        detail[["trade_id", "entry_filled", "portfolio_return"]], on="trade_id", how="left"
    )
    merged["symbol"] = merged.symbol.replace({"FB": "META", "CDAY": "DAY"})
    filled = merged[merged.entry_filled].copy()
    if len(merged) != 751 or len(filled) != 734:
        raise RuntimeError(f"Unexpected cohort: attempts={len(merged)}, fills={len(filled)}")
    filled["entry_execution"] = filled.governed_entry_price.astype(float) * 1.0005
    return merged, filled


def fetch_path(timestamp: pd.Timestamp, symbols: list[str], headers: dict[str, str]) -> pd.DataFrame:
    start = pd.Timestamp(timestamp)
    end = start + pd.Timedelta(minutes=PATH_MINUTES)
    rows, token = [], None
    while True:
        params = {
            "symbols": ",".join(symbols), "start": start.isoformat(), "end": end.isoformat(),
            "feed": "sip", "sort": "asc", "limit": 10000,
            "asof": start.strftime("%Y-%m-%d"),
        }
        if token:
            params["page_token"] = token
        url = "https://data.alpaca.markets/v2/stocks/quotes?" + urlencode(params)
        for attempt in range(7):
            try:
                with urlopen(Request(url, headers=headers), timeout=60) as response:
                    payload = json.load(response)
                break
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 6:
                    raise
                time.sleep(min(30, 2**attempt))
            except Exception:
                if attempt == 6:
                    raise
                time.sleep(min(30, 2**attempt))
        for symbol, quotes in payload.get("quotes", {}).items():
            rows.extend({"symbol": symbol, "quote_ts": pd.Timestamp(q["t"]),
                         "bid_price": float(q["bp"]), "ask_price": float(q["ap"]),
                         "bid_size": int(q["bs"]), "ask_size": int(q["as"])} for q in quotes)
        token = payload.get("next_page_token")
        if not token:
            break
    return pd.DataFrame(rows, columns=["symbol", "quote_ts", "bid_price", "ask_price",
                                       "bid_size", "ask_size"])


def download(filled: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    headers, frames, errors = api_headers(), [], []
    quote_dir = OUT / "quotes"
    quote_dir.mkdir(parents=True, exist_ok=True)
    groups = list(filled.groupby("exit_ts", sort=True))
    for index, (timestamp, group) in enumerate(groups, 1):
        timestamp = pd.Timestamp(timestamp)
        path = quote_dir / f"path_{timestamp.strftime('%Y%m%dT%H%M%S%z')}.parquet"
        symbols = sorted(group.symbol.unique())
        try:
            frame = pd.read_parquet(path) if path.exists() else pd.DataFrame()
            present = set(frame.symbol.unique()) if len(frame) else set()
            missing = sorted(set(symbols) - present)
            if missing:
                frame = pd.concat([frame, fetch_path(timestamp, missing, headers)], ignore_index=True)
                frame.to_parquet(path, index=False)
            frame["path_start"] = timestamp
            frames.append(frame)
        except Exception as exc:
            errors.append({"timestamp": timestamp.isoformat(), "error": type(exc).__name__})
        if index % 10 == 0 or index == len(groups):
            print(f"DOWNLOAD {index}/{len(groups)} errors={len(errors)}", flush=True)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), errors


def exit_return(entry: float, quotes: pd.DataFrame, start: pd.Timestamp, gate: str,
                trail_bps: int | None, take_profit_bps: int | None,
                hard_minutes: int) -> tuple[float, str, pd.Timestamp, float]:
    q = quotes.sort_values("quote_ts")
    first = q.iloc[0]
    if gate == "overnight_positive":
        qualifies = float(first.bid_price) > entry
        decision_ts = pd.Timestamp(first.quote_ts)
    elif gate == "first5_positive":
        cutoff = start + pd.Timedelta(minutes=5)
        before = q[q.quote_ts <= cutoff]
        if before.empty:
            return np.nan, "missing_gate_quote", pd.NaT, np.nan
        decision = before.iloc[-1]
        qualifies = float(decision.bid_price) > float(first.bid_price) and float(decision.bid_price) > entry
        decision_ts = pd.Timestamp(decision.quote_ts)
        if not qualifies:
            px = float(decision.bid_price)
            return px / entry - 1, "gate_exit", decision_ts, px
    else:
        raise ValueError(gate)
    if not qualifies:
        return np.nan, "use_baseline", pd.NaT, np.nan
    active = q[(q.quote_ts >= decision_ts) &
               (q.quote_ts <= start + pd.Timedelta(minutes=hard_minutes))]
    if active.empty:
        return np.nan, "missing_path", pd.NaT, np.nan
    high_bid = float(active.iloc[0].bid_price)
    target = entry * (1 + take_profit_bps / 10000) if take_profit_bps else np.inf
    for row in active.itertuples():
        bid = float(row.bid_price)
        high_bid = max(high_bid, bid)
        if bid >= target:
            return target / entry - 1, "take_profit", pd.Timestamp(row.quote_ts), target
        if trail_bps is not None and bid <= high_bid * (1 - trail_bps / 10000):
            return bid / entry - 1, "trailing_stop", pd.Timestamp(row.quote_ts), bid
    final = active.iloc[-1]
    px = float(final.bid_price)
    return px / entry - 1, "hard_exit", pd.Timestamp(final.quote_ts), px


def summarize(detail: pd.DataFrame, attempts: int) -> dict:
    by_day = detail.groupby("session_date").strategy_return.sum().div(
        detail.groupby("session_date").attempts.first()
    ).sort_index()
    cumulative = by_day.cumsum()
    drawdown = cumulative - cumulative.cummax()
    monthly = by_day.groupby(pd.to_datetime(by_day.index).strftime("%Y-%m")).sum()
    return {"gate": detail.gate.iloc[0], "exit_style": detail.exit_style.iloc[0],
            "trail_bps": detail.trail_bps.iloc[0], "take_profit_bps": detail.take_profit_bps.iloc[0],
            "hard_exit_minutes": detail.hard_exit_minutes.iloc[0], "attempted_entries": attempts,
            "filled_entries": len(detail), "mean_filled_trade_bps": detail.strategy_return.mean()*10000,
            "additive_return": by_day.sum(), "compounded_return": (1+by_day).prod()-1,
            "max_additive_drawdown": drawdown.min(), "positive_months": int((monthly>0).sum()),
            "continued": int(detail.continued.sum()), "trailing_stops": int((detail.exit_reason=="trailing_stop").sum()),
            "take_profits": int((detail.exit_reason=="take_profit").sum()),
            "hard_exits": int((detail.exit_reason=="hard_exit").sum())}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_attempts, filled = cohort()
    quotes, errors = download(filled)
    quotes.to_parquet(OUT / "downloaded_quotes.parquet", index=False)
    valid = quotes[(quotes.bid_price > 0) & (quotes.ask_price >= quotes.bid_price)
                   & (quotes.bid_size > 0) & (quotes.ask_size > 0)].copy()
    paths = {(ts, symbol): g for (ts, symbol), g in valid.groupby(["path_start", "symbol"], sort=False)}
    configurations = []
    for gate in ("overnight_positive", "first5_positive"):
        for hard in HARD_EXIT_MINUTES:
            configurations.extend((gate, "trail", trail, None, hard) for trail in TRAIL_BPS)
            configurations.extend((gate, "take_profit", None, target, hard) for target in TAKE_PROFIT_BPS)
    rows, summaries = [], []
    attempts_by_day = all_attempts.groupby("session_date").size()
    for gate, style, trail, target, hard in configurations:
        current = []
        for row in filled.itertuples():
            path = paths.get((row.exit_ts, row.symbol))
            if path is None or path.empty:
                ret, reason, ts, px = np.nan, "missing_path", pd.NaT, np.nan
            else:
                ret, reason, ts, px = exit_return(row.entry_execution, path, row.exit_ts,
                                                   gate, trail, target, hard)
            continued = reason not in {"use_baseline", "gate_exit", "missing_path", "missing_gate_quote"}
            if reason == "use_baseline":
                ret, reason = float(row.portfolio_return), "baseline_exit"
            record = {"trade_id": row.trade_id, "symbol": row.symbol, "session_date": row.session_date,
                      "gate": gate, "exit_style": style, "trail_bps": trail,
                      "take_profit_bps": target, "hard_exit_minutes": hard,
                      "strategy_return": ret, "exit_reason": reason, "exit_ts_actual": ts,
                      "exit_price_actual": px, "continued": continued,
                      "attempts": int(attempts_by_day.loc[row.session_date])}
            current.append(record)
        frame = pd.DataFrame(current)
        rows.append(frame)
        summaries.append(summarize(frame, len(all_attempts)))
    detail = pd.concat(rows, ignore_index=True)
    summary = pd.DataFrame(summaries)
    baseline = pd.read_parquet(BASE / "forced_exit_summary.parquet")
    baseline = baseline[baseline.bps == 5].iloc[0]
    summary["delta_additive_vs_baseline"] = summary.additive_return - baseline.additive_daily_return
    detail.to_parquet(OUT / "detail.parquet", index=False)
    summary.to_parquet(OUT / "summary.parquet", index=False)
    payload = {"status": "complete" if not errors else "partial", "download_errors": errors,
               "attempts": len(all_attempts), "filled_entries": len(filled),
               "baseline_additive_return": float(baseline.additive_daily_return),
               "configurations": len(summary), "sealed_periods_accessed": False}
    (OUT / "manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(summary.sort_values("additive_return", ascending=False).to_string(index=False), flush=True)
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
