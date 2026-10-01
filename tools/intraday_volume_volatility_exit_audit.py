"""Focused bar-grid audit of the C0246 volume-share/high-volatility long state."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from intraday_entry_search import allocate
from intraday_exit_search import statistics
from intraday_strategy_search import ROOT, OUT, obs_arrays
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
from quant_pipeline.production.evidence_store import EvidenceReader


DEST = OUT / "volume_volatility_exit_audit"
DEST.mkdir(exist_ok=True)


def main() -> None:
    obs, t, day, days, sec, securities, closes = obs_arrays()
    del obs
    axes = json.loads((OUT / "price_axes.json").read_text())
    opens = np.asarray(axes["open_minutes"])
    minute = t - opens[day]
    prices = np.load(OUT / "opens.npy", mmap_mode="r")
    ranks = np.load(OUT / "fine_ranks.npy", mmap_mode="r")
    reader = EvidenceReader(ROOT, "evidence/reader.json", "intraday_5m")
    definitions = pd.read_parquet(OUT / "replay_definitions.parquet").set_index("candidate_id")
    definition = definitions.loc["C0246"]
    a = decode_packed_bins(reader.read_columns("bins", [definition.feature_a], 0, reader.rows)[:, 0], 10)
    b = decode_packed_bins(reader.read_columns("bins", [definition.feature_b], 0, reader.rows)[:, 0], 10)

    rows, ledgers = [], []
    trial = 0
    for cell_a in [6, 7, 8]:
        for cell_b in [6, 7, 8]:
            for vol_floor in [.7, .8, .9]:
                mask = (a == cell_a) & (b == cell_b) & (ranks[:, 7] >= vol_floor)
                ix = np.flatnonzero(mask & (minute >= 5) & (t + 33 <= closes[day] - 5))
                d, s, m = day[ix], sec[ix], minute[ix] + 1
                entry = prices[d, s, m]
                good = np.isfinite(entry)
                ix, d, s, m, entry = ix[good], d[good], s[good], m[good], entry[good]
                offsets = np.arange(32)
                path = prices[d[:, None], s[:, None], np.minimum(m[:, None] + offsets, 389)]
                returns = (path / entry[:, None] - 1) * 10000
                next_valid = np.where(np.isfinite(path), offsets[None, :], 999)
                next_valid = np.minimum.accumulate(next_valid[:, ::-1], axis=1)[:, ::-1]
                recent = prices[d, s, np.maximum(m - 1, 0)] / prices[d, s, np.maximum(m - 6, 0)] - 1
                priorities = {
                    "acceleration": np.nan_to_num(ranks[ix, 4], nan=-1),
                    "recent_move": np.nan_to_num(np.abs(recent), nan=-1),
                }
                for hold in [10, 15, 20, 30]:
                    for tp in [20, 30, 40, 50, 60]:
                        take = returns >= tp; take[:, 0] = False
                        take_at = np.where(take.any(1), take.argmax(1) + 1, 999)
                        for sl in [15, 20, 25, 30, 40]:
                            stop = returns <= -sl; stop[:, 0] = False
                            stop_at = np.where(stop.any(1), stop.argmax(1) + 1, 999)
                            scheduled = np.minimum(np.minimum(take_at, stop_at), hold)
                            actual = next_valid[np.arange(len(ix)), scheduled]
                            valid = actual < 999
                            exit_price = path[np.arange(len(ix)), np.minimum(actual, 31)]
                            pnl = (exit_price / entry - 1) * 10000
                            release = t[ix] + 1 + np.where(valid, actual, hold)
                            for ranking, priority in priorities.items():
                                chosen, _ = allocate(t[ix] + 1, release, s, valid, 1, priority=priority)
                                if len(chosen) < 75 or (~valid[chosen]).any():
                                    continue
                                trial += 1
                                g, ds = pnl[chosen], d[chosen]
                                monthly = pd.DataFrame({"month": pd.to_datetime(days[ds]).strftime("%Y-%m"), "pnl": g}).groupby("month").pnl.sum()
                                daily = np.bincount(ds, weights=g - 2, minlength=len(days))
                                symbol_sum = pd.Series(g).groupby(securities[s[chosen]]).sum()
                                row = {
                                    "trial": trial, "cell_a": cell_a, "cell_b": cell_b,
                                    "vol_floor": vol_floor, "ranking": ranking, "hold": hold,
                                    "tp_bps": tp, "sl_bps": sl, "trades": len(chosen),
                                    "active_days": len(np.unique(ds)), "gross_bps": g.mean(),
                                    "first_half_gross": g[ds < 126].mean() if (ds < 126).any() else np.nan,
                                    "second_half_gross": g[ds >= 126].mean() if (ds >= 126).any() else np.nan,
                                    "positive_months_c1": int((monthly - 2 * pd.Series(1, index=monthly.index)
                                                               * pd.DataFrame({"month": pd.to_datetime(days[ds]).strftime("%Y-%m")}).groupby("month").size() > 0).sum()),
                                    "bps_day_ex_best5_c1": (daily.sum() - np.sort(daily)[-5:].sum()) / len(days),
                                    "top5_symbol_share": symbol_sum.nlargest(5).sum() / g.sum() if g.sum() > 0 else np.nan,
                                    **statistics(g, ds),
                                }
                                rows.append(row)
                                if (cell_a, cell_b, vol_floor, ranking, hold, tp, sl) == (7, 7, .8, "acceleration", 15, 40, 25):
                                    ledgers.append(pd.DataFrame({
                                        "trial": trial, "observation_id": ix[chosen],
                                        "session_date": pd.to_datetime(days[ds]).date,
                                        "security_id": securities[s[chosen]], "entry_minute": t[ix[chosen]] + 1,
                                        "exit_minute": release[chosen], "gross_bps": g,
                                    }))
                print("STATE", cell_a, cell_b, vol_floor, "trials", trial, flush=True)
    result = pd.DataFrame(rows)
    result.to_parquet(DEST / "grid.parquet", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_parquet(DEST / "baseline_trades.parquet", index=False)
    robust = result[(result.first_half_gross > 2) & (result.second_half_gross > 2)
                    & (result.positive_months_c1 >= 8) & (result.bps_day_ex_best5_c1 > 0)]
    robust.sort_values(["sharpe_c1", "return_c1"], ascending=False).to_csv(DEST / "robust.csv", index=False)
    (DEST / "scope.json").write_text(json.dumps({
        "candidate": "C0246", "side": "long", "cells": [6, 7, 8],
        "volatility_floors": [.7, .8, .9], "holds": [10, 15, 20, 30],
        "targets_bps": [20, 30, 40, 50, 60], "stops_bps": [15, 20, 25, 30, 40],
        "entry": "next-minute raw open", "exit": "first available minute open after trigger",
        "replication_accessed": False, "final_holdout_accessed": False,
    }, indent=2))
    print("GRID", len(result), "ROBUST", len(robust), flush=True)
    print(robust.sort_values(["sharpe_c1", "return_c1"], ascending=False).head(20).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
