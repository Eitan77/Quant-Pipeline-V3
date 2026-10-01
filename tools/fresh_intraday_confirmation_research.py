"""Fresh intraday confirmation and finite-slot research on governed evidence."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
from quant_pipeline.production.coverage import _members
from quant_pipeline.production.evidence_store import EvidenceReader


ROOT = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923")
OUT = ROOT / "research" / "fresh_strategy_competition_20260928" / "intraday_confirmation"
RESOLUTION = 5
TARGET = "target_240m__raw__intraday_5m"
PATH_TARGETS = [
    "target_30m__raw__intraday_5m",
    "target_60m__raw__intraday_5m",
    "target_120m__raw__intraday_5m",
    TARGET,
    "target_240m__benchmark_adjusted__intraday_5m",
    "target_240m__beta_residual__intraday_5m",
    "target_eod__raw__intraday_5m",
]
PAIR_CELLS = {
    "49ba1886c98f4effe309482b": 23,  # market beta
    "15256596b839908082ed3b76": 19,  # upside beta
    "abd45bb85b6c9691bbeb708a": 3,   # market lead response
    "766e09652b4e507efc92d167": 19,  # vol of vol
    "b5b151e4320e3a694cdcaec6": 16,  # recovery in downtrend
    "1266da721bfe4b0ac4ac6da6": 19,  # roll spread
    "a226d54970c18318a8e6d99d": 23,  # market correlation
    "58ca977e8dfb4d7e973cfac4": 23,  # downside return sum
}
PAIR_EDGE_BPS = {
    "49ba1886c98f4effe309482b": 23.04,
    "15256596b839908082ed3b76": 20.13,
    "abd45bb85b6c9691bbeb708a": 21.17,
    "766e09652b4e507efc92d167": 19.47,
    "b5b151e4320e3a694cdcaec6": 19.37,
    "1266da721bfe4b0ac4ac6da6": 21.26,
    "a226d54970c18318a8e6d99d": 18.59,
    "58ca977e8dfb4d7e973cfac4": 21.19,
}
BPS_LEVELS = (-1, 0, 1, 2, 3, 4, 5)


def scored_observations() -> pd.DataFrame:
    reader = EvidenceReader(ROOT, "evidence/reader.json", "intraday_5m")
    _, definitions = _members(ROOT, "intraday_5m", reader.grid, "dual")
    features = sorted({feature for pair in PAIR_CELLS for feature in definitions[pair]})
    feature_index = {feature: index for index, feature in enumerate(features)}
    observations = ROOT / reader.grid["observations"]
    frames = []
    offset = 0
    for batch in pq.ParquetFile(observations).iter_batches(
        batch_size=100_000,
        columns=["observation_id", "security_id", "session_date", "decision_ts"],
    ):
        stop = offset + batch.num_rows
        packed = reader.read_columns("bins", features, offset, stop)
        targets = reader.read_columns("targets", PATH_TARGETS, offset, stop)
        decoded = {
            feature: decode_packed_bins(packed[:, index], RESOLUTION)
            for feature, index in feature_index.items()
        }
        flags = []
        for pair, selected_cell in PAIR_CELLS.items():
            feature_a, feature_b = definitions[pair]
            a, b = decoded[feature_a], decoded[feature_b]
            flags.append((a >= 0) & (b >= 0) & (a * RESOLUTION + b == selected_cell))
        flag_matrix = np.column_stack(flags)
        score = flag_matrix.sum(axis=1)
        active = (score > 0) & np.isfinite(targets[:, PATH_TARGETS.index(TARGET)])
        if np.any(active):
            frame = batch.filter(pa.array(active)).to_pandas()
            frame["confirmation_score"] = score[active].astype(np.int8)
            weights = np.asarray([PAIR_EDGE_BPS[pair] for pair in PAIR_CELLS])
            frame["expected_edge_score"] = (flag_matrix[active] * weights).sum(axis=1)
            frame["reason_mask"] = sum(
                flag_matrix[active, index].astype(np.uint16) << index
                for index in range(len(PAIR_CELLS))
            )
            for index, target in enumerate(PATH_TARGETS):
                frame[target] = targets[active, index]
            frames.append(frame)
        offset = stop
    if offset != reader.rows:
        raise RuntimeError("Observation stream length disagrees with evidence reader")
    return pd.concat(frames, ignore_index=True)


def attach_execution(frame: pd.DataFrame) -> pd.DataFrame:
    ledger = ROOT / "cache" / "targets" / "intraday_5m.parquet"
    with duckdb.connect() as con:
        con.register("signals", frame)
        result = con.execute(
            """SELECT s.*,t.entry_ts,t.entry_price,t.exit_ts,t.exit_price
            FROM signals s JOIN read_parquet(?) t
              ON s.observation_id=t.observation_id AND t.target_id=?""",
            [str(ledger), TARGET],
        ).fetchdf()
        symbols = con.execute(
            "SELECT security_id,first(symbol) symbol FROM read_parquet(?) GROUP BY 1",
            [str(Path.cwd() / "reference" / "security_master.parquet")],
        ).fetchdf()
    return result.merge(symbols, on="security_id", how="left", validate="many_to_one")


def independent_starts(frame: pd.DataFrame, threshold: int) -> pd.DataFrame:
    selected = frame[frame.confirmation_score >= threshold].copy()
    selected = selected.sort_values(["security_id", "session_date", "decision_ts"])
    prior = selected.groupby(["security_id", "session_date"], sort=False).decision_ts.shift()
    starts = selected.loc[prior.isna() | ((selected.decision_ts - prior) != pd.Timedelta(minutes=5))]
    starts = starts.sort_values(["decision_ts", "expected_edge_score", "security_id"], ascending=[True, False, True])
    keep = []
    next_allowed = {}
    for row in starts.itertuples():
        allowed = next_allowed.get(row.security_id)
        accepted = allowed is None or row.decision_ts >= allowed
        keep.append(accepted)
        if accepted:
            next_allowed[row.security_id] = row.exit_ts
    return starts.loc[keep].copy()


def finite_slots(starts: pd.DataFrame, slots: int) -> pd.DataFrame:
    accepted = []
    active_exits = []
    for timestamp, group in starts.groupby("decision_ts", sort=True):
        active_exits = [value for value in active_exits if value > timestamp]
        available = slots - len(active_exits)
        if available <= 0:
            continue
        ranked = group.sort_values(
            ["confirmation_score", "expected_edge_score", "security_id"],
            ascending=[False, False, True],
            kind="stable",
        ).head(available)
        accepted.extend(ranked.index.tolist())
        active_exits.extend(ranked.exit_ts.tolist())
    return starts.loc[accepted].sort_values(["decision_ts", "security_id"]).copy()


def finite_slots_random_ties(starts: pd.DataFrame, slots: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    work = starts.copy()
    work["tie_break"] = rng.random(len(work))
    accepted = []
    active_exits = []
    for timestamp, group in work.groupby("decision_ts", sort=True):
        active_exits = [value for value in active_exits if value > timestamp]
        available = slots - len(active_exits)
        if available <= 0:
            continue
        ranked = group.sort_values(
            ["confirmation_score", "expected_edge_score", "tie_break"],
            ascending=[False, False, True], kind="stable",
        ).head(available)
        accepted.extend(ranked.index.tolist())
        active_exits.extend(ranked.exit_ts.tolist())
    return work.loc[accepted].drop(columns="tie_break").sort_values(
        ["decision_ts", "security_id"]
    ).copy()


def summarize(trades: pd.DataFrame, threshold: int, slots: int, bps: int) -> dict:
    entry = trades.entry_price.to_numpy(float) * (1 - bps / 10000)
    exit_price = trades.exit_price.to_numpy(float) * (1 + bps / 10000)
    returns = entry / exit_price - 1
    work = trades[["session_date", "symbol"]].copy()
    work["return"] = returns
    daily = work.groupby("session_date")["return"].mean().sort_index()
    cumulative = daily.cumsum()
    drawdown = cumulative - cumulative.cummax()
    monthly = daily.groupby(pd.to_datetime(daily.index).strftime("%Y-%m")).sum()
    symbol_sum = work.groupby("symbol")["return"].sum().sort_values(ascending=False)
    return {
        "threshold": threshold,
        "slots": slots,
        "bps": bps,
        "trades": len(trades),
        "sessions": int(work.session_date.nunique()),
        "mean_trade_bps": float(returns.mean() * 10000) if len(returns) else np.nan,
        "median_trade_bps": float(np.median(returns) * 10000) if len(returns) else np.nan,
        "win_rate": float(np.mean(returns > 0)) if len(returns) else np.nan,
        "total_trade_return": float(returns.sum()),
        "equal_weight_daily_total": float(daily.sum()),
        "max_additive_drawdown": float(drawdown.min()) if len(drawdown) else np.nan,
        "positive_months": int((monthly > 0).sum()),
        "observed_months": len(monthly),
        "top5_contribution_share": float(symbol_sum.head(5).sum() / symbol_sum.sum())
        if symbol_sum.sum() > 0 else np.nan,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    observations = attach_execution(scored_observations())
    observations.to_parquet(OUT / "scored_observations.parquet", index=False)
    path_rows = []
    portfolio_rows = []
    ledgers = []
    for threshold in range(1, len(PAIR_CELLS) + 1):
        starts = independent_starts(observations, threshold)
        if starts.empty:
            continue
        for target in PATH_TARGETS:
            values = starts[target].dropna().to_numpy(float)
            path_rows.append(
                {
                    "threshold": threshold,
                    "target_id": target,
                    "n": len(values),
                    "short_edge_bps": float(-values.mean() * 10000) if len(values) else np.nan,
                }
            )
        for slots in (1, 3, 5, 10):
            trades = finite_slots(starts, slots)
            tagged = trades.copy()
            tagged["threshold"] = threshold
            tagged["slots"] = slots
            ledgers.append(tagged)
            for bps in BPS_LEVELS:
                portfolio_rows.append(summarize(trades, threshold, slots, bps))
    pd.DataFrame(path_rows).to_parquet(OUT / "horizon_summary.parquet", index=False)
    summary = pd.DataFrame(portfolio_rows)
    summary.to_parquet(OUT / "portfolio_summary.parquet", index=False)
    pd.concat(ledgers, ignore_index=True).to_parquet(OUT / "trade_ledgers.parquet", index=False)
    tie_rows = []
    for threshold, slots in ((5, 5), (6, 10)):
        starts = independent_starts(observations, threshold)
        for seed in range(20):
            row = summarize(finite_slots_random_ties(starts, slots, seed), threshold, slots, 5)
            row["seed"] = seed
            tie_rows.append(row)
    pd.DataFrame(tie_rows).to_parquet(OUT / "random_tie_sensitivity.parquet", index=False)
    print(
        summary[summary.bps.isin([0, 5])].sort_values(
            ["bps", "equal_weight_daily_total"], ascending=[True, False]
        ).to_string(index=False),
        flush=True,
    )
    print("HORIZONS", flush=True)
    print(pd.DataFrame(path_rows).to_string(index=False), flush=True)
    manifest = {
        "status": "complete",
        "pair_cells": PAIR_CELLS,
        "scored_observations": len(observations),
        "portfolio_rows": len(summary),
        "sealed_periods_accessed": False,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"OUTPUT {OUT}", flush=True)


if __name__ == "__main__":
    main()
