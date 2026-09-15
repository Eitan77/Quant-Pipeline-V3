from __future__ import annotations

import numpy as np
import pandas as pd


def aggregate_bars(bars: pd.DataFrame, minutes: int | None) -> pd.DataFrame:
    """Aggregate canonical 1m rows inside each exchange session without overnight flooring."""
    required = {"security_id", "symbol", "session_date", "bar_start_ts_utc", "bar_end_ts_utc", "open", "high", "low", "close", "volume"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"Bars missing aggregation columns: {sorted(missing)}")
    frame = bars.copy()
    frame["bar_start_ts_utc"] = pd.to_datetime(frame.bar_start_ts_utc, utc=True)
    frame["bar_end_ts_utc"] = pd.to_datetime(frame.bar_end_ts_utc, utc=True)
    frame = frame.sort_values(["security_id", "session_date", "bar_start_ts_utc"], kind="mergesort")
    session_group = frame.groupby(["security_id", "session_date"], sort=False, observed=True)
    frame["_ordinal"] = session_group.cumcount()
    frame["_bucket"] = 0 if minutes is None else frame._ordinal // int(minutes)
    keys = ["security_id", "symbol", "session_date", "_bucket"]

    def weighted_vwap(group: pd.DataFrame) -> float:
        if "vwap" not in group or group.vwap.isna().all() or group.volume.sum() <= 0:
            return np.nan
        valid = group.vwap.notna() & group.volume.gt(0)
        return float(np.average(group.loc[valid, "vwap"], weights=group.loc[valid, "volume"])) if valid.any() else np.nan

    grouped = frame.groupby(keys, sort=False, observed=True)
    output = grouped.agg(
        bar_start_ts_utc=("bar_start_ts_utc", "first"), bar_end_ts_utc=("bar_end_ts_utc", "last"),
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), constituent_bars=("_ordinal", "size"),
    ).reset_index(drop=False)
    if "trade_count" in frame:
        output["trade_count"] = grouped.trade_count.sum(min_count=1).to_numpy()
    if "vwap" in frame:
        output["vwap"] = grouped.apply(weighted_vwap, include_groups=False).to_numpy()
    output["availability_ts_utc"] = output.bar_end_ts_utc
    output["bar_minutes"] = "session" if minutes is None else int(minutes)
    return output.drop(columns="_bucket")
