from __future__ import annotations

import numpy as np
import pandas as pd


def build_split_consistent_view(raw: pd.DataFrame, split_factors: pd.DataFrame) -> pd.DataFrame:
    factors = split_factors[["security_id", "session_date", "split_factor"]].copy()
    if factors.duplicated(["security_id", "session_date"]).any():
        raise ValueError("Duplicate split-factor keys")
    output = raw.merge(factors, on=["security_id", "session_date"], how="left", validate="many_to_one")
    output["split_factor"] = output.split_factor.fillna(1.0)
    if (~np.isfinite(output.split_factor) | output.split_factor.le(0)).any():
        raise ValueError("Invalid split factors")
    for column in ("open", "high", "low", "close", "vwap"):
        if column in output:
            output[f"research_{column}"] = output[column] / output.split_factor
    output["price_basis"] = "split_consistent"
    return output
