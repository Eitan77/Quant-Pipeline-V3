"""Chronological bar exit grid for the quote-positive rule115 entry schedule."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from intraday_strategy_search import OUT


DEST = OUT / "rule115_exit_grid"
DEST.mkdir(exist_ok=True)
TARGETS = [0, 20, 40, 60, 80, 120, 160, 240]
STOPS = [0, 20, 40, 60, 80, 120, 160]
HOLDS = [30, 60, 90, 120, 180, 240]


def segment_metrics(gross: np.ndarray, dates: pd.DatetimeIndex, prefix: str) -> dict:
    net = gross - 2  # fixed 1 bp/side development screen
    ret = net / 10000
    equity = np.cumprod(1 + ret)
    peak = np.maximum.accumulate(np.r_[1, equity])[1:]
    monthly = pd.DataFrame({"month": dates.strftime("%Y-%m"), "ret": ret}).groupby("month").ret.sum()
    return {
        f"{prefix}_trades": len(gross), f"{prefix}_gross_bps": gross.mean(),
        f"{prefix}_return_c1": equity[-1] - 1,
        f"{prefix}_max_dd_c1": (1 - equity / peak).max(),
        f"{prefix}_positive_months_c1": int((monthly > 0).sum()),
        f"{prefix}_months": len(monthly),
    }


def main() -> None:
    ledger = pd.read_parquet(OUT / "breadth_extension" / "leader_trades.parquet")
    ledger = ledger[(ledger.rule_id == 115) & (ledger.slots == 1)].sort_values("day").reset_index(drop=True)
    if len(ledger) != 248:
        raise RuntimeError(f"Expected 248 rule115 trades, found {len(ledger)}")
    axes = json.loads((OUT / "price_axes.json").read_text())
    days = pd.to_datetime(axes["days"])
    open_minutes = np.asarray(axes["open_minutes"])
    prices = np.load(OUT / "opens.npy", mmap_mode="r")
    d = ledger.day.to_numpy(np.int64); s = ledger.security_code.to_numpy(np.int64)
    entry_offset = ledger.entry_minute.to_numpy(np.int64) - open_minutes[d]
    entry = prices[d, s, entry_offset]
    offsets = np.arange(243)
    path = prices[d[:, None], s[:, None], np.minimum(entry_offset[:, None] + offsets, 389)]
    returns = (path / entry[:, None] - 1) * 10000
    next_valid = np.where(np.isfinite(path), offsets[None, :], 999)
    next_valid = np.minimum.accumulate(next_valid[:, ::-1], axis=1)[:, ::-1]
    rows, ledgers = [], []
    trial = 0
    for hold in HOLDS:
        for tp in TARGETS:
            take = returns >= tp if tp else np.zeros_like(returns, dtype=bool)
            take[:, 0] = False
            take_at = np.where(take.any(1), take.argmax(1) + 1, 999)
            for sl in STOPS:
                stop = returns <= -sl if sl else np.zeros_like(returns, dtype=bool)
                stop[:, 0] = False
                stop_at = np.where(stop.any(1), stop.argmax(1) + 1, 999)
                scheduled = np.minimum(np.minimum(take_at, stop_at), hold)
                actual = next_valid[np.arange(len(ledger)), scheduled]
                if (actual >= 999).any():
                    continue
                exit_price = path[np.arange(len(ledger)), actual]
                gross = (exit_price / entry - 1) * 10000
                early = d < 126
                trial += 1
                row = {"trial": trial, "hold": hold, "tp_bps": tp, "sl_bps": sl,
                       "gross_bps": gross.mean(), "median_exit_minutes": np.median(actual)}
                row.update(segment_metrics(gross[early], days[d[early]], "development"))
                row.update(segment_metrics(gross[~early], days[d[~early]], "validation"))
                rows.append(row)
                ledgers.append(pd.DataFrame({
                    "trial": trial, "session_date": days[d], "security_code": s,
                    "entry_minute": ledger.entry_minute, "exit_minute": ledger.entry_minute + actual,
                    "gross_bps": gross,
                }))
    result = pd.DataFrame(rows)
    result.to_parquet(DEST / "grid.parquet", index=False)
    pd.concat(ledgers, ignore_index=True).to_parquet(DEST / "trade_ledgers.parquet", index=False)
    robust = result[(result.development_positive_months_c1 >= 4)
                    & (result.development_gross_bps > 2)
                    & (result.development_max_dd_c1 < .20)]
    robust.sort_values("development_return_c1", ascending=False).to_csv(DEST / "development_survivors.csv", index=False)
    (DEST / "scope.json").write_text(json.dumps({
        "entry_rule": "breadth rule115 frozen one-slot schedule", "selection_segment": "days 0-125",
        "validation_segment": "days 126-250", "targets_bps": TARGETS, "stops_bps": STOPS,
        "holds_minutes": HOLDS, "cost_bps_per_side": 1,
        "execution": "next available minute open after target/stop observation",
        "replication_accessed": False, "final_holdout_accessed": False,
    }, indent=2))
    print("GRID", len(result), "SURVIVORS", len(robust), flush=True)
    print(robust.sort_values("development_return_c1", ascending=False).head(30).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
