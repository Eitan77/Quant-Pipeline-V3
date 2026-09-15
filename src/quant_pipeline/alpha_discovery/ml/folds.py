from __future__ import annotations

import numpy as np
import pandas as pd


def purged_walk_forward_folds(decision_ts, label_available_ts, folds: int = 5,
                              embargo: str = "0s") -> list[tuple[np.ndarray, np.ndarray]]:
    """Keep timestamp groups intact; exclude labels unavailable at train cutoff."""
    decisions = pd.DatetimeIndex(pd.to_datetime(decision_ts, utc=True))
    available = pd.DatetimeIndex(pd.to_datetime(label_available_ts, utc=True))
    if len(decisions) != len(available) or decisions.hasnans or available.hasnans:
        raise ValueError("Complete aligned decision and label timestamps are required")
    if folds < 1 or (available < decisions).any(): raise ValueError("Invalid label timestamps or folds")
    gap = pd.Timedelta(embargo)
    if gap < pd.Timedelta(0): raise ValueError("Embargo must be nonnegative")
    groups = np.array_split(decisions.unique().sort_values(), folds + 1)
    output = []
    for validation_dates in groups[1:]:
        if not len(validation_dates): continue
        start = validation_dates[0]
        train = np.flatnonzero((decisions < start-gap) & (available < start-gap))
        validation = np.flatnonzero(decisions.isin(validation_dates))
        if len(train) and len(validation): output.append((train, validation))
    return output
