"""Execution primitives for frozen candidate replays.

The functions in this module operate on explicit price legs.  In particular,
short and hedged returns are reconstructed from entry/exit cash flows rather
than by treating a stored forward or residual return as executable P&L.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExecutionAssumptions:
    cost_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 2.0
    additional_entry_delay_minutes: int = 1


def decode_packed_bins(values: np.ndarray, resolution: int) -> np.ndarray:
    """Decode the governed lossless 3/5/10-bin byte representation."""
    packed = np.asarray(values, dtype=np.uint8)
    if resolution == 3:
        decoded = packed % 3
    elif resolution == 5:
        decoded = (packed // 3) % 5
    elif resolution == 10:
        decoded = packed // 15
    else:
        raise ValueError(f"Unsupported resolution: {resolution}")
    output = decoded.astype(np.int16, copy=False)
    output[packed == 255] = -1
    return output


def explicit_leg_return(side: int, entry_price: float, exit_price: float,
                        *, notional: float = 1.0) -> float:
    """Return of an explicit long or short price leg on normalized notional."""
    if side not in (-1, 1):
        raise ValueError("side must be -1 or 1")
    if notional < 0 or not np.isfinite([entry_price, exit_price, notional]).all():
        raise ValueError("invalid leg inputs")
    if min(entry_price, exit_price) <= 0:
        raise ValueError("prices must be positive")
    if side == 1:
        return float(notional * (exit_price - entry_price) / entry_price)
    proceeds = notional * entry_price / entry_price
    cover = notional * exit_price / entry_price
    return float(proceeds - cover)


def executed_leg_components(side: int, entry_price: float, exit_price: float,
                            *, notional: float = 1.0, cost_bps_per_side: float = 5.0,
                            slippage_bps_per_side: float = 2.0) -> dict[str, float]:
    """Gross, adverse-slippage and commission components for one price leg."""
    if cost_bps_per_side < 0 or slippage_bps_per_side < 0:
        raise ValueError("friction must be nonnegative")
    gross = explicit_leg_return(side, entry_price, exit_price, notional=notional)
    slip = slippage_bps_per_side / 10_000.0
    fee = cost_bps_per_side / 10_000.0
    if side == 1:
        executed_entry = entry_price * (1.0 + slip)
        executed_exit = exit_price * (1.0 - slip)
        slippage_only = notional * (executed_exit - executed_entry) / entry_price
    else:
        executed_entry = entry_price * (1.0 - slip)
        executed_exit = exit_price * (1.0 + slip)
        slippage_only = notional * (executed_entry - executed_exit) / entry_price
    commission = notional * fee * (executed_entry + executed_exit) / entry_price
    return {
        "gross_return": float(gross),
        "executed_entry_price": float(executed_entry),
        "executed_exit_price": float(executed_exit),
        "slippage_return_cost": float(gross - slippage_only),
        "commission_return_cost": float(commission),
        "net_return": float(slippage_only - commission),
    }


def first_executable_entry(price_bars: pd.DataFrame, security_id: str,
                           governed_entry_ts: pd.Timestamp, exit_ts: pd.Timestamp,
                           additional_delay_minutes: int) -> tuple[pd.Timestamp, float] | None:
    """Find the first positive raw open at/after governed entry plus delay."""
    if additional_delay_minutes < 0:
        raise ValueError("delay must be nonnegative")
    bars = price_bars.get(str(security_id))
    if bars is None or bars.empty:
        return None
    threshold = pd.Timestamp(governed_entry_ts) + pd.Timedelta(minutes=additional_delay_minutes)
    exit_time = pd.Timestamp(exit_ts)
    timestamps = bars.index
    location = int(timestamps.searchsorted(threshold, side="left"))
    while location < len(bars):
        timestamp = timestamps[location]
        if timestamp >= exit_time:
            return None
        price = float(bars.iloc[location])
        if np.isfinite(price) and price > 0:
            return timestamp, price
        location += 1
    return None


def _leg(prefix: str, side: int, entry: float, exit_: float, notional: float,
         assumptions: ExecutionAssumptions) -> dict[str, float]:
    values = executed_leg_components(
        side, entry, exit_, notional=notional,
        cost_bps_per_side=assumptions.cost_bps_per_side,
        slippage_bps_per_side=assumptions.slippage_bps_per_side,
    )
    return {f"{prefix}_{key}": value for key, value in values.items()}


def replay_candidate_signals(signals: pd.DataFrame, price_bars: dict[str, pd.Series],
                             assumptions: ExecutionAssumptions,
                             *, benchmark_security_id: str | None = None,
                             retain_rejections: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay one frozen candidate with one open position per security.

    Required signal columns are explicit and auditable.  ``return_basis`` may
    be raw, benchmark_adjusted, or beta_residual.  Hedge legs use the same
    signal sign with opposite benchmark exposure; beta residual exposure uses
    the causal ``beta_prior`` stored with the target.
    """
    required = {
        "candidate_key", "observation_id", "security_id", "symbol", "decision_ts",
        "governed_entry_ts", "governed_entry_price", "exit_ts", "exit_price",
        "local_direction", "return_basis", "benchmark_entry_ts",
        "benchmark_entry_price", "benchmark_exit_ts", "benchmark_exit_price", "beta_prior",
    }
    missing = required - set(signals)
    if missing:
        raise ValueError(f"Missing replay columns: {sorted(missing)}")
    frame = signals.copy()
    for column in ("decision_ts", "governed_entry_ts", "exit_ts", "benchmark_entry_ts", "benchmark_exit_ts"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    frame["source_signal_row"] = np.arange(len(frame), dtype=np.int64)
    frame = frame.sort_values(["decision_ts", "security_id", "observation_id"], kind="stable")
    active_until: dict[str, pd.Timestamp] = {}
    trades: list[dict] = []
    rejected: list[dict] = []

    for row in frame.itertuples(index=False):
        reason = None
        if pd.isna(row.exit_ts) or not np.isfinite(row.exit_price) or row.exit_price <= 0:
            reason = "missing_or_invalid_target_window"
        elif pd.isna(row.governed_entry_ts) or not np.isfinite(row.governed_entry_price) or row.governed_entry_price <= 0:
            reason = "missing_or_invalid_governed_entry"
        elif row.local_direction not in (-1, 1):
            reason = "invalid_local_direction"
        elif row.security_id in active_until and row.decision_ts < active_until[row.security_id]:
            reason = "overlap_existing_position"

        stock_entry = None if reason else first_executable_entry(
            price_bars, row.security_id, row.governed_entry_ts, row.exit_ts,
            assumptions.additional_entry_delay_minutes,
        )
        if reason is None and stock_entry is None:
            reason = "delayed_entry_at_or_after_exit_or_missing"

        basis = str(row.return_basis)
        hedge_ratio = 0.0
        if basis == "benchmark_adjusted":
            hedge_ratio = 1.0
        elif basis == "beta_residual":
            if not np.isfinite(row.beta_prior):
                reason = reason or "missing_causal_beta"
            else:
                hedge_ratio = float(row.beta_prior)
        elif basis != "raw":
            reason = reason or "unsupported_return_basis"

        benchmark_entry = None
        if reason is None and hedge_ratio != 0:
            if benchmark_security_id is None or pd.isna(row.benchmark_exit_ts) or not np.isfinite(row.benchmark_exit_price):
                reason = "missing_benchmark_window"
            else:
                benchmark_entry = first_executable_entry(
                    price_bars, benchmark_security_id, row.benchmark_entry_ts,
                    row.benchmark_exit_ts, assumptions.additional_entry_delay_minutes,
                )
                if benchmark_entry is None:
                    reason = "missing_delayed_benchmark_entry"

        if reason is not None:
            if retain_rejections:
                rejected.append({
                    "candidate_key": row.candidate_key,
                    "source_signal_row": row.source_signal_row,
                    "observation_id": row.observation_id,
                    "security_id": row.security_id,
                    "symbol": row.symbol,
                    "signal_ts": row.decision_ts,
                    "planned_exit_ts": row.exit_ts,
                    "additional_entry_delay_minutes": assumptions.additional_entry_delay_minutes,
                    "rejection_reason": reason,
                })
            continue

        entry_ts, entry_price = stock_entry
        direct = _leg("direct", int(row.local_direction), entry_price, float(row.exit_price), 1.0, assumptions)
        hedge: dict[str, float] = {
            "hedge_gross_return": 0.0, "hedge_slippage_return_cost": 0.0,
            "hedge_commission_return_cost": 0.0, "hedge_net_return": 0.0,
            "hedge_executed_entry_price": np.nan, "hedge_executed_exit_price": np.nan,
        }
        benchmark_entry_ts = pd.NaT
        benchmark_entry_price = np.nan
        benchmark_side = 0
        if hedge_ratio != 0:
            benchmark_entry_ts, benchmark_entry_price = benchmark_entry
            signed_exposure = -int(row.local_direction) * hedge_ratio
            benchmark_side = 1 if signed_exposure > 0 else -1
            hedge = _leg(
                "hedge", benchmark_side, float(benchmark_entry_price),
                float(row.benchmark_exit_price), abs(hedge_ratio), assumptions,
            )
        gross = direct["direct_gross_return"] + hedge["hedge_gross_return"]
        net = direct["direct_net_return"] + hedge["hedge_net_return"]
        trades.append({
            "candidate_key": row.candidate_key,
            "source_signal_row": row.source_signal_row,
            "observation_id": row.observation_id,
            "security_id": row.security_id,
            "symbol": row.symbol,
            "signal_ts": row.decision_ts,
            "governed_entry_ts": row.governed_entry_ts,
            "governed_entry_price": row.governed_entry_price,
            "entry_ts": entry_ts,
            "entry_price": entry_price,
            "exit_ts": row.exit_ts,
            "exit_price": row.exit_price,
            "side": "LONG" if row.local_direction == 1 else "SHORT",
            "side_value": int(row.local_direction),
            "return_basis": basis,
            "beta_prior": float(row.beta_prior) if np.isfinite(row.beta_prior) else np.nan,
            "benchmark_security_id": benchmark_security_id if hedge_ratio != 0 else None,
            "benchmark_side": benchmark_side,
            "benchmark_notional_ratio": abs(hedge_ratio),
            "benchmark_entry_ts": benchmark_entry_ts,
            "benchmark_entry_price": benchmark_entry_price,
            "benchmark_exit_ts": row.benchmark_exit_ts if hedge_ratio != 0 else pd.NaT,
            "benchmark_exit_price": row.benchmark_exit_price if hedge_ratio != 0 else np.nan,
            **direct, **hedge,
            "gross_trade_return": gross,
            "costs_slippage_return": gross - net,
            "net_trade_return": net,
            "cost_bps_per_side": assumptions.cost_bps_per_side,
            "slippage_bps_per_side": assumptions.slippage_bps_per_side,
            "additional_entry_delay_minutes": assumptions.additional_entry_delay_minutes,
        })
        active_until[row.security_id] = row.exit_ts

    return pd.DataFrame(trades), pd.DataFrame(rejected)


def friction_net_return(trades: pd.DataFrame, bps_per_side: float) -> np.ndarray:
    """Apply total per-side friction to every explicit stock and hedge leg."""
    if bps_per_side < 0:
        raise ValueError("friction must be nonnegative")
    if trades.empty:
        return np.empty(0, dtype=float)
    rate = bps_per_side / 10_000.0
    direct_turnover = 1.0 + trades.exit_price.to_numpy(float) / trades.entry_price.to_numpy(float)
    hedge_turnover = np.zeros(len(trades), dtype=float)
    active = trades.benchmark_notional_ratio.to_numpy(float) > 0
    hedge_turnover[active] = trades.loc[active, "benchmark_notional_ratio"].to_numpy(float) * (
        1.0 + trades.loc[active, "benchmark_exit_price"].to_numpy(float)
        / trades.loc[active, "benchmark_entry_price"].to_numpy(float)
    )
    return trades.gross_trade_return.to_numpy(float) - rate * (direct_turnover + hedge_turnover)


def aggregate_returns(trades: pd.DataFrame, return_column: str) -> dict[str, float]:
    values = trades[return_column].to_numpy(float) if len(trades) else np.empty(0)
    if not len(values):
        return {"return": 0.0, "average_trade": np.nan, "median_trade": np.nan,
                "win_rate": np.nan, "max_drawdown": 0.0}
    events = trades.assign(_value=values).groupby("exit_ts", sort=True)._value.sum()
    equity = 1.0 + events.cumsum()
    peak = equity.cummax().clip(lower=1.0)
    drawdown = equity / peak - 1.0
    return {
        "return": float(np.sum(values)),
        "average_trade": float(np.mean(values)),
        "median_trade": float(np.median(values)),
        "win_rate": float(np.mean(values > 0)),
        "max_drawdown": float(-drawdown.min()),
    }
