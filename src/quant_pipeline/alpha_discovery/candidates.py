from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any
import numpy as np
import pandas as pd
from .models import stable_hash


@dataclass(frozen=True)
class CandidateRule:
    structure_type: str
    feature_ids: tuple[str, ...]
    target_id: str
    direction: int
    resolution: int | None = None
    active_cells: tuple[int, ...] = ()
    tail_fraction: float = .10
    missing_behavior: str = "inactive"
    threshold_policy: str = "decision_cross_section"
    execution_policy: str = "long_only"
    definition_hash: str = ""

    @classmethod
    def create(cls, structure_type: str, feature_ids: tuple[str, ...], target_id: str,
               direction: int, resolution: int | None = None, active_cells: tuple[int, ...] = (),
               tail_fraction: float = .10) -> "CandidateRule":
        payload = {"structure_type": structure_type, "feature_ids": feature_ids, "target_id": target_id,
                   "direction": int(direction), "resolution": resolution, "active_cells": active_cells,
                   "tail_fraction": tail_fraction, "missing_behavior": "inactive",
                   "threshold_policy": "decision_cross_section", "execution_policy": "long_only"}
        return cls(**payload, definition_hash=stable_hash(payload))

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def single_positions(score: np.ndarray, direction: int, tail: float = .10,
                     *, decision_ts=None, cutoffs: tuple[float, float] | None = None) -> np.ndarray:
    """Causal cross-sectional signals or frozen training cutoffs; no sample fallback."""
    if direction not in (-1, 1) or not 0 < tail < .5: raise ValueError("Invalid direction or tail")
    values=np.asarray(score,float); valid=np.isfinite(values); out=np.zeros(len(values),dtype=np.float32)
    if cutoffs is not None:
        low, high = cutoffs
        if not np.isfinite([low, high]).all() or low >= high:
            raise ValueError("Frozen cutoffs must be finite and strictly increasing")
    elif decision_ts is not None:
        if len(decision_ts) != len(values) or pd.isna(decision_ts).any():
            raise ValueError("Decision timestamps must be complete and row-aligned")
        frame = pd.DataFrame({"value":np.where(valid, values, np.nan), "decision":np.asarray(decision_ts)})
        grouped = frame.groupby("decision", sort=False).value
        thresholds = grouped.quantile([tail, 1-tail]).unstack()
        low = frame.decision.map(thresholds[tail]).to_numpy()
        high = frame.decision.map(thresholds[1-tail]).to_numpy()
        valid &= (grouped.transform("count").to_numpy() >= 20) & (low < high)
    else:
        raise ValueError("Causal signals require decision_ts or frozen cutoffs")
    out[valid & (values>=high)]=direction; out[valid & (values<=low)]=-direction
    return out


def dual_positions(left_bins: np.ndarray, right_bins: np.ndarray, rule: CandidateRule) -> np.ndarray:
    left,right=np.asarray(left_bins),np.asarray(right_bins); valid=(left>=0)&(right>=0)
    cells=left.astype(np.int16)*int(rule.resolution)+right.astype(np.int16)
    active=valid & np.isin(cells,np.asarray(rule.active_cells,dtype=np.int16))
    out=np.zeros(len(left),dtype=np.float32); out[active]=rule.direction
    return out
