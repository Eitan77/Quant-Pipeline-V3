"""Two-hour SPY/QQQ 5-minute-momentum probe using the shared SIP replay."""
from __future__ import annotations

import json
import argparse
import shutil
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import momentum_micro_scalp_discovery as core


core.OUT = core.ROOT / "research/momentum_micro_scalp_hf_20260929"
core.CACHE = core.OUT / "quote_windows"
DAYS = ["2025-06-17", "2026-03-17"]
EXPANDED_DAYS = [
    "2025-05-20", "2025-06-17", "2025-07-15", "2025-09-16",
    "2025-11-18", "2026-01-20", "2026-03-17", "2026-04-14",
]
CONFIRMATION_DAYS = ["2026-04-21", "2026-04-28"]


def prepare(days: list[str], symbols: list[str] | None = None, bidirectional: bool = False) -> pd.DataFrame:
    core.OUT.mkdir(parents=True, exist_ok=True)
    core.CACHE.mkdir(exist_ok=True)
    dates = ",".join(f"'{x}'" for x in days)
    symbols = symbols or ["SPY", "QQQ"]
    symbol_sql = ",".join(f"'{x}'" for x in symbols)
    sql = f"""
    WITH dedup AS (
      SELECT symbol, session_date, bar_start_ts_utc, open, high, low, close,
             volume, trade_count,
             row_number() OVER (PARTITION BY symbol, bar_start_ts_utc
                                ORDER BY ingest_batch_id DESC) AS rn
      FROM bars_1m_raw
      WHERE symbol IN ({symbol_sql}) AND session_date IN ({dates})
        AND CAST(timezone('America/New_York',bar_start_ts_utc) AS TIME)
            BETWEEN TIME '09:30:00' AND TIME '15:59:00'
    ) SELECT * EXCLUDE(rn) FROM dedup WHERE rn=1
      ORDER BY symbol,bar_start_ts_utc
    """
    with duckdb.connect(str(core.CATALOG), read_only=True) as con:
        bars = con.execute(sql).fetchdf()
    bars.bar_start_ts_utc = pd.to_datetime(bars.bar_start_ts_utc, utc=True)
    frames = []
    for (_, _), g in bars.groupby(["symbol", "session_date"], sort=False):
        g = g.sort_values("bar_start_ts_utc").copy()
        ret = g.close.pct_change()
        prior = g.close.shift(5)
        low5 = g.low.rolling(5).min()
        high5 = g.high.rolling(5).max()
        z = g.loc[prior.notna(), ["symbol", "session_date", "bar_start_ts_utc", "close", "volume"]].copy()
        ix = z.index
        z["lookback"] = 5
        z["momentum_bps"] = (g.loc[ix, "close"] / prior.loc[ix] - 1) * 10000
        z["last1_bps"] = ret.loc[ix] * 10000
        z["positive_fraction"] = ret.gt(0).rolling(5).mean().loc[ix]
        z["close_location5"] = ((g.close - low5) / (high5 - low5).replace(0, np.nan)).loc[ix]
        z["volume_ratio20"] = (g.volume / g.volume.shift(1).rolling(20).median()).loc[ix]
        z["acceleration_bps"] = ((g.close / g.close.shift(2) - 1) - (g.close.shift(2) / g.close.shift(5) - 1)).loc[ix] * 10000
        z["request_ts"] = z.bar_start_ts_utc + pd.Timedelta(minutes=1, milliseconds=250)
        z["month"] = z.request_ts.dt.strftime("%Y-%m")
        frames.append(z)
    sample = pd.concat(frames, ignore_index=True)
    local = sample.request_ts.dt.tz_convert("America/New_York")
    sample = sample[(sample.momentum_bps.ne(0) if bidirectional else sample.momentum_bps.gt(0)) & local.dt.hour.eq(12)].copy()
    sample["side"] = np.where(sample.momentum_bps >= 0, 1, -1)
    sample = sample.sort_values(["request_ts", "symbol"]).reset_index(drop=True)
    sample.insert(0, "attempt_id", np.arange(len(sample), dtype=np.int64))
    sample.to_parquet(core.OUT / "signal_sample.parquet", index=False)
    (core.OUT / "scope.json").write_text(json.dumps({
        "days": days, "window_et": "12:00-12:59 every minute", "symbols": symbols,
        "lookback_minutes": 5, "attempts": len(sample), "commissions_bps": 0,
        "bidirectional": bidirectional, "replication_accessed": False, "final_holdout_accessed": False,
    }, indent=2))
    print("PREPARED", len(sample), "positive 5m attempts", flush=True)
    return sample


