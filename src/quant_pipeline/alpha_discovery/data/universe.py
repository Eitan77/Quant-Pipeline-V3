from __future__ import annotations

import pandas as pd


def apply_point_in_time_universe(panel: pd.DataFrame, membership: pd.DataFrame, security_master: pd.DataFrame, universe: dict | None = None, full_bars: pd.DataFrame | None = None) -> pd.DataFrame:
    if membership.duplicated(["security_id", "session_date"]).any():
        raise ValueError("Duplicate point-in-time membership keys")
    valid_ids = set(security_master.security_id)
    if not set(panel.security_id).issubset(valid_ids):
        raise ValueError("Panel contains security IDs absent from security master")
    merged = panel.merge(membership[["security_id", "session_date", "in_universe"]], on=["security_id", "session_date"], how="left", validate="many_to_one")
    merged["in_universe"] = merged.in_universe.fillna(False).astype(bool)
    if universe is None or full_bars is None:
        return merged[merged.in_universe].copy()
    daily = full_bars.sort_values(["security_id", "session_date", "bar_start_ts_utc"]).copy()
    price = daily["vwap"].where(daily["vwap"].notna(), daily["close"])
    daily["_dollar_volume"] = price * daily["volume"]
    daily = (daily.groupby(["security_id", "session_date"], as_index=False).agg(session_close=("close", "last"), dollar_volume=("_dollar_volume", "sum")).sort_values(["security_id", "session_date"]))
    g = daily.groupby("security_id", sort=False)
    daily["prior_close"] = g["session_close"].shift(1)
    daily["prior_20d_median_dollar_volume"] = g["dollar_volume"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).median())
    daily["passes_universe_filters"] = daily["prior_close"].ge(float(universe["minimum_price"])) & daily["prior_20d_median_dollar_volume"].ge(float(universe["minimum_prior_20d_median_dollar_volume"]))
    eligibility = daily[["security_id", "session_date", "passes_universe_filters"]]
    merged = merged.merge(eligibility, on=["security_id", "session_date"], how="left", validate="many_to_one")
    merged["passes_universe_filters"] = merged.passes_universe_filters.fillna(False).astype(bool)
    return merged[merged.in_universe & merged.passes_universe_filters].copy()
