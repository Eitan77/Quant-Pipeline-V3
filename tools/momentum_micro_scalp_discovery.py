"""Discovery-only quote replay for tiny-target momentum scalping.

Uses only 2025-05-01 through 2026-04-30. Passive fills require strict NBBO
move-through; every filled entry is either sold at its target or forced out at
the bid. Results are per attempted signal so cancelled entries are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import duckdb
import numpy as np
import pandas as pd
from dotenv import dotenv_values


START = "2025-05-01"
END = "2026-04-30"
UNIVERSE = [
    "SPY", "QQQ", "TSLA", "NVDA", "MSFT", "AAPL", "META", "AMZN",
    "GOOGL", "AVGO", "AMD", "NFLX", "JPM", "XOM", "BAC",
]
LOOKBACKS = [5, 15, 30, 60, 120]
FEE_CASES = [-1, 0, 0.25, 0.5, 1, 2]
TARGETS = [1, 2, 3, 4, 5]
QUICK_DAYS = ["2025-06-17", "2026-03-17"]
QUICK_UNIVERSE = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMD"]
ROOT = Path("D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923")
OUT = ROOT / "research/momentum_micro_scalp_20260929"
CACHE = OUT / "quote_windows"
CATALOG = Path("D:/AlgoResearch/Quant-Pipeline-V3/cache/source/20240401_20260430/catalog.duckdb")


def prepare(per_symbol_month: int, quick: bool = False) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    active_universe = QUICK_UNIVERSE if quick else UNIVERSE
    symbols = ",".join(f"'{x}'" for x in active_universe)
    date_filter = (
        "session_date IN (" + ",".join(f"'{x}'" for x in QUICK_DAYS) + ")"
        if quick else f"session_date BETWEEN '{START}' AND '{END}'"
    )
    sql = f"""
    WITH dedup AS (
      SELECT symbol, session_date, bar_start_ts_utc, open, high, low, close,
             volume, trade_count,
             row_number() OVER (
               PARTITION BY symbol, bar_start_ts_utc
               ORDER BY ingest_batch_id DESC
             ) AS rn
      FROM bars_1m_raw
      WHERE symbol IN ({symbols})
        AND {date_filter}
        AND CAST(timezone('America/New_York', bar_start_ts_utc) AS TIME)
            BETWEEN TIME '09:30:00' AND TIME '15:59:00'
    )
    SELECT * EXCLUDE(rn) FROM dedup WHERE rn=1
    ORDER BY symbol, bar_start_ts_utc
    """
    with duckdb.connect(str(CATALOG), read_only=True) as con:
        bars = con.execute(sql).fetchdf()
    bars["bar_start_ts_utc"] = pd.to_datetime(bars.bar_start_ts_utc, utc=True)
    bars["month"] = bars.bar_start_ts_utc.dt.strftime("%Y-%m")
    candidates = []
    for (_, _), g in bars.groupby(["symbol", "session_date"], sort=False):
        g = g.sort_values("bar_start_ts_utc").copy()
        # Require a continuous lookback and order arrival at the completed bar end.
        minute_delta = g.bar_start_ts_utc.diff().dt.total_seconds().div(60)
        continuous = minute_delta.eq(1).rolling(max(LOOKBACKS), min_periods=1).sum()
        for lookback in LOOKBACKS:
            prior = g.close.shift(lookback)
            valid = prior.notna() & continuous.ge(lookback)
            z = g.loc[valid, ["symbol", "session_date", "bar_start_ts_utc", "month", "close", "volume"]].copy()
            z["lookback"] = lookback
            z["momentum_bps"] = (g.loc[valid, "close"].to_numpy() / prior.loc[valid].to_numpy() - 1) * 10000
            z = z[z.momentum_bps > 0]
            z["request_ts"] = z.bar_start_ts_utc + pd.Timedelta(minutes=1, milliseconds=250)
            candidates.append(z)
    all_candidates = pd.concat(candidates, ignore_index=True)
    all_candidates["hash"] = [
        hashlib.sha256(f"{s}|{t.isoformat()}|{lb}|20260929".encode()).hexdigest()
        for s, t, lb in zip(all_candidates.symbol, all_candidates.request_ts, all_candidates.lookback)
    ]
    if quick:
        local = all_candidates.request_ts.dt.tz_convert("America/New_York")
        sample = all_candidates[
            local.dt.hour.eq(12) & local.dt.minute.mod(5).eq(0)
        ].sort_values(["request_ts", "symbol", "lookback"]).reset_index(drop=True)
    else:
        # Fixed balanced sample: every symbol/month/lookback contributes equally when available.
        sample = (
            all_candidates.sort_values("hash")
            .groupby(["symbol", "month", "lookback"], group_keys=False)
            .head(per_symbol_month)
            .sort_values(["request_ts", "symbol", "lookback"])
            .reset_index(drop=True)
        )
    sample.insert(0, "attempt_id", np.arange(len(sample), dtype=np.int64))
    sample.to_parquet(OUT / "signal_sample.parquet", index=False)
    frequency = (
        all_candidates.groupby(["symbol", "lookback", "month"])
        .agg(signals=("request_ts", "size"), median_momentum_bps=("momentum_bps", "median"))
        .reset_index()
    )
    frequency.to_parquet(OUT / "signal_frequency.parquet", index=False)
    scope = {
        "discovery_start": START,
        "discovery_end": END,
        "replication_accessed": False,
        "final_holdout_accessed": False,
        "universe": active_universe,
        "lookbacks_minutes": LOOKBACKS,
        "per_symbol_month": per_symbol_month,
        "sample_attempts": len(sample),
        "candidate_signals": len(all_candidates),
        "arrival_latency_ms": 250,
        "max_quote_path_seconds": 80,
        "quick_probe": quick,
        "quick_days": QUICK_DAYS if quick else None,
        "quick_window_et": "12:00-12:59 every 5 minutes" if quick else None,
    }
    (OUT / "scope.json").write_text(json.dumps(scope, indent=2))
    print("PREPARED", json.dumps(scope), flush=True)
    return sample


def credentials() -> dict[str, str]:
    values = dotenv_values("D:/AlgoResearch/.env")
    headers = {
        "APCA-API-KEY-ID": values.get("ALPACA_API_KEY_ID") or values.get("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": values.get("ALPACA_API_SECRET_KEY") or values.get("APCA_API_SECRET_KEY"),
    }
    if not all(headers.values()):
        raise RuntimeError("Alpaca credentials are unavailable")
    return headers


def cache_path(row) -> Path:
    stamp = pd.Timestamp(row.request_ts).strftime("%Y%m%dT%H%M%S%f")
    return CACHE / f"{row.symbol}_{stamp}.parquet"


def fetch_window(row, headers: dict[str, str]) -> tuple[int, str | None]:
    path = cache_path(row)
    if path.exists():
        return int(row.attempt_id), None
    start = pd.Timestamp(row.request_ts) - pd.Timedelta(seconds=2)
    end = pd.Timestamp(row.request_ts) + pd.Timedelta(seconds=80)
    token = None
    records = []
    while True:
        params = {
            "symbols": row.symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "feed": "sip",
            "sort": "asc",
            "limit": 10000,
            "asof": start.strftime("%Y-%m-%d"),
        }
        if token:
            params["page_token"] = token
        error = None
        for attempt in range(5):
            try:
                request = Request(
                    "https://data.alpaca.markets/v2/stocks/quotes?" + urlencode(params),
                    headers=headers,
                )
                with urlopen(request, timeout=45) as response:
                    payload = json.load(response)
                error = None
                break
            except Exception as exc:  # network retry is recorded, never converted to no-fill
                error = exc
                time.sleep(min(16, 2**attempt))
        if error is not None:
            return int(row.attempt_id), type(error).__name__
        records.extend(payload.get("quotes", {}).get(row.symbol, []))
        token = payload.get("next_page_token")
        if not token:
            break
    frame = pd.DataFrame(
        [
            {
                "ns": pd.Timestamp(q["t"]).value,
                "bid": q["bp"],
                "ask": q["ap"],
                "bid_size": q["bs"],
                "ask_size": q["as"],
            }
            for q in records
        ],
        columns=["ns", "bid", "ask", "bid_size", "ask_size"],
    )
    frame.to_parquet(path, index=False)
    return int(row.attempt_id), None


def download(sample: pd.DataFrame, workers: int) -> None:
    headers = credentials()
    errors = []
    windows = sample.drop_duplicates(["symbol", "request_ts"])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_window, row, headers): int(row.attempt_id) for row in windows.itertuples()}
        for done, future in enumerate(as_completed(futures), 1):
            attempt_id, error = future.result()
            if error:
                errors.append({"attempt_id": attempt_id, "error_type": error})
            if done % 100 == 0 or done == len(futures):
                print("DOWNLOAD", done, "/", len(futures), "errors", len(errors), flush=True)
    (OUT / "download_errors.json").write_text(json.dumps(errors, indent=2))


def valid_quotes(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame[
        (frame.bid > 0)
        & (frame.ask >= frame.bid)
        & (frame.bid_size > 0)
        & (frame.ask_size > 0)
    ].sort_values("ns", kind="stable")


def replay(sample: pd.DataFrame) -> pd.DataFrame:
    rows = []
    missing = []
    for n, signal in enumerate(sample.itertuples(), 1):
        path = cache_path(signal)
        if not path.exists():
            missing.append(int(signal.attempt_id))
            continue
        quotes = valid_quotes(pd.read_parquet(path))
        request_ns = pd.Timestamp(signal.request_ts).value
        arrival = quotes[(quotes.ns >= request_ns) & (quotes.ns <= request_ns + 1_000_000_000)]
        if arrival.empty:
            missing.append(int(signal.attempt_id))
            continue
        first = arrival.iloc[0]
        side = int(getattr(signal, "side", 1))
        passive_label = "bid" if side == 1 else "ask"
        entry_variants = [("market", 0), (passive_label, 1), (passive_label, 5), (passive_label, 15),
                          ("passive_then_market", 1), ("passive_then_market", 5)]
        for entry_method, entry_wait in entry_variants:
            passive_fill = False
            if entry_method == "market":
                entry_filled = True
                entry_price = float(first.ask if side == 1 else first.bid)
                fill_ns = int(first.ns)
            else:
                entry_limit = (np.floor((float(first.bid) + 1e-10) * 100) / 100 if side == 1
                               else np.ceil((float(first.ask) - 1e-10) * 100) / 100)
                through = quotes[
                    (quotes.ns > first.ns)
                    & (quotes.ns <= first.ns + entry_wait * 1_000_000_000)
                    & ((quotes.ask < entry_limit) if side == 1 else (quotes.bid > entry_limit))
                ]
                entry_filled = not through.empty
                entry_price = float(entry_limit) if entry_filled else np.nan
                fill_ns = int(through.iloc[0].ns) if entry_filled else -1
                passive_fill = entry_filled
                if not entry_filled and entry_method == "passive_then_market":
                    deadline = int(first.ns) + entry_wait * 1_000_000_000
                    cross = quotes[(quotes.ns >= deadline) & (quotes.ns <= deadline + 1_000_000_000)]
                    if not cross.empty:
                        entry_filled = True
                        fill_ns = int(cross.iloc[0].ns)
                        entry_price = float(cross.iloc[0].ask if side == 1 else cross.iloc[0].bid)
            entry_fill_wait_seconds = (fill_ns - int(first.ns)) / 1e9 if entry_filled else float(entry_wait)
            # Include maker-rebate, zero-cost, sub-bp and conservative cases.
            for fee_bps in FEE_CASES:
                for target_net_bps in TARGETS:
                    for hold_seconds in [5, 15, 30, 60]:
                        target_fill = False
                        forced_exit = False
                        exit_price = np.nan
                        wait_seconds = np.nan
                        if entry_filled:
                            target_raw = entry_price * (1 + side * (fee_bps + target_net_bps) / 10000)
                            target = (np.ceil(target_raw * 100 - 1e-10) / 100 if side == 1
                                      else np.floor(target_raw * 100 + 1e-10) / 100)
                            deadline = fill_ns + hold_seconds * 1_000_000_000
                            after = quotes[(quotes.ns > fill_ns) & (quotes.ns <= deadline)]
                            hits = after[after.bid > target] if side == 1 else after[after.ask < target]
                            if not hits.empty:
                                target_fill = True
                                exit_price = float(target)
                                wait_seconds = (int(hits.iloc[0].ns) - fill_ns) / 1e9
                            elif not after.empty:
                                forced_exit = True
                                exit_price = float(after.iloc[-1].bid if side == 1 else after.iloc[-1].ask)
                                wait_seconds = hold_seconds
                        raw_bps = side * (exit_price / entry_price - 1) * 10000 if entry_filled else 0.0
                        net_bps = raw_bps - fee_bps if entry_filled else 0.0
                        rows.append(
                            {
                                "attempt_id": int(signal.attempt_id),
                                "symbol": signal.symbol,
                                "session_date": signal.session_date,
                                "month": signal.month,
                                "request_ts": signal.request_ts,
                                "lookback": int(signal.lookback),
                                "momentum_bps": float(signal.momentum_bps),
                                "side": side,
                                "entry_method": entry_method,
                                "entry_wait_seconds": entry_wait,
                                "fee_bps": fee_bps,
                                "target_net_bps": target_net_bps,
                                "hold_seconds": hold_seconds,
                                "entry_filled": entry_filled,
                                "entry_passive_fill": passive_fill,
                                "entry_fill_wait_seconds": entry_fill_wait_seconds,
                                "target_filled": target_fill,
                                "forced_exit": forced_exit,
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "net_bps": net_bps,
                                "wait_seconds": wait_seconds,
                                "occupancy_seconds": entry_fill_wait_seconds + wait_seconds if entry_filled else entry_fill_wait_seconds,
                                "arrival_spread_bps": (float(first.ask) / float(first.bid) - 1) * 10000,
                            }
                        )
        if n % 100 == 0 or n == len(sample):
            print("REPLAY", n, "/", len(sample), "missing", len(missing), flush=True)
    result = pd.DataFrame(rows)
    result.to_parquet(OUT / "replay.parquet", index=False)
    (OUT / "missing_attempts.json").write_text(json.dumps(missing))
    summarize(result)
    return result


def summarize(result: pd.DataFrame) -> None:
    keys = ["lookback", "entry_method", "entry_wait_seconds", "fee_bps", "target_net_bps", "hold_seconds"]
    summaries = []
    strength = result.side * result.momentum_bps if "side" in result else result.momentum_bps
    for threshold in [0, 5, 10, 20, 50]:
        frame = result[strength >= threshold]
        grouped = frame.groupby(keys)
        summary = grouped.agg(
            attempts=("attempt_id", "size"),
            entry_fills=("entry_filled", "sum"),
            target_fills=("target_filled", "sum"),
            forced_exits=("forced_exit", "sum"),
            net_bps_attempt=("net_bps", "mean"),
            total_net_bps=("net_bps", "sum"),
            median_net_bps=("net_bps", "median"),
            mean_spread_bps=("arrival_spread_bps", "mean"),
        ).reset_index()
        forced = frame[frame.forced_exit].groupby(keys).net_bps.mean().rename("forced_exit_mean_bps").reset_index()
        summary = summary.merge(forced, on=keys, how="left")
        summary["momentum_threshold_bps"] = threshold
        summaries.append(summary)
    summary = pd.concat(summaries, ignore_index=True)
    summary["entry_fill_rate"] = summary.entry_fills / summary.attempts
    summary["target_rate_per_entry"] = summary.target_fills / summary.entry_fills.replace(0, np.nan)
    summary.to_parquet(OUT / "summary.parquet", index=False)
    eligible = summary[(summary.attempts >= 30) & (summary.entry_fills >= 15)]
    top = eligible.sort_values("net_bps_attempt", ascending=False).head(20)
    top.to_csv(OUT / "top_configs.csv", index=False)
    print("TOP CONFIGS\n", top.to_string(index=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["all", "prepare", "download", "replay"], default="all")
    parser.add_argument("--per-symbol-month", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    sample = prepare(args.per_symbol_month, args.quick) if args.stage in {"all", "prepare"} else pd.read_parquet(OUT / "signal_sample.parquet")
    if args.stage in {"all", "download"}:
        download(sample, args.workers)
    if args.stage in {"all", "replay"}:
        replay(sample)


if __name__ == "__main__":
    main()
