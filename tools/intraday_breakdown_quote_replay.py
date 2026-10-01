"""SIP marketable replay for the frozen full-horizon breakdown short."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from fresh_overnight_quote_replay import api_headers, fetch_window
from intraday_strategy_search import OUT


SOURCE = OUT / "breakdown_exit_audit"
DEST = SOURCE / "quote_replay"
ALIASES = {"FB": "META", "CDAY": "DAY", "PEAK": "DOC", "JEC": "J", "UTX": "RTX", "WRK": "SW", "VIAC": "PARA"}
COSTS = [-1, 0, 1, 2, 3, 5]


def signals() -> pd.DataFrame:
    frame = pd.read_parquet(SOURCE / "frozen_trades.parquet").copy()
    if len(frame) != 432:
        raise RuntimeError(f"Expected 432 frozen trades, got {len(frame)}")
    catalog = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\cache\source\20240401_20260430\catalog.duckdb")
    with duckdb.connect(str(catalog), read_only=True) as con:
        keys = frame[["security_id", "session_date"]].drop_duplicates().copy()
        keys["session_date"] = pd.to_datetime(keys.session_date).dt.date
        con.register("trade_keys", keys)
        symbols = con.execute("""
            SELECT DISTINCT k.security_id,k.session_date,b.symbol
            FROM trade_keys k JOIN bars_1m_raw b
              ON b.security_id=k.security_id AND b.session_date=k.session_date
        """).fetchdf()
    frame["session_date"] = pd.to_datetime(frame.session_date).dt.strftime("%Y-%m-%d")
    symbols["session_date"] = pd.to_datetime(symbols.session_date).dt.strftime("%Y-%m-%d")
    frame = frame.merge(symbols, on=["security_id", "session_date"], how="left", validate="many_to_one")
    if frame.symbol.isna().any():
        raise RuntimeError("Unmapped symbols")
    frame["symbol"] = frame.symbol.replace(ALIASES)
    frame["entry_ts"] = pd.to_datetime(frame.entry_minute, unit="m", utc=True)
    frame["exit_ts"] = pd.to_datetime(frame.exit_minute, unit="m", utc=True)
    frame["trade_id"] = np.arange(len(frame), dtype=np.int64)
    return frame


def download(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    headers = api_headers(); quote_dir = DEST / "quotes"; quote_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for leg, column in [("entry", "entry_ts"), ("exit", "exit_ts")]:
        for timestamp, group in frame.groupby(column, sort=True):
            jobs.append((leg, pd.Timestamp(timestamp), sorted(group.symbol.unique())))

    def one(job):
        leg, timestamp, names = job
        path = quote_dir / f"{leg}_{timestamp.strftime('%Y%m%dT%H%M%S%z')}.parquet"
        cached = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        present = set(cached.symbol.unique()) if len(cached) else set()
        missing = sorted(set(names) - present)
        if missing:
            cached = pd.concat([cached, fetch_window(timestamp - pd.Timedelta(seconds=60), missing, headers)], ignore_index=True)
            cached.to_parquet(path, index=False)
        cached["leg"], cached["window_ts"] = leg, timestamp
        return cached

    frames, errors = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(one, job): job for job in jobs}
        for n, future in enumerate(as_completed(futures), 1):
            try: frames.append(future.result())
            except Exception as exc:
                leg, timestamp, names = futures[future]
                errors.append({"leg": leg, "timestamp": timestamp.isoformat(), "symbols": names,
                               "error": type(exc).__name__})
            if n % 100 == 0 or n == len(jobs):
                print("DOWNLOAD", n, "/", len(jobs), "errors", len(errors), flush=True)
    return pd.concat(frames, ignore_index=True), errors


def asof_quote(path: pd.DataFrame, timestamp: pd.Timestamp):
    valid = path[(path.bid_price > 0) & (path.ask_price >= path.bid_price)
                 & (path.bid_size > 0) & (path.ask_size > 0)
                 & (path.quote_ts <= timestamp)].sort_values("quote_ts")
    return None if valid.empty else valid.iloc[-1]


def replay(frame: pd.DataFrame, quotes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    paths = {(leg, ts, symbol): g for (leg, ts, symbol), g in
             quotes.groupby(["leg", "window_ts", "symbol"], sort=False)}
    rows = []
    for trade in frame.itertuples():
        entry = asof_quote(paths.get(("entry", trade.entry_ts, trade.symbol), pd.DataFrame()), trade.entry_ts)
        exit_quote = asof_quote(paths.get(("exit", trade.exit_ts, trade.symbol), pd.DataFrame()), trade.exit_ts)
        covered = entry is not None and exit_quote is not None
        gross = (float(entry.bid_price) / float(exit_quote.ask_price) - 1) * 10000 if covered else np.nan
        rows.append({
            "trade_id": trade.trade_id, "session_date": trade.session_date, "symbol": trade.symbol,
            "covered": covered, "quote_gross_bps": gross, "bar_gross_bps": trade.gross_bps,
            "entry_spread_bps": ((float(entry.ask_price) / float(entry.bid_price) - 1) * 10000 if entry is not None else np.nan),
            "entry_quote_age_seconds": ((trade.entry_ts - entry.quote_ts).total_seconds() if entry is not None else np.nan),
            "exit_quote_age_seconds": ((trade.exit_ts - exit_quote.quote_ts).total_seconds() if exit_quote is not None else np.nan),
        })
    detail = pd.DataFrame(rows); z = detail[detail.covered].copy(); z["date"] = pd.to_datetime(z.session_date)
    summaries = []
    for cost in COSTS:
        net = z.quote_gross_bps - 2 * cost
        early = z.date < pd.Timestamp("2025-11-01")
        monthly = pd.DataFrame({"month": z.date.dt.strftime("%Y-%m"), "net": net}).groupby("month").net.sum()
        summaries.append({
            "cost_bps_per_side": cost, "attempts": len(detail), "covered": len(z),
            "mean_bps": net.mean(), "first_half_bps": net[early].mean(),
            "second_half_bps": net[~early].mean(), "win_rate": (net > 0).mean(),
            "positive_months": int((monthly > 0).sum()), "months": len(monthly),
            "bar_quote_correlation": z[["bar_gross_bps", "quote_gross_bps"]].corr().iloc[0, 1],
            "mean_entry_spread_bps": z.entry_spread_bps.mean(),
        })
    return detail, pd.DataFrame(summaries)


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    frame = signals(); frame.to_parquet(DEST / "signals.parquet", index=False)
    quotes, errors = download(frame); quotes.to_parquet(DEST / "downloaded_quotes.parquet", index=False)
    detail, summary = replay(frame, quotes)
    detail.to_parquet(DEST / "replay_detail.parquet", index=False); summary.to_csv(DEST / "summary.csv", index=False)
    (DEST / "status.json").write_text(json.dumps({
        "status": "complete" if not errors and detail.covered.all() else "partial",
        "errors": errors, "replication_accessed": False, "final_holdout_accessed": False,
    }, indent=2))
    print(summary.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
