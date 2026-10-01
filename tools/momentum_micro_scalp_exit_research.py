"""Exit-policy research on frozen momentum micro-scalp quote paths."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import momentum_micro_scalp_discovery as core


ROOT = core.ROOT / "research"


def entry_fill(row, quotes: pd.DataFrame, method: str):
    ns = pd.Timestamp(row.request_ts).value
    arrivals = quotes[(quotes.ns >= ns) & (quotes.ns <= ns + 1_000_000_000)]
    if arrivals.empty:
        return None
    first = arrivals.iloc[0]
    side = int(row.side)
    if method == "market":
        return int(first.ns), float(first.ask if side == 1 else first.bid), False
    wait = int(method.replace("hybrid", ""))
    limit = (np.floor((first.bid + 1e-10) * 100) / 100 if side == 1
             else np.ceil((first.ask - 1e-10) * 100) / 100)
    through = quotes[(quotes.ns > first.ns) & (quotes.ns <= first.ns + wait * 1e9)]
    through = through[through.ask < limit] if side == 1 else through[through.bid > limit]
    if not through.empty:
        return int(through.iloc[0].ns), float(limit), True
    deadline = int(first.ns + wait * 1e9)
    cross = quotes[(quotes.ns >= deadline) & (quotes.ns <= deadline + 1e9)]
    if cross.empty:
        return None
    q = cross.iloc[0]
    return int(q.ns), float(q.ask if side == 1 else q.bid), False


def configurations():
    configs = []
    for target in [2, 3, 4, 5, 7]:
        for stop in [None, 2, 3, 5]:
            configs.append((f"fixed_t{target}_s{stop or 0}", target, stop, None, None))
    for activation in [1, 2, 3]:
        configs.append((f"breakeven_t5_a{activation}", 5, None, activation, 0))
    for target in [5, 7]:
        for activation in [2, 3]:
            for trail in [1, 2]:
                configs.append((f"trail_t{target}_a{activation}_d{trail}", target, None, activation, trail))
    return configs


def replay(dataset: str, rule: str) -> None:
    folder = ROOT / dataset
    core.OUT = folder
    core.CACHE = folder / "quote_windows"
    sample = pd.read_parquet(folder / "signal_sample.parquet")
    micro = pd.read_parquet(folder / "arrival_microstructure.parquet")
    sample = sample.merge(micro, on="attempt_id")
    if rule == "long":
        selected = sample[(sample.side == 1) & (sample.volume_ratio20 >= 1)
                          & (sample.ofi_norm_2s > 0) & (sample.last1_bps > 0)]
    else:
        selected = sample[(sample.side == -1) & (sample.queue_imbalance >= .55)]
    rows = []
    for signal in selected.itertuples():
        quotes = core.valid_quotes(pd.read_parquet(core.cache_path(signal)))
        for method in ["market", "hybrid1", "hybrid5"]:
            fill = entry_fill(signal, quotes, method)
            if fill is None:
                continue
            fill_ns, entry, passive_fill = fill
            side = int(signal.side)
            deadline = fill_ns + int(60e9)
            path = quotes[(quotes.ns > fill_ns) & (quotes.ns <= deadline)]
            if path.empty:
                continue
            executable = path.bid.to_numpy() if side == 1 else path.ask.to_numpy()
            favorable = side * (executable / entry - 1) * 10000
            times = path.ns.to_numpy()
            for name, target_bps, hard_stop, activation, trail in configurations():
                target_raw = entry * (1 + side * target_bps / 10000)
                target = (np.ceil(target_raw * 100 - 1e-10) / 100 if side == 1
                          else np.floor(target_raw * 100 + 1e-10) / 100)
                exit_price = float(executable[-1]); exit_ns = int(times[-1])
                reason = "timeout"; max_favorable = -np.inf; armed = False
                for quote_ns, price, fav in zip(times, executable, favorable):
                    target_hit = price > target if side == 1 else price < target
                    if target_hit:
                        exit_price = float(target); exit_ns = int(quote_ns); reason = "target"; break
                    max_favorable = max(max_favorable, float(fav))
                    if hard_stop is not None and fav <= -hard_stop:
                        exit_price = float(price); exit_ns = int(quote_ns); reason = "hard_stop"; break
                    if activation is not None and max_favorable >= activation:
                        armed = True
                    if armed and trail is not None:
                        trigger = fav <= 0 if trail == 0 else fav <= max_favorable - trail
                        if trigger:
                            exit_price = float(price); exit_ns = int(quote_ns)
                            reason = "breakeven" if trail == 0 else "trailing"; break
                rows.append({
                    "attempt_id": int(signal.attempt_id), "session_date": signal.session_date,
                    "symbol": signal.symbol, "request_ts": signal.request_ts,
                    "selection_score": float(signal.ofi_norm_2s if side == 1 else signal.queue_imbalance),
                    "side": side, "entry_method": method, "passive_fill": passive_fill,
                    "policy": name, "target_bps": target_bps, "exit_reason": reason,
                    "net_bps": side * (exit_price / entry - 1) * 10000,
                    "entry_ns": fill_ns, "exit_ns": exit_ns,
                    "occupancy_seconds": (exit_ns - fill_ns) / 1e9,
                })
    result = pd.DataFrame(rows)
    result.to_parquet(folder / f"{rule}_exit_replay.parquet", index=False)
    summary = result.groupby(["entry_method", "policy", "target_bps"]).agg(
        attempts=("attempt_id", "size"), mean_bps=("net_bps", "mean"), total_bps=("net_bps", "sum"),
        targets=("exit_reason", lambda x: int((x == "target").sum())),
        stops=("exit_reason", lambda x: int(x.isin(["hard_stop", "breakeven", "trailing"]).sum())),
        worst=("net_bps", "min"),
    ).reset_index()
    daily = result.groupby(["entry_method", "policy", "session_date"]).net_bps.sum().reset_index()
    stability = daily.groupby(["entry_method", "policy"]).agg(
        positive_days=("net_bps", lambda x: int((x > 0).sum())), median_day=("net_bps", "median"),
        worst_day=("net_bps", "min"), best_day=("net_bps", "max"),
    ).reset_index()
    summary = summary.merge(stability, on=["entry_method", "policy"], how="left")
    summary.to_csv(folder / f"{rule}_exit_summary.csv", index=False)
    slot_rows = []
    for (method, policy), group in result.groupby(["entry_method", "policy"]):
        for slots in [1, 2, 4]:
            picked = []
            for _, day in group.groupby("session_date"):
                available = [0] * slots
                for row in day.sort_values(
                    ["request_ts", "selection_score", "attempt_id"],
                    ascending=[True, False, True],
                ).itertuples():
                    slot = int(np.argmin(available))
                    if available[slot] <= row.entry_ns:
                        available[slot] = row.exit_ns
                        picked.append(row)
            p = pd.DataFrame(picked)
            daily_pnl = p.groupby("session_date").net_bps.sum()
            slot_rows.append({
                "entry_method": method, "policy": policy, "slots": slots,
                "selected": len(p), "mean_bps": p.net_bps.mean(),
                "total_bps": p.net_bps.sum(),
                "positive_days": int((daily_pnl > 0).sum()),
                "median_day": daily_pnl.median(), "worst_day": daily_pnl.min(),
            })
    pd.DataFrame(slot_rows).to_csv(folder / f"{rule}_finite_slot_summary.csv", index=False)
    print(json.dumps({"dataset": dataset, "rule": rule, "signals": len(selected), "replay_rows": len(result)}))
    print(summary.sort_values(["positive_days", "mean_bps"], ascending=False).head(25).to_string(index=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--rule", choices=["long", "short"], required=True)
    args = parser.parse_args()
    replay(args.dataset, args.rule)


if __name__ == "__main__":
    main()
