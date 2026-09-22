from __future__ import annotations

from .evidence_artifacts import commit_tile, committed_tile
from .segmented_scan import SegmentedMoments, local_group_codes


def execute_segmented_task(*, root, task, reader, pair_definitions,
                           observation_id, row_chunk, max_state_bytes,
                           device="cpu", cancelled=lambda: False):
    """One complete logical task; caller owns its lock and verified stage manifest."""
    if reader.grid["observation_id"] != observation_id or row_chunk < 1:
        raise ValueError("Invalid task input identity or chunk size")
    previous = committed_tile(root, task)
    if previous is not None:
        return previous
    singles = task["state_kind"] == "single"
    pairs = [pair_definitions[key] for key in task["pair_ids"]]
    if any(len(pair) != (1 if singles else 2) for pair in pairs):
        raise ValueError("Pair definitions and state kind disagree")
    features = sorted({key for pair in pairs for key in pair})
    index = {key: i for i, key in enumerate(features)}
    left = [index[pair[0]] for pair in pairs]
    right = None if singles else [index[pair[1]] for pair in pairs]
    moments = SegmentedMoments(
        pairs=len(pairs), targets=len(task["target_ids"]),
        groups=task["group_stop"] - task["group_start"],
        resolution=task["resolution"], singles=singles,
        device=device, max_state_bytes=max_state_bytes,
    )
    for start in range(0, reader.rows, row_chunk):
        if cancelled():
            raise InterruptedError("Job cancelled at observation-chunk boundary")
        stop = min(start + row_chunk, reader.rows)
        groups = local_group_codes(reader.read_groups(task["grouping_id"], start, stop),
                                   task["group_start"], task["group_stop"])
        moments.update(reader.read_columns("bins", features, start, stop), left, right,
                       reader.read_columns("targets", task["target_ids"], start, stop), groups)
    if cancelled():
        raise InterruptedError("Job cancelled before commit")
    return commit_tile(root, task, moments)
