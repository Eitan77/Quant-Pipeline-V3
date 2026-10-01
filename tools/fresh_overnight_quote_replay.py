"""Download exact SIP quote windows and replay the fresh overnight leader."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from dotenv import dotenv_values

from quant_pipeline.production.replay import prepare_replay_inputs


ROOT = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923")
OUT = ROOT / "research" / "fresh_strategy_competition_20260928" / "quote_replay"
WINDOW_SECONDS = 60
BPS_LEVELS = (-1, 0, 1, 2, 3, 4, 5)


def candidate_signals() -> pd.DataFrame:
    reader = json.loads((ROOT / "evidence" / "reader.json").read_text(encoding="utf-8"))
    spec = {
        "grid": "preclose_1555",
        "state_kind": "dual",
        "pair_id": "e669d83e43b3cea8b148779a",
        "target_id": "target_overnight__raw__preclose_1555",
        "resolution": 10,
        "cells": [80, 90],
        "direction": 1,
        "return_basis": "raw",
    }
    signals, preparation = prepare_replay_inputs(ROOT, reader, spec)
    if preparation["status"] != "complete" or len(signals) != 751:
        raise RuntimeError(f"Unexpected replay preparation: {preparation}")
    result = signals.dropna(
        subset=["governed_entry_ts", "governed_entry_price", "exit_ts", "exit_price"]
    ).copy()
    # The governed security IDs are stable, but the compact reference table also
    # carries obsolete aliases. All discovery dates are after these renames.
    result["symbol"] = result.symbol.replace({"FB": "META", "CDAY": "DAY"})
    result["trade_id"] = np.arange(len(result), dtype=np.int64)
    return result


def api_headers() -> dict[str, str]:
    values = dotenv_values(r"D:\AlgoResearch\.env")
    key = values.get("ALPACA_API_KEY_ID") or values.get("APCA_API_KEY_ID")
    secret = values.get("ALPACA_API_SECRET_KEY") or values.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Alpaca SIP credentials are unavailable")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def fetch_window(timestamp: pd.Timestamp, symbols: list[str], headers: dict[str, str]) -> pd.DataFrame:
    start = pd.Timestamp(timestamp)
    end = start + pd.Timedelta(seconds=WINDOW_SECONDS)
    rows: list[dict] = []
    token = None
    while True:
        params = {
            "symbols": ",".join(symbols),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "feed": "sip",
            "sort": "asc",
            "limit": 10000,
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
            rows.extend(
                {
                    "symbol": symbol,
                    "quote_ts": pd.Timestamp(item["t"]),
                    "bid_price": float(item["bp"]),
                    "ask_price": float(item["ap"]),
                    "bid_size": int(item["bs"]),
                    "ask_size": int(item["as"]),
                }
                for item in quotes
            )
        token = payload.get("next_page_token")
        if not token:
            break
    return pd.DataFrame(
        rows,
        columns=["symbol", "quote_ts", "bid_price", "ask_price", "bid_size", "ask_size"],
    )


def download(signals: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    headers = api_headers()
    quote_dir = OUT / "quotes"
    quote_dir.mkdir(parents=True, exist_ok=True)
    windows = []
    for leg, column in (("entry", "governed_entry_ts"), ("exit", "exit_ts")):
        for timestamp, group in signals.groupby(column, sort=True):
            windows.append((leg, pd.Timestamp(timestamp), sorted(group.symbol.unique())))
    errors = []
    frames = []
    for index, (leg, timestamp, symbols) in enumerate(windows, 1):
        stamp = timestamp.strftime("%Y%m%dT%H%M%S%z")
        path = quote_dir / f"{leg}_{stamp}.parquet"
        try:
            frame = pd.read_parquet(path) if path.exists() else pd.DataFrame()
            present = set(frame.symbol.unique()) if len(frame) else set()
            missing = sorted(set(symbols) - present)
            if missing:
                fetched = fetch_window(timestamp, missing, headers)
                frame = pd.concat([frame, fetched], ignore_index=True)
                frame.to_parquet(path, index=False)
            frame["leg"] = leg
            frame["window_ts"] = timestamp
            frames.append(frame)
        except Exception as exc:
            errors.append(
                {"leg": leg, "timestamp": timestamp.isoformat(), "error": type(exc).__name__}
            )
        if index % 25 == 0 or index == len(windows):
            print(f"DOWNLOAD {index}/{len(windows)} errors={len(errors)}", flush=True)
    quotes = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return quotes, errors


def replay(signals: pd.DataFrame, quotes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid = quotes[
        (quotes.bid_price > 0)
        & (quotes.ask_price >= quotes.bid_price)
        & (quotes.bid_size > 0)
        & (quotes.ask_size > 0)
    ].copy()
    paths = {
        (leg, timestamp, symbol): group
        for (leg, timestamp, symbol), group in valid.groupby(
            ["leg", "window_ts", "symbol"], sort=False
        )
    }
    records = []
    for row in signals.itertuples():
        entry = paths.get(("entry", row.governed_entry_ts, row.symbol))
        exit_frame = paths.get(("exit", row.exit_ts, row.symbol))
        entry_covered = entry is not None and len(entry) > 0
        exit_covered = exit_frame is not None and len(exit_frame) > 0
        max_bid = float(entry.bid_price.max()) if entry_covered else np.nan
        max_exit_bid = float(exit_frame.bid_price.max()) if exit_covered else np.nan
        for bps in BPS_LEVELS:
            entry_limit = float(row.governed_entry_price) * (1 + bps / 10000)
            exit_limit = float(row.exit_price) * (1 - bps / 10000)
            entry_fill = bool(entry_covered and float(entry.ask_price.min()) <= entry_limit)
            exit_fill = bool(exit_covered and max_exit_bid >= exit_limit)
            completed = entry_fill and exit_fill
            records.append(
                {
                    "trade_id": int(row.trade_id),
                    "symbol": row.symbol,
                    "session_date": row.session_date,
                    "bps": bps,
                    "entry_quote_covered": entry_covered,
                    "exit_quote_covered": exit_covered,
                    "entry_limit": entry_limit,
                    "exit_limit": exit_limit,
                    "entry_attainable": entry_fill,
                    "exit_attainable": exit_fill,
                    "completed": completed,
                    "completed_return": exit_limit / entry_limit - 1 if completed else np.nan,
                }
            )
    detail = pd.DataFrame(records)
    summary_rows = []
    for bps, group in detail.groupby("bps", sort=True):
        entry_attempted = len(group)
        entry_attainable = int(group.entry_attainable.sum())
        attempted_exits = entry_attainable
        attainable_exits = int((group.entry_attainable & group.exit_attainable).sum())
        completed = group[group.completed]
        summary_rows.append(
            {
                "bps": int(bps),
                "attempted_entries": entry_attempted,
                "entry_quote_covered": int(group.entry_quote_covered.sum()),
                "attainable_entries": entry_attainable,
                "attempted_exits": attempted_exits,
                "exit_quote_covered": int((group.entry_attainable & group.exit_quote_covered).sum()),
                "attainable_exits": attainable_exits,
                "completed_trades": len(completed),
                "entry_attainment_rate": entry_attainable / entry_attempted,
                "exit_attainment_rate": attainable_exits / attempted_exits if attempted_exits else np.nan,
                "both_sides_attainment_rate": len(completed) / entry_attempted,
                "average_completed_return_bps": completed.completed_return.mean() * 10000,
                "total_completed_return": completed.completed_return.sum(),
            }
        )
    return detail, pd.DataFrame(summary_rows)


def replay_with_forced_exit(
    signals: pd.DataFrame, quotes: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Close every filled entry; missed exit limits cross at the final window bid."""
    valid = quotes[
        (quotes.bid_price > 0)
        & (quotes.ask_price >= quotes.bid_price)
        & (quotes.bid_size > 0)
        & (quotes.ask_size > 0)
    ].copy()
    paths = {
        (leg, timestamp, symbol): group.sort_values("quote_ts")
        for (leg, timestamp, symbol), group in valid.groupby(
            ["leg", "window_ts", "symbol"], sort=False
        )
    }
    records = []
    for row in signals.itertuples():
        entry = paths.get(("entry", row.governed_entry_ts, row.symbol))
        exit_frame = paths.get(("exit", row.exit_ts, row.symbol))
        for bps in BPS_LEVELS:
            entry_limit = float(row.governed_entry_price) * (1 + bps / 10000)
            exit_limit = float(row.exit_price) * (1 - bps / 10000)
            entry_fill = bool(entry is not None and len(entry) and entry.ask_price.min() <= entry_limit)
            limit_exit = bool(
                entry_fill
                and exit_frame is not None
                and len(exit_frame)
                and exit_frame.bid_price.max() >= exit_limit
            )
            if not entry_fill:
                status, realized_exit, realized_return = "unfilled_entry", np.nan, 0.0
            elif limit_exit:
                status, realized_exit = "limit_exit", exit_limit
                realized_return = realized_exit / entry_limit - 1
            elif exit_frame is not None and len(exit_frame):
                status = "forced_exit_final_bid"
                realized_exit = float(exit_frame.iloc[-1].bid_price)
                realized_return = realized_exit / entry_limit - 1
            else:
                status, realized_exit, realized_return = "missing_exit_quotes", np.nan, np.nan
            records.append(
                {
                    "trade_id": int(row.trade_id),
                    "symbol": row.symbol,
                    "session_date": row.session_date,
                    "bps": bps,
                    "entry_limit": entry_limit,
                    "exit_limit": exit_limit,
                    "entry_filled": entry_fill,
                    "exit_status": status,
                    "realized_exit_price": realized_exit,
                    "portfolio_return": realized_return,
                }
            )
    detail = pd.DataFrame(records)
    summary_rows = []
    for bps, group in detail.groupby("bps", sort=True):
        daily = group.groupby("session_date").portfolio_return.mean().sort_index()
        cumulative = daily.cumsum()
        drawdown = cumulative - cumulative.cummax()
        monthly = daily.groupby(pd.to_datetime(daily.index).strftime("%Y-%m")).sum()
        filled = group[group.entry_filled]
        summary_rows.append(
            {
                "bps": int(bps),
                "attempted_entries": len(group),
                "filled_entries": int(group.entry_filled.sum()),
                "limit_exits": int((group.exit_status == "limit_exit").sum()),
                "forced_exits": int((group.exit_status == "forced_exit_final_bid").sum()),
                "closed_positions": int(group.exit_status.isin(["limit_exit", "forced_exit_final_bid"]).sum()),
                "mean_filled_trade_bps": float(filled.portfolio_return.mean() * 10000),
                "filled_trade_win_rate": float((filled.portfolio_return > 0).mean()),
                "additive_daily_return": float(daily.sum()),
                "compounded_daily_return": float((1 + daily).prod() - 1),
                "max_additive_drawdown": float(drawdown.min()),
                "positive_months": int((monthly > 0).sum()),
                "observed_months": len(monthly),
            }
        )
    return detail, pd.DataFrame(summary_rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    signals = candidate_signals()
    signals.to_parquet(OUT / "signals.parquet", index=False)
    quotes, errors = download(signals)
    quotes.to_parquet(OUT / "downloaded_quotes.parquet", index=False)
    detail, summary = replay(signals, quotes)
    detail.to_parquet(OUT / "replay_detail.parquet", index=False)
    summary.to_parquet(OUT / "replay_summary.parquet", index=False)
    forced_detail, forced_summary = replay_with_forced_exit(signals, quotes)
    forced_detail.to_parquet(OUT / "forced_exit_detail.parquet", index=False)
    forced_summary.to_parquet(OUT / "forced_exit_summary.parquet", index=False)
    payload = {
        "status": "complete" if not errors else "partial",
        "strategy": "overnight_long_r10_cells_80_90",
        "window_seconds": WINDOW_SECONDS,
        "signals": len(signals),
        "download_errors": errors,
        "summary": summary.replace({np.nan: None}).to_dict("records"),
        "forced_exit_policy": "missed 60-second exit limit sells at final valid bid in window",
        "forced_exit_summary": forced_summary.replace({np.nan: None}).to_dict("records"),
    }
    (OUT / "replay_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(summary.to_string(index=False), flush=True)
    print("FORCED EXIT ACCOUNTING", flush=True)
    print(forced_summary.to_string(index=False), flush=True)
    print(f"OUTPUT {OUT / 'replay_summary.json'}", flush=True)


if __name__ == "__main__":
    main()
