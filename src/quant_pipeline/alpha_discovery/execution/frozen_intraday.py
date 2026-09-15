"""Small, fail-closed primitives for frozen timestamp-level strategy replays."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PassivePolicy:
    short_horizon_seconds: int = 120
    long_horizon_seconds: int = 1800
    quote_wait_ms: int = 1000


def select_independent_signals(signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply frozen overlap/conflict rules to timestamped signal opportunities.

    Signals at the same timestamp and symbol that disagree are all rejected when
    there is no pre-existing position.  This avoids introducing an arbitrary
    strategy priority after results are known.
    """
    required = {"strategy", "symbol", "signal_ts", "planned_exit_ts", "side"}
    missing = required - set(signals)
    if missing:
        raise ValueError(f"Missing signal columns: {sorted(missing)}")
    frame = signals.copy()
    frame["signal_ts"] = pd.to_datetime(frame.signal_ts, utc=True)
    frame["planned_exit_ts"] = pd.to_datetime(frame.planned_exit_ts, utc=True)
    frame["source_signal_row"] = np.arange(len(frame), dtype=np.int64)
    frame = frame.sort_values(
        ["signal_ts", "symbol", "strategy", "source_signal_row"], kind="stable"
    )
    active: dict[tuple[str, str], tuple[pd.Timestamp, int]] = {}
    accepted: list[dict] = []
    rejected: list[dict] = []

    for timestamp, timestamp_rows in frame.groupby("signal_ts", sort=False):
        expired = [key for key, (until, _) in active.items() if until <= timestamp]
        for key in expired:
            del active[key]
        for symbol, group in timestamp_rows.groupby("symbol", sort=False):
            existing = [(key, value) for key, value in active.items() if key[1] == symbol]
            existing_sides = {value[1] for _, value in existing}
            pending = group.copy()
            if existing_sides:
                allowed_side = next(iter(existing_sides))
                conflict = pending.side.astype(int).ne(allowed_side)
                for row in pending.loc[conflict].to_dict("records"):
                    row["rejection_reason"] = "conflicts_with_existing_position"
                    rejected.append(row)
                pending = pending.loc[~conflict]
            elif pending.side.astype(int).nunique() > 1:
                for row in pending.to_dict("records"):
                    row["rejection_reason"] = "simultaneous_unprioritized_conflict"
                    rejected.append(row)
                continue
            for row in pending.to_dict("records"):
                key = (str(row["strategy"]), str(symbol))
                if key in active:
                    row["rejection_reason"] = "same_strategy_symbol_already_open"
                    rejected.append(row)
                    continue
                active[key] = (pd.Timestamp(row["planned_exit_ts"]), int(row["side"]))
                accepted.append(row)
    return pd.DataFrame(accepted), pd.DataFrame(rejected)


def passive_fill_from_quotes(
    quotes: pd.DataFrame, side: int, arrival_ts: pd.Timestamp, deadline_ts: pd.Timestamp
) -> dict:
    """Fill at the arrival-side limit only after a strict NBBO move-through.

    A touch is deliberately insufficient.  A buy at the initial bid requires a
    later ask strictly below that bid; a short/sell at the initial ask requires
    a later bid strictly above that ask.
    """
    if side not in (-1, 1):
        raise ValueError("side must be -1 or 1")
    q = quotes.copy()
    q["quote_ts"] = pd.to_datetime(q.quote_ts, utc=True)
    q = q.loc[
        q.quote_ts.ge(pd.Timestamp(arrival_ts))
        & q.quote_ts.le(pd.Timestamp(deadline_ts))
        & q.bid_price.gt(0)
        & q.ask_price.ge(q.bid_price)
        & q.bid_size.gt(0)
        & q.ask_size.gt(0)
    ].sort_values("quote_ts")
    if q.empty:
        return {"status": "missing_arrival_quote"}
    arrival = q.iloc[0]
    limit = float(arrival.bid_price if side == 1 else arrival.ask_price)
    later = q.loc[q.quote_ts.gt(arrival.quote_ts)]
    crossed = later.ask_price.lt(limit) if side == 1 else later.bid_price.gt(limit)
    if not crossed.any():
        return {"status": "missed", "limit_price": limit}
    fill = later.loc[crossed].iloc[0]
    return {
        "status": "filled",
        "limit_price": limit,
        "price": limit,
        "fill_ts": fill.quote_ts,
        "time_to_fill_seconds": float((fill.quote_ts - arrival.quote_ts).total_seconds()),
    }


def return_from_prices(side: int, entry: float, exit_: float) -> float:
    if side not in (-1, 1) or min(entry, exit_) <= 0:
        raise ValueError("invalid side or price")
    return float(side * (exit_ / entry - 1.0))


def summarize_trades(trades: pd.DataFrame, cost_bps_per_side: float = 0.0) -> dict:
    """Summarize equal-notional additive trade returns."""
    if trades.empty:
        return {
            "trades": 0, "trades_per_day": 0.0, "gross_bp_per_trade": None,
            "net_bp_per_trade": None, "total_additive_pnl": 0.0,
            "win_rate": None, "max_drawdown": 0.0, "sharpe": None,
        }
    frame = trades.copy()
    frame["entry_ts"] = pd.to_datetime(frame.entry_ts, utc=True)
    cost = 2.0 * float(cost_bps_per_side) / 10_000.0
    frame["net_return"] = frame.gross_return.astype(float) - cost
    daily = frame.groupby(frame.entry_ts.dt.date).net_return.sum().sort_index()
    equity = 1.0 + daily.cumsum()
    drawdown = equity.cummax() - equity
    standard_deviation = float(daily.std(ddof=1))
    sharpe = None if not np.isfinite(standard_deviation) or standard_deviation == 0 else (
        float(np.sqrt(252.0) * daily.mean() / standard_deviation)
    )
    span_days = max(1, frame.entry_ts.dt.date.nunique())
    return {
        "trades": int(len(frame)),
        "trades_per_day": float(len(frame) / span_days),
        "gross_bp_per_trade": float(frame.gross_return.mean() * 10_000.0),
        "net_bp_per_trade": float(frame.net_return.mean() * 10_000.0),
        "total_additive_pnl": float(frame.net_return.sum()),
        "win_rate": float(frame.net_return.gt(0).mean()),
        "max_drawdown": float(drawdown.max()),
        "sharpe": sharpe,
    }
