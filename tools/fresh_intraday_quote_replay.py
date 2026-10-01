"""Exact SIP quote replay for the frozen intraday confirmation candidate."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fresh_overnight_quote_replay import api_headers, fetch_window


ROOT = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923")
SOURCE = ROOT / "research" / "fresh_strategy_competition_20260928" / "intraday_confirmation"
OUT = SOURCE / "quote_replay_t6_slots10"
WINDOW_SECONDS = 60
BPS_LEVELS = (-1, 0, 1, 2, 3, 4, 5)


def signals() -> pd.DataFrame:
    frame = pd.read_parquet(SOURCE / "trade_ledgers.parquet")
    frame = frame[(frame.threshold == 6) & (frame.slots == 10)].copy()
    frame["symbol"] = frame.symbol.replace({"FB": "META", "CDAY": "DAY"})
    frame["trade_id"] = np.arange(len(frame), dtype=np.int64)
    if len(frame) != 661:
        raise RuntimeError(f"Expected 661 frozen trades, found {len(frame)}")
    return frame


def download(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    headers = api_headers()
    quote_dir = OUT / "quotes"
    quote_dir.mkdir(parents=True, exist_ok=True)
    windows = []
    for leg, column in (("entry", "entry_ts"), ("exit", "exit_ts")):
        for timestamp, group in frame.groupby(column, sort=True):
            windows.append((leg, pd.Timestamp(timestamp), sorted(group.symbol.unique())))
    errors, frames = [], []
    for index, (leg, timestamp, symbols) in enumerate(windows, 1):
        stamp = timestamp.strftime("%Y%m%dT%H%M%S%z")
        path = quote_dir / f"{leg}_{stamp}.parquet"
        try:
            quotes = pd.read_parquet(path) if path.exists() else pd.DataFrame()
            present = set(quotes.symbol.unique()) if len(quotes) else set()
            missing = sorted(set(symbols) - present)
            if missing:
                quotes = pd.concat([quotes, fetch_window(timestamp, missing, headers)], ignore_index=True)
                quotes.to_parquet(path, index=False)
            quotes["leg"], quotes["window_ts"] = leg, timestamp
            frames.append(quotes)
        except Exception as exc:
            errors.append({"leg": leg, "timestamp": timestamp.isoformat(), "error": type(exc).__name__})
        if index % 25 == 0 or index == len(windows):
            print(f"DOWNLOAD {index}/{len(windows)} errors={len(errors)}", flush=True)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), errors


def replay(frame: pd.DataFrame, quotes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid = quotes[(quotes.bid_price > 0) & (quotes.ask_price >= quotes.bid_price)
                   & (quotes.bid_size > 0) & (quotes.ask_size > 0)].copy()
    paths = {(leg, ts, symbol): group for (leg, ts, symbol), group in
             valid.groupby(["leg", "window_ts", "symbol"], sort=False)}
    records = []
    for row in frame.itertuples():
        entry = paths.get(("entry", row.entry_ts, row.symbol))
        exit_frame = paths.get(("exit", row.exit_ts, row.symbol))
        entry_covered = entry is not None and len(entry) > 0
        exit_covered = exit_frame is not None and len(exit_frame) > 0
        max_entry_bid = float(entry.bid_price.max()) if entry_covered else np.nan
        min_exit_ask = float(exit_frame.ask_price.min()) if exit_covered else np.nan
        for bps in BPS_LEVELS:
            entry_limit = float(row.entry_price) * (1 - bps / 10000)
            exit_limit = float(row.exit_price) * (1 + bps / 10000)
            entry_fill = bool(entry_covered and max_entry_bid >= entry_limit)
            exit_fill = bool(exit_covered and min_exit_ask <= exit_limit)
            completed = entry_fill and exit_fill
            records.append({
                "trade_id": int(row.trade_id), "symbol": row.symbol,
                "session_date": row.session_date, "bps": bps,
                "entry_quote_covered": entry_covered, "exit_quote_covered": exit_covered,
                "entry_limit": entry_limit, "exit_limit": exit_limit,
                "entry_attainable": entry_fill, "exit_attainable": exit_fill,
                "completed": completed,
                "completed_return": entry_limit / exit_limit - 1 if completed else np.nan,
            })
    detail = pd.DataFrame(records)
    summary = []
    for bps, group in detail.groupby("bps", sort=True):
        entries = int(group.entry_attainable.sum())
        completed = group[group.completed]
        summary.append({
            "bps": int(bps), "attempted_entries": len(group),
            "entry_quote_covered": int(group.entry_quote_covered.sum()),
            "attainable_entries": entries,
            "attempted_exits": entries,
            "exit_quote_covered": int((group.entry_attainable & group.exit_quote_covered).sum()),
            "attainable_exits": len(completed),
            "completed_trades": len(completed),
            "entry_attainment_rate": entries / len(group),
            "exit_attainment_rate": len(completed) / entries if entries else np.nan,
            "both_sides_attainment_rate": len(completed) / len(group),
            "average_completed_return_bps": completed.completed_return.mean() * 10000,
            "total_completed_return": completed.completed_return.sum(),
        })
    return detail, pd.DataFrame(summary)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = signals()
    frame.to_parquet(OUT / "signals.parquet", index=False)
    quotes, errors = download(frame)
    quotes.to_parquet(OUT / "downloaded_quotes.parquet", index=False)
    detail, summary = replay(frame, quotes)
    detail.to_parquet(OUT / "replay_detail.parquet", index=False)
    summary.to_parquet(OUT / "replay_summary.parquet", index=False)
    payload = {"status": "complete" if not errors else "partial",
               "strategy": "intraday_short_confirmation_t6_slots10",
               "window_seconds": WINDOW_SECONDS, "signals": len(frame),
               "download_errors": errors,
               "summary": summary.replace({np.nan: None}).to_dict("records")}
    (OUT / "replay_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(summary.to_string(index=False), flush=True)
    print(f"OUTPUT {OUT / 'replay_summary.json'}", flush=True)


if __name__ == "__main__":
    main()
