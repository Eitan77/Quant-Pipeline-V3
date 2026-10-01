"""Exact SIP marketable replay for the frozen C0246 bar candidate."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from fresh_overnight_quote_replay import api_headers, fetch_window
from intraday_strategy_search import ROOT, OUT


SOURCE = OUT / "volume_volatility_exit_audit"
DEST = SOURCE / "quote_replay_nbbo"
COSTS_PER_SIDE = [-1, 0, 1, 2, 3, 5]
ALIASES = {"FB": "META", "CDAY": "DAY", "PEAK": "DOC", "JEC": "J", "UTX": "RTX", "WRK": "SW", "VIAC": "PARA"}


def signals() -> pd.DataFrame:
    frame = pd.read_parquet(SOURCE / "baseline_trades.parquet").copy()
    if len(frame) != 261:
        raise RuntimeError(f"Expected 261 frozen trades, found {len(frame)}")
    catalog = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\cache\source\20240401_20260430\catalog.duckdb")
    with duckdb.connect(str(catalog), read_only=True) as con:
        keys = frame[["security_id", "session_date"]].drop_duplicates().copy()
        keys["session_date"] = pd.to_datetime(keys.session_date).dt.date
        con.register("trade_keys", keys)
        master = con.execute("""
            SELECT DISTINCT k.security_id,k.session_date,b.symbol
            FROM trade_keys k JOIN bars_1m_raw b
              ON b.security_id=k.security_id AND b.session_date=k.session_date
        """).fetchdf()
    frame["session_date"] = pd.to_datetime(frame.session_date).dt.strftime("%Y-%m-%d")
    master["session_date"] = pd.to_datetime(master.session_date).dt.strftime("%Y-%m-%d")
    frame = frame.merge(master, on=["security_id", "session_date"], how="left", validate="many_to_one")
    if frame.symbol.isna().any():
        raise RuntimeError("Unmapped security IDs")
    frame["symbol"] = frame.symbol.replace(ALIASES)
    frame["entry_ts"] = pd.to_datetime(frame.entry_minute, unit="m", utc=True)
    frame["exit_ts"] = pd.to_datetime(frame.exit_minute, unit="m", utc=True)
    frame["trade_id"] = np.arange(len(frame), dtype=np.int64)
    return frame


def download(frame: pd.DataFrame, workers: int = 6) -> tuple[pd.DataFrame, list[dict]]:
    headers = api_headers()
    quote_dir = DEST / "quotes"
    quote_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for leg, column in [("entry", "entry_ts"), ("exit", "exit_ts")]:
        for timestamp, group in frame.groupby(column, sort=True):
            jobs.append((leg, pd.Timestamp(timestamp), sorted(group.symbol.unique())))

    def one(job):
        leg, timestamp, symbols = job
        path = quote_dir / f"{leg}_{timestamp.strftime('%Y%m%dT%H%M%S%z')}.parquet"
        cached = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        present = set(cached.symbol.unique()) if len(cached) else set()
        missing = sorted(set(symbols) - present)
        if missing:
            cached = pd.concat(
                [cached, fetch_window(timestamp - pd.Timedelta(seconds=30), missing, headers)],
                ignore_index=True,
            )
            cached.to_parquet(path, index=False)
        cached["leg"], cached["window_ts"] = leg, timestamp
        return cached

    frames, errors = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, job): job for job in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                frames.append(future.result())
            except Exception as exc:
                leg, timestamp, symbols = futures[future]
                errors.append({"leg": leg, "timestamp": timestamp.isoformat(),
                               "symbols": symbols, "error": type(exc).__name__})
            if index % 50 == 0 or index == len(jobs):
                print("DOWNLOAD", index, "/", len(jobs), "errors", len(errors), flush=True)
    return pd.concat(frames, ignore_index=True), errors


def first_arrival(path: pd.DataFrame, timestamp: pd.Timestamp):
    valid = path[(path.bid_price > 0) & (path.ask_price >= path.bid_price)
                 & (path.bid_size > 0) & (path.ask_size > 0)].sort_values("quote_ts")
    before = valid[(valid.quote_ts <= timestamp) &
                   (valid.quote_ts >= timestamp - pd.Timedelta(seconds=5))]
    if not before.empty:
        return before.iloc[-1]
    arrival = valid[(valid.quote_ts > timestamp) &
                    (valid.quote_ts <= timestamp + pd.Timedelta(seconds=1))]
    return None if arrival.empty else arrival.iloc[0]


def replay(frame: pd.DataFrame, quotes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    paths = {(leg, ts, symbol): group for (leg, ts, symbol), group in
             quotes.groupby(["leg", "window_ts", "symbol"], sort=False)}
    rows = []
    for trade in frame.itertuples():
        entry_path = paths.get(("entry", trade.entry_ts, trade.symbol), pd.DataFrame())
        exit_path = paths.get(("exit", trade.exit_ts, trade.symbol), pd.DataFrame())
        entry = first_arrival(entry_path, trade.entry_ts) if len(entry_path) else None
        exit_quote = first_arrival(exit_path, trade.exit_ts) if len(exit_path) else None
        covered = entry is not None and exit_quote is not None
        gross = (float(exit_quote.bid_price) / float(entry.ask_price) - 1) * 10000 if covered else np.nan
        rows.append({
            "trade_id": int(trade.trade_id), "session_date": trade.session_date,
            "symbol": trade.symbol, "entry_ts": trade.entry_ts, "exit_ts": trade.exit_ts,
            "covered": covered, "entry_ask": float(entry.ask_price) if entry is not None else np.nan,
            "exit_bid": float(exit_quote.bid_price) if exit_quote is not None else np.nan,
            "entry_spread_bps": ((float(entry.ask_price) / float(entry.bid_price) - 1) * 10000
                                 if entry is not None else np.nan),
            "exit_spread_bps": ((float(exit_quote.ask_price) / float(exit_quote.bid_price) - 1) * 10000
                                if exit_quote is not None else np.nan),
            "quote_gross_bps": gross, "bar_gross_bps": float(trade.gross_bps),
        })
    detail = pd.DataFrame(rows)
    complete = detail[detail.covered].copy()
    summaries = []
    all_dates = sorted(detail.session_date.astype(str).unique())
    for cost in COSTS_PER_SIDE:
        z = complete.assign(net_bps=complete.quote_gross_bps - 2 * cost,
                            net_return=(complete.quote_gross_bps - 2 * cost) / 10000)
        daily = z.groupby(z.session_date.astype(str)).net_return.sum().reindex(all_dates, fill_value=0)
        equity = (1 + daily).cumprod()
        peak = equity.cummax()
        monthly = z.groupby(pd.to_datetime(z.session_date).dt.strftime("%Y-%m")).net_return.sum()
        summaries.append({
            "cost_bps_per_side": cost, "attempts": len(detail), "completed": len(z),
            "coverage": len(z) / len(detail), "mean_bps": z.net_bps.mean(),
            "median_bps": z.net_bps.median(), "win_rate": (z.net_bps > 0).mean(),
            "additive_return": z.net_return.sum(), "compounded_daily_return": equity.iloc[-1] - 1,
            "max_drawdown": (1 - equity / peak).max(),
            "positive_months": int((monthly > 0).sum()), "months": len(monthly),
            "bar_quote_correlation": z[["bar_gross_bps", "quote_gross_bps"]].corr().iloc[0, 1],
        })
    return detail, pd.DataFrame(summaries)


def spread_diagnostics(detail: pd.DataFrame) -> pd.DataFrame:
    complete = detail[detail.covered].copy()
    complete["session_date"] = pd.to_datetime(complete.session_date)
    rows = []
    for cap in [.5, 1, 2, 3, 5, 10]:
        z = complete[complete.entry_spread_bps <= cap].copy()
        for cost in [0, 1, 2]:
            pnl = z.quote_gross_bps - 2 * cost
            early = z.session_date < pd.Timestamp("2025-11-01")
            monthly = pd.DataFrame({"month": z.session_date.dt.strftime("%Y-%m"), "pnl": pnl}).groupby("month").pnl.sum()
            rows.append({
                "entry_spread_cap_bps": cap, "cost_bps_per_side": cost, "trades": len(z),
                "mean_bps": pnl.mean(), "first_half_bps": pnl[early].mean(),
                "second_half_bps": pnl[~early].mean(),
                "positive_months": int((monthly > 0).sum()), "months": len(monthly),
                "mean_entry_spread_bps": z.entry_spread_bps.mean(),
                "mean_exit_spread_bps": z.exit_spread_bps.mean(),
            })
    return pd.DataFrame(rows)


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    frame = signals()
    frame.to_parquet(DEST / "signals.parquet", index=False)
    quotes, errors = download(frame)
    quotes.to_parquet(DEST / "downloaded_quotes.parquet", index=False)
    detail, summary = replay(frame, quotes)
    detail.to_parquet(DEST / "replay_detail.parquet", index=False)
    summary.to_csv(DEST / "summary.csv", index=False)
    spread = spread_diagnostics(detail)
    spread.to_csv(DEST / "spread_diagnostics.csv", index=False)
    (DEST / "status.json").write_text(json.dumps({
        "status": "complete" if not errors and detail.covered.all() else "partial",
        "signals": len(frame), "errors": errors,
        "replication_accessed": False, "final_holdout_accessed": False,
    }, indent=2))
    print(summary.to_string(index=False), flush=True)
    print(spread.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