def selective_report(sample: pd.DataFrame) -> None:
    micro_rows = []
    for row in sample.itertuples():
        q = core.valid_quotes(pd.read_parquet(core.cache_path(row)))
        ns = pd.Timestamp(row.request_ts).value
        arrivals = q[(q.ns >= ns) & (q.ns <= ns + 1_000_000_000)]
        if arrivals.empty:
            continue
        arrival = arrivals.iloc[0]
        side = int(row.side)
        denom = float(arrival.bid_size + arrival.ask_size)
        mid = (float(arrival.bid) + float(arrival.ask)) / 2
        microprice = (float(arrival.ask) * float(arrival.bid_size) + float(arrival.bid) * float(arrival.ask_size)) / denom
        recent = q[(q.ns >= ns - 2_000_000_000) & (q.ns <= int(arrival.ns))]
        ofi = 0.0
        if len(recent) > 1:
            prev = recent.shift(1)
            event = (
                np.where(recent.bid >= prev.bid, recent.bid_size, 0)
                - np.where(recent.bid <= prev.bid, prev.bid_size, 0)
                - np.where(recent.ask <= prev.ask, recent.ask_size, 0)
                + np.where(recent.ask >= prev.ask, prev.ask_size, 0)
            )
            ofi = float(np.nansum(event[1:]))
        ofi_scale = float(recent.bid_size.add(recent.ask_size).median()) if len(recent) else 1.0
        micro_rows.append({
            "attempt_id": int(row.attempt_id),
            "queue_imbalance": (float(arrival.bid_size) / denom if side == 1 else float(arrival.ask_size) / denom),
            "microprice_edge_bps": side * (microprice / mid - 1) * 10000,
            "spread_cents": (float(arrival.ask) - float(arrival.bid)) * 100,
            "updates_2s": len(recent),
            "ofi_2s": side * ofi,
            "ofi_norm_2s": side * ofi / max(ofi_scale, 1.0),
        })
    micro = pd.DataFrame(micro_rows)
    micro.to_parquet(core.OUT / "arrival_microstructure.parquet", index=False)
    replay = pd.read_parquet(core.OUT / "replay.parquet")
    frame = replay.merge(sample[["attempt_id", "last1_bps", "positive_fraction", "close_location5", "volume_ratio20", "acceleration_bps"]], on="attempt_id").merge(micro,on="attempt_id")
    frame = frame[frame.fee_bps == 0]
    filters = {
        "all_positive_5m": np.ones(len(frame), dtype=bool),
        "last_minute_positive": frame.last1_bps > 0,
        "at_least_4_of_5_green": frame.positive_fraction >= .8,
        "close_near_5m_high": frame.close_location5 >= .8,
        "positive_acceleration": frame.acceleration_bps > 0,
        "above_median_relative_volume": frame.volume_ratio20 >= 1,
        "green_and_near_high": (frame.positive_fraction >= .6) & (frame.close_location5 >= .8),
        "volume_ge_median": frame.volume_ratio20 >= 1,
        "bid_imbalance_ge_55": frame.queue_imbalance >= .55,
        "bid_imbalance_ge_60": frame.queue_imbalance >= .60,
        "volume_and_bid_imbalance": (frame.volume_ratio20 >= 1) & (frame.queue_imbalance >= .55),
        "positive_microprice": frame.microprice_edge_bps > 0,
        "ofi_positive": frame.ofi_norm_2s > 0,
        "volume_and_ofi_positive": (frame.volume_ratio20 >= 1) & (frame.ofi_norm_2s > 0),
    }
    rows = []
    keys = ["entry_method", "entry_wait_seconds", "target_net_bps", "hold_seconds"]
    for name, mask in filters.items():
        z = frame[mask]
        s = z.groupby(keys).agg(attempts=("attempt_id", "size"), targets=("target_filled", "sum"),
                               forced=("forced_exit", "sum"), bps_attempt=("net_bps", "mean"),
                               total_bps=("net_bps", "sum")).reset_index()
        s["filter"] = name
        rows.append(s)
    result = pd.concat(rows, ignore_index=True)
    result.to_parquet(core.OUT / "selective_summary.parquet", index=False)
    eligible = result[(result.attempts >= 20)].sort_values("bps_attempt", ascending=False)
    eligible.to_csv(core.OUT / "selective_top.csv", index=False)
    print("SELECTIVE TOP\n", eligible.head(25).to_string(index=False), flush=True)


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--expanded",action="store_true")
    parser.add_argument("--confirmation",action="store_true")
    parser.add_argument("--bidirectional",action="store_true")
    parser.add_argument("--bidirectional-confirmation",action="store_true")
    args=parser.parse_args()
    bidirectional=args.bidirectional or args.bidirectional_confirmation
    days=CONFIRMATION_DAYS if (args.confirmation or args.bidirectional_confirmation) else EXPANDED_DAYS if (args.expanded or args.bidirectional) else DAYS
    symbols=["QQQ"] if (args.confirmation or args.bidirectional_confirmation) else ["SPY","QQQ"]
    if args.bidirectional_confirmation:
        core.OUT=core.ROOT / "research/momentum_micro_scalp_hf_bidirectional_confirmation_20260929"
        core.CACHE=core.OUT / "quote_windows"
        core.FEE_CASES=[0]
    elif args.bidirectional:
        core.OUT=core.ROOT / "research/momentum_micro_scalp_hf_bidirectional_20260929"
        core.CACHE=core.OUT / "quote_windows"
        core.FEE_CASES=[0]
    elif args.confirmation:
        core.OUT=core.ROOT / "research/momentum_micro_scalp_hf_confirmation_20260929"
        core.CACHE=core.OUT / "quote_windows"
    elif args.expanded:
        core.OUT=core.ROOT / "research/momentum_micro_scalp_hf_expanded_20260929"
        core.CACHE=core.OUT / "quote_windows"
    sample = prepare(days,symbols,bidirectional)
    if bidirectional:
        prior=core.ROOT / ("research/momentum_micro_scalp_hf_confirmation_20260929/quote_windows" if args.bidirectional_confirmation else "research/momentum_micro_scalp_hf_expanded_20260929/quote_windows")
        for row in sample.itertuples():
            target=core.cache_path(row); source=prior/target.name
            if source.exists() and not target.exists(): shutil.copy2(source,target)
    core.download(sample, workers=4)
    core.replay(sample)
    selective_report(sample)


if __name__ == "__main__":
    main()
