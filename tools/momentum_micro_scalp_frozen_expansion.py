"""Frozen discovery expansion for the long momentum micro-scalp candidate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import momentum_micro_scalp_discovery as core


DEV_DAYS = [
    "2025-05-08", "2025-06-05", "2025-07-10", "2025-08-07",
    "2025-09-04", "2025-10-09", "2025-11-06", "2025-12-04",
]
VALIDATION_DAYS = ["2026-01-08", "2026-02-05", "2026-03-05", "2026-04-02"]
DAYS = DEV_DAYS + VALIDATION_DAYS
SYMBOLS = ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA"]
LATENCIES_MS = [250, 500, 1000]
TARGETS_BPS = [5, 7]
COSTS_BPS = [0, 1, 2]
OUT = core.ROOT / "research/momentum_micro_scalp_frozen_expansion_20260929"
CACHE = OUT / "quote_windows"


def prepare() -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    dates = ",".join(f"'{x}'" for x in DAYS)
    symbols = ",".join(f"'{x}'" for x in SYMBOLS)
    sql = f"""
    WITH dedup AS (
      SELECT symbol, session_date, bar_start_ts_utc, close, volume,
             row_number() OVER (PARTITION BY symbol, bar_start_ts_utc
                                ORDER BY ingest_batch_id DESC) AS rn
      FROM bars_1m_raw
      WHERE symbol IN ({symbols}) AND session_date IN ({dates})
        AND CAST(timezone('America/New_York',bar_start_ts_utc) AS TIME)
            BETWEEN TIME '09:30:00' AND TIME '15:59:00'
    ) SELECT * EXCLUDE(rn) FROM dedup WHERE rn=1 ORDER BY symbol,bar_start_ts_utc
    """
    with duckdb.connect(str(core.CATALOG), read_only=True) as con:
        bars = con.execute(sql).fetchdf()
    bars.bar_start_ts_utc = pd.to_datetime(bars.bar_start_ts_utc, utc=True)
    frames = []
    for (_, _), g in bars.groupby(["symbol", "session_date"], sort=False):
        g = g.sort_values("bar_start_ts_utc").copy()
        z = g[["symbol", "session_date", "bar_start_ts_utc", "close", "volume"]].copy()
        z["momentum_bps"] = (g.close / g.close.shift(5) - 1) * 10000
        z["last1_bps"] = g.close.pct_change() * 10000
        z["volume_ratio20"] = g.volume / g.volume.shift(1).rolling(20).median()
        z["signal_ts"] = z.bar_start_ts_utc + pd.Timedelta(minutes=1)
        z["request_ts"] = z.signal_ts + pd.Timedelta(milliseconds=250)
        frames.append(z)
    sample = pd.concat(frames, ignore_index=True)
    local = sample.signal_ts.dt.tz_convert("America/New_York")
    in_window = (local.dt.time >= pd.Timestamp("09:45").time()) & (local.dt.time < pd.Timestamp("15:45").time())
    sample = sample[
        in_window & sample.momentum_bps.gt(0) & sample.last1_bps.gt(0)
        & sample.volume_ratio20.ge(1)
    ].sort_values(["request_ts", "symbol"]).reset_index(drop=True)
    sample.insert(0, "attempt_id", np.arange(len(sample), dtype=np.int64))
    sample["segment"] = np.where(sample.session_date.astype(str).isin(DEV_DAYS), "development", "validation")
    sample.to_parquet(OUT / "signal_sample.parquet", index=False)
    scope = {
        "days": DAYS, "development_days": DEV_DAYS, "validation_days": VALIDATION_DAYS,
        "symbols": SYMBOLS, "window_et": "09:45-15:44", "lookback_minutes": 5,
        "bar_prefilters": ["momentum>0", "last1>0", "volume_ratio20>=1"],
        "quote_filter": "directional_ofi_2s>0", "latencies_ms": LATENCIES_MS,
        "targets_bps": TARGETS_BPS, "timeout_seconds": 60, "cost_stress_bps": COSTS_BPS,
        "attempts_before_ofi": len(sample), "replication_accessed": False,
        "final_holdout_accessed": False,
    }
    (OUT / "scope.json").write_text(json.dumps(scope, indent=2))
    print("PREPARED", json.dumps({"attempts": len(sample), "by_segment": sample.segment.value_counts().to_dict()}), flush=True)
    return sample


def replay(sample: pd.DataFrame) -> pd.DataFrame:
    rows, missing = [], []
    for n, signal in enumerate(sample.itertuples(), 1):
        path = core.cache_path(signal)
        if not path.exists():
            missing.append(int(signal.attempt_id)); continue
        quotes = core.valid_quotes(pd.read_parquet(path))
        signal_ns = pd.Timestamp(signal.signal_ts).value
        for latency_ms in LATENCIES_MS:
            arrival_ns = signal_ns + latency_ms * 1_000_000
            arrivals = quotes[(quotes.ns >= arrival_ns) & (quotes.ns <= arrival_ns + 1_000_000_000)]
            if arrivals.empty:
                continue
            first = arrivals.iloc[0]
            recent = quotes[(quotes.ns >= arrival_ns - 2_000_000_000) & (quotes.ns <= int(first.ns))]
            if len(recent) < 2:
                continue
            prev = recent.shift(1)
            events = (
                np.where(recent.bid >= prev.bid, recent.bid_size, 0)
                - np.where(recent.bid <= prev.bid, prev.bid_size, 0)
                - np.where(recent.ask <= prev.ask, recent.ask_size, 0)
                + np.where(recent.ask >= prev.ask, prev.ask_size, 0)
            )
            scale = float(recent.bid_size.add(recent.ask_size).median())
            ofi_norm = float(np.nansum(events[1:])) / max(scale, 1.0)
            if ofi_norm <= 0:
                continue
            entry_ns, entry = int(first.ns), float(first.ask)
            path60 = quotes[(quotes.ns > entry_ns) & (quotes.ns <= entry_ns + 60_000_000_000)]
            if path60.empty:
                continue
            for target_bps in TARGETS_BPS:
                target = np.ceil(entry * (1 + target_bps / 10000) * 100 - 1e-10) / 100
                hit = path60[path60.bid > target]
                if hit.empty:
                    last = path60.iloc[-1]; exit_ns, exit_price, reason = int(last.ns), float(last.bid), "timeout"
                else:
                    first_hit = hit.iloc[0]; exit_ns, exit_price, reason = int(first_hit.ns), float(target), "target"
                rows.append({
                    "attempt_id": int(signal.attempt_id), "symbol": signal.symbol,
                    "session_date": pd.Timestamp(signal.session_date).strftime("%Y-%m-%d"),
                    "segment": signal.segment,
                    "signal_ts": signal.signal_ts, "latency_ms": latency_ms,
                    "target_bps": target_bps, "ofi_norm_2s": ofi_norm,
                    "momentum_bps": float(signal.momentum_bps),
                    "last1_bps": float(signal.last1_bps),
                    "volume_ratio20": float(signal.volume_ratio20),
                    "spread_bps": (float(first.ask) / float(first.bid) - 1) * 10000,
                    "entry_ns": entry_ns, "exit_ns": exit_ns, "exit_reason": reason,
                    "gross_bps": (exit_price / entry - 1) * 10000,
                    "occupancy_seconds": (exit_ns - entry_ns) / 1e9,
                })
        if n % 500 == 0 or n == len(sample):
            print("REPLAY", n, "/", len(sample), "eligible rows", len(rows), flush=True)
    (OUT / "replay_missing.json").write_text(json.dumps(missing))
    result = pd.DataFrame(rows)
    result.to_parquet(OUT / "frozen_replay.parquet", index=False)
    return result


def summarize(result: pd.DataFrame) -> None:
    all_dates = {"all": DAYS, "development": DEV_DAYS, "validation": VALIDATION_DAYS}
    rows, slot_rows = [], []
    for segment, dates in all_dates.items():
        base = result if segment == "all" else result[result.segment == segment]
        for (latency, target), z in base.groupby(["latency_ms", "target_bps"]):
            for cost in COSTS_BPS:
                pnl = z.assign(net_bps=z.gross_bps - cost)
                daily = pnl.groupby("session_date").net_bps.sum().reindex(dates, fill_value=0)
                rows.append({
                    "segment": segment, "latency_ms": latency, "target_bps": target,
                    "cost_bps": cost, "trades": len(pnl), "mean_bps": pnl.net_bps.mean(),
                    "positive_days": int((daily > 0).sum()), "days": len(dates),
                    "median_day": daily.median(), "worst_day": daily.min(), "best_day": daily.max(),
                })
                for slots in [1, 2]:
                    picked = []
                    for _, day in pnl.groupby("session_date"):
                        available = [0] * slots
                        for row in day.sort_values(["signal_ts", "ofi_norm_2s"], ascending=[True, False]).itertuples():
                            slot = int(np.argmin(available))
                            if available[slot] <= row.entry_ns:
                                available[slot] = row.exit_ns
                                picked.append(row)
                    p = pd.DataFrame(picked)
                    daily_pnl = p.groupby("session_date").net_bps.sum().reindex(dates, fill_value=0)
                    slot_rows.append({
                        "segment": segment, "latency_ms": latency, "target_bps": target,
                        "cost_bps": cost, "slots": slots, "selected": len(p),
                        "mean_bps": p.net_bps.mean(), "positive_days": int((daily_pnl > 0).sum()),
                        "days": len(dates), "median_day": daily_pnl.median(),
                        "worst_day": daily_pnl.min(), "best_day": daily_pnl.max(),
                    })
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False)
    slots = pd.DataFrame(slot_rows)
    slots.to_csv(OUT / "finite_slot_summary.csv", index=False)
    print(slots[(slots.latency_ms == 250) & (slots.slots == 1)].to_string(index=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    core.OUT, core.CACHE = OUT, CACHE
    sample = prepare()
    if args.prepare_only:
        return
    core.download(sample, workers=args.workers)
    result = replay(sample)
    summarize(result)


if __name__ == "__main__":
    main()
