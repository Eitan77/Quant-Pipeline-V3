from __future__ import annotations

from datetime import date


def canonical_cells(feature_a, feature_b, resolution, cells):
    if resolution not in (3, 5, 10):
        raise ValueError("Unsupported resolution")
    cells = tuple(cells)
    if not cells or any(type(c) is not int or not 0 <= c < resolution**2 for c in cells):
        raise ValueError("Invalid or empty cell union")
    if feature_a <= feature_b:
        return feature_a, feature_b, tuple(sorted(set(cells)))
    transposed = {(c % resolution) * resolution + c // resolution for c in cells}
    return feature_b, feature_a, tuple(sorted(transposed))


def validate_discovery_subrange(request, authorized):
    """authorized is supplied by trusted project governance, not this request."""
    start, end = (date.fromisoformat(request[k]) for k in ("start", "end"))
    first, last = (date.fromisoformat(authorized[k]) for k in ("start", "end"))
    if not first <= start <= end <= last:
        raise ValueError("Requested discovery range is outside the authorized envelope")
    return {"start": start.isoformat(), "end": end.isoformat()}


def coverage_complete(planned_ids, records):
    planned = set(planned_ids)
    if len(planned) != len(planned_ids):
        raise ValueError("Duplicate planned tasks")
    current = {}
    for record in records:
        task_id = record["task_id"]
        if task_id in current or task_id not in planned:
            raise ValueError("Duplicate or unplanned task result")
        current[task_id] = record
    return bool(planned) and all(
        task_id in current and current[task_id]["compute_status"] == "complete"
        for task_id in planned
    )


def fold_coverage(counts, expected_folds):
    import numpy as np
    counts = np.asarray(counts)
    if counts.ndim != 3 or counts.shape[1] == 0 or np.any(counts < 0):
        raise ValueError("Expected nonnegative pair/fold/cell counts")
    if not counts.shape[1] <= expected_folds <= np.iinfo(np.uint32).max:
        raise ValueError("Expected fold count is inconsistent")
    shape = (counts.shape[0], counts.shape[2])
    return {
        "populated_fold_count": (counts > 0).sum(axis=1),
        "expected_fold_count": np.full(shape, expected_folds, dtype=np.uint32),
        "minimum_fold_n_including_empty": counts.min(axis=1) if expected_folds == counts.shape[1] else np.zeros(shape, dtype=counts.dtype),
    }
