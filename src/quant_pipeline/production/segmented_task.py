from __future__ import annotations

import numpy as np

from .evidence_artifacts import commit_tile, committed_tile
from .segmented_scan import SegmentedMoments, local_group_codes, prepare_tile


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
        active = np.flatnonzero(groups >= 0)
        if not len(active):
            continue
        sparse = active if len(active) < len(groups) else None
        moments.update(reader.read_columns("bins", features, start, stop, sparse), left, right,
                       reader.read_columns("targets", task["target_ids"], start, stop, sparse),
                       groups if sparse is None else groups[sparse])
    if cancelled():
        raise InterruptedError("Job cancelled before commit")
    return commit_tile(root, task, moments)


def execute_segmented_batch(*, root, rows, reader, row_chunk, max_state_bytes,
                            device="cpu", cancelled=lambda: False, consume_block=None,
                            materialize=True):
    """Scan one pair/target tile for all admitted grouping and resolution tasks."""
    rows = list(rows)
    if not rows:
        return []
    first = rows[0]["task"]
    if any(row["task"]["pair_ids"] != first["pair_ids"] or
           row["task"]["target_ids"] != first["target_ids"] or
           row["task"]["state_kind"] != first["state_kind"] for row in rows):
        raise ValueError("Batch members must share pair and target axes")
    pending = [(row, committed_tile(root, row["task"])) for row in rows]
    singles = first["state_kind"] == "single"
    definitions = rows[0]["pairs"]
    pairs = [definitions[key] for key in first["pair_ids"]]
    features = sorted({feature for pair in pairs for feature in pair})
    index = {key: i for i, key in enumerate(features)}
    left = [index[pair[0]] for pair in pairs]
    right = None if singles else [index[pair[1]] for pair in pairs]
    live = []
    state_bytes = 0
    for row, previous in pending:
        if previous is not None:
            continue
        task = row["task"]
        cells = task["resolution"] if singles else task["resolution"] ** 2
        state_bytes += 24 * len(pairs) * len(first["target_ids"]) * (task["group_stop"]-task["group_start"]) * cells
        if state_bytes > max_state_bytes:
            raise MemoryError("Batch accumulator state exceeds admission")
        live.append((task, SegmentedMoments(pairs=len(pairs), targets=len(first["target_ids"]),
                    groups=task["group_stop"]-task["group_start"], resolution=task["resolution"],
                    singles=singles, device=device, max_state_bytes=max_state_bytes)))
    for start in range(0, reader.rows, row_chunk):
        if cancelled():
            raise InterruptedError("Coverage cancelled at observation-chunk boundary")
        stop = min(start + row_chunk, reader.rows)
        if not live:
            break
        group_codes = {task["grouping_id"]: reader.read_groups(task["grouping_id"], start, stop)
                       for task, _ in live}
        active = np.zeros(stop-start, dtype=np.bool_)
        for task, _ in live:
            codes = group_codes[task["grouping_id"]]
            active |= (codes >= task["group_start"]) & (codes < task["group_stop"])
        if not active.any():
            continue
        sparse = np.flatnonzero(active) if not active.all() else None
        prepared = prepare_tile(reader.read_columns("bins", features, start, stop, sparse),
                                reader.read_columns("targets", first["target_ids"], start, stop, sparse), device)
        for task, moments in live:
            codes = group_codes[task["grouping_id"]]
            local = local_group_codes(codes if sparse is None else codes[sparse],
                                      task["group_start"], task["group_stop"])
            moments.update_prepared(prepared, left, right, local)
    computed = {}
    for task, moments in live:
        if cancelled():
            raise InterruptedError("Coverage cancelled before commit")
        if consume_block is not None:
            consume_block(task, moments, {"grid": rows[0]["grid"], "rows_evaluated": reader.rows})
        if materialize:
            computed[task["task_id"]] = commit_tile(root, task, moments)
        else:
            populated = (int(np.count_nonzero(np.any(moments.n, axis=-1))) if moments.torch is None
                         else int(moments.n.any(dim=-1).sum().item()))
            computed[task["task_id"]] = {
                "compute_status": "complete", "materialization_status": "recomputable",
                "artifact": None, "bytes": 0, "sha256": None,
                "populated_groups": populated,
            }
    return [computed.get(row["task"]["task_id"], previous) for row, previous in pending]
