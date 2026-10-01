"""Neighbor audit for the all-day breakdown/acceleration short exit."""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

from intraday_entry_search import allocate
from intraday_exit_search import statistics
from intraday_strategy_search import OUT, obs_arrays


DEST = OUT / "breakdown_exit_audit"
DEST.mkdir(exist_ok=True)


def main() -> None:
    _, t, day, days, sec, securities, closes = obs_arrays()
    axes = json.loads((OUT / "price_axes.json").read_text())
    opens = np.asarray(axes["open_minutes"])
    minute = t - opens[day]
    ranks = np.load(OUT / "fine_ranks.npy", mmap_mode="r")
    prices = np.load(OUT / "opens.npy", mmap_mode="r")
    ix = np.flatnonzero((ranks[:, 3] < .05) & (ranks[:, 4] >= .9)
                        & (minute >= 5) & (t + 242 <= closes[day] - 5))
    d, s, m = day[ix], sec[ix], minute[ix] + 1
    entry = prices[d, s, m]
    good = np.isfinite(entry)
    ix, d, s, m, entry = ix[good], d[good], s[good], m[good], entry[good]
    offsets = np.arange(243)
    path = prices[d[:, None], s[:, None], np.minimum(m[:, None] + offsets, 389)]
    returns = -(path / entry[:, None] - 1) * 10000
    next_valid = np.where(np.isfinite(path), offsets[None, :], 999)
    next_valid = np.minimum.accumulate(next_valid[:, ::-1], axis=1)[:, ::-1]
    priority = np.nan_to_num(ranks[ix, 4], nan=-1)
    rows, frozen = [], []
    trial = 0
    for hold in [180, 210, 240]:
        for target in [50, 60, 70, 80, 90, 100, 120]:
            hit = returns >= target; hit[:, 0] = False
            hit_at = np.where(hit.any(1), hit.argmax(1) + 1, 999)
            for stop_bps in [0, 160, 200]:
                if stop_bps:
                    stop = returns <= -stop_bps; stop[:, 0] = False
                    stop_at = np.where(stop.any(1), stop.argmax(1) + 1, 999)
                else:
                    stop_at = np.full(len(ix), 999)
                scheduled = np.minimum(np.minimum(hit_at, stop_at), hold)
                actual = next_valid[np.arange(len(ix)), scheduled]
                valid = actual < 999
                exit_price = path[np.arange(len(ix)), np.minimum(actual, 242)]
                pnl = -(exit_price / entry - 1) * 10000
                release = t[ix] + 1 + np.where(valid, actual, hold)
                chosen, _ = allocate(t[ix] + 1, release, s, valid, 1, priority=priority)
                if len(chosen) < 100 or (~valid[chosen]).any():
                    continue
                trial += 1
                g, ds = pnl[chosen], d[chosen]
                monthly = pd.DataFrame({"month": pd.to_datetime(days[ds]).strftime("%Y-%m"),
                                        "net": g - 2}).groupby("month").net.sum()
                row = {"trial": trial, "hold": hold, "target_bps": target,
                       "stop_bps": stop_bps, "trades": len(chosen),
                       "gross_bps": g.mean(), "first_half_gross": g[ds < 126].mean(),
                       "second_half_gross": g[ds >= 126].mean(),
                       "positive_months_c1": int((monthly > 0).sum()), **statistics(g, ds)}
                rows.append(row)
                if (hold, target, stop_bps) == (240, 80, 0):
                    frozen.append(pd.DataFrame({
                        "trial": trial, "session_date": pd.to_datetime(days[ds]).date,
                        "security_id": securities[s[chosen]], "entry_minute": t[ix[chosen]] + 1,
                        "exit_minute": release[chosen], "gross_bps": g,
                    }))
    result = pd.DataFrame(rows)
    result.to_csv(DEST / "grid.csv", index=False)
    if frozen:
        pd.concat(frozen, ignore_index=True).to_parquet(DEST / "frozen_trades.parquet", index=False)
    (DEST / "scope.json").write_text(json.dumps({
        "rule": "short breakdown_distance rank<5%, acceleration_halves rank>=90%",
        "frozen_exit": {"hold": 240, "target_bps": 80, "stop_bps": 0},
        "replication_accessed": False, "final_holdout_accessed": False,
    }, indent=2))
    print(result.sort_values("return_c1", ascending=False).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
