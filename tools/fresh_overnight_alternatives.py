"""Compare structurally distinct overnight candidates with finite-slot sensitivity."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_pipeline.production.replay import prepare_replay_inputs


ROOT = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923")
OUT = ROOT / "research" / "fresh_strategy_competition_20260928" / "overnight_alternatives"
TARGET = "target_overnight__raw__preclose_1555"
CANDIDATES = {
    "current": ("e669d83e43b3cea8b148779a", [80, 90]),
    "downvol_posjump": ("306b333fd69bc576376df568", [44]),
    "jump_marketvolpct": ("105c166e4ee662ea80b537d1", [34]),
    "riskmom_posjump": ("e5edd51c1a185eb42f8f6f34", [54]),
    "marketvolpct_posjump": ("e94abbeadf5fd9b35ab82244", [44]),
    "jumpvar_marketvol": ("663b3e2857ce5af8c9fa8307", [34]),
    "signagree_posjump": ("252544f9a28669a0b7327353", [64]),
    "negjump_lowreclaim": ("4139def8e4c32e23b80a916b", [44]),
    "weekday_jumpvar": ("0705f2abc25315fa59e00280", [53]),
    "beta_lowreclaim": ("2f6dbffec2b967466891b086", [94]),
    "breakdown_beta": ("3152d9c8623108d04a934d6a", [59]),
    "posjump_ownvol": ("f1c481781767db523a647f77", [43]),
    "posjump_recovery": ("2e3fe8adfbf69bc8d7ddb6b5", [44]),
    "breakdown_negjump": ("f95ed8ac3d41bcead5cf2bab", [54]),
    "longdown_signagree": ("847fa45c05ab94b60e710d45", [26]),
    "breakout_posjump": ("129c5f41a4b30c10b3001147", [34]),
    "atr_downbeta": ("9ba5e17ef3b4cdb0c6f89b54", [99]),
    "since_low_failedbreak": ("eccf609cc96db08a9db7feed", [22]),
    "downbeta_volvol": ("b9cbc30e772291161eee2044", [99]),
    "failedbreak_range": ("dc8674a49002338ee6b8692a", [22]),
    "newlow_volume": ("3333880f08678123a16a7c98", [9]),
    "openinggap_upvolaccel": ("d1282c8c244a0e50e04fb479", [99]),
    "rawvol_vwap": ("03be47a8a50ce5f9f4aa3fd4", [90]),
    "failedbreakout_gap": ("20a5f5c812df33fe4a0078cb", [19]),
    "wick_newhigh": ("7de0afb09136cdb5468f2d3e", [38]),
    "closingret_varratio": ("dd1c2645f02005a31427763c", [10]),
}


def stats(frame: pd.DataFrame, name: str) -> tuple[dict, pd.Series]:
    work = frame.copy()
    work["return_5bps"] = (
        work.exit_price.to_numpy(float) * 0.9995
        / (work.governed_entry_price.to_numpy(float) * 1.0005)
        - 1
    )
    daily = work.groupby("session_date").return_5bps.mean().sort_index()
    cumulative = daily.cumsum()
    drawdown = cumulative - cumulative.cummax()
    monthly = daily.groupby(pd.to_datetime(daily.index).strftime("%Y-%m")).sum()
    symbol_sum = work.groupby("symbol").return_5bps.sum().sort_values(ascending=False)
    late = work[work.session_date.astype(str) >= "2025-11-01"]
    ex_top5 = work[~work.symbol.isin(symbol_sum.head(5).index)]
    rng_rows = []
    for seed in range(100):
        randomized = work.assign(tie_break=np.random.default_rng(seed).random(len(work)))
        chosen = randomized.sort_values(["session_date", "tie_break"]).groupby(
            "session_date", group_keys=False
        ).head(5)
        rng_rows.append(chosen.groupby("session_date").return_5bps.mean().sum())
    return {
        "candidate": name,
        "pair_id": CANDIDATES[name][0],
        "cells": json.dumps(CANDIDATES[name][1]),
        "trades": len(work),
        "sessions": int(work.session_date.nunique()),
        "trades_per_all_251_sessions": len(work) / 251,
        "mean_trade_bps_5": work.return_5bps.mean() * 10000,
        "win_rate_5": (work.return_5bps > 0).mean(),
        "additive_return_5": daily.sum(),
        "compounded_return_5": (1 + daily).prod() - 1,
        "max_additive_drawdown_5": drawdown.min(),
        "positive_months_5": int((monthly > 0).sum()),
        "late_trades": len(late),
        "late_mean_bps_5": late.return_5bps.mean() * 10000,
        "top5_contribution_share": symbol_sum.head(5).sum() / symbol_sum.sum(),
        "ex_top5_trades": len(ex_top5),
        "ex_top5_mean_bps_5": ex_top5.return_5bps.mean() * 10000,
        "random_5slot_p05": np.quantile(rng_rows, 0.05),
        "random_5slot_median": np.median(rng_rows),
        "random_5slot_p95": np.quantile(rng_rows, 0.95),
    }, daily.rename(name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    reader = json.loads((ROOT / "evidence" / "reader.json").read_text(encoding="utf-8"))
    rows, dailies, ledgers = [], [], []
    for name, (pair_id, cells) in CANDIDATES.items():
        spec = {"grid": "preclose_1555", "state_kind": "dual", "pair_id": pair_id,
                "target_id": TARGET, "resolution": 10, "cells": cells,
                "direction": 1, "return_basis": "raw"}
        signals, preparation = prepare_replay_inputs(ROOT, reader, spec)
        if preparation["status"] != "complete":
            raise RuntimeError(f"{name}: {preparation}")
        signals = signals.dropna(subset=["governed_entry_price", "exit_price"]).copy()
        signals["candidate"] = name
        row, daily = stats(signals, name)
        rows.append(row)
        dailies.append(daily)
        ledgers.append(signals)
        print(f"{name}: {len(signals)} trades", flush=True)
    summary = pd.DataFrame(rows)
    daily_frame = pd.concat(dailies, axis=1)
    benchmark = daily_frame["current"]
    summary["daily_corr_with_current"] = [
        daily_frame[name].corr(benchmark) for name in summary.candidate
    ]
    summary.to_parquet(OUT / "summary.parquet", index=False)
    daily_frame.to_parquet(OUT / "daily_returns.parquet")
    pd.concat(ledgers, ignore_index=True).to_parquet(OUT / "signal_ledgers.parquet", index=False)
    (OUT / "manifest.json").write_text(json.dumps({"status": "complete", "sealed_periods_accessed": False,
                                                    "candidates": CANDIDATES}, indent=2), encoding="utf-8")
    print(summary.sort_values("additive_return_5", ascending=False).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
