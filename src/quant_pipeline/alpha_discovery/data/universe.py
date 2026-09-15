from __future__ import annotations

import pandas as pd


def apply_point_in_time_universe(panel: pd.DataFrame, membership: pd.DataFrame, security_master: pd.DataFrame) -> pd.DataFrame:
    if membership.duplicated(["security_id", "session_date"]).any():
        raise ValueError("Duplicate point-in-time membership keys")
    valid_ids = set(security_master.security_id)
    if not set(panel.security_id).issubset(valid_ids):
        raise ValueError("Panel contains security IDs absent from security master")
    merged = panel.merge(membership[["security_id", "session_date", "in_universe"]], on=["security_id", "session_date"], how="left", validate="many_to_one")
    merged["in_universe"] = merged.in_universe.fillna(False).astype(bool)
    return merged[merged.in_universe].copy()
