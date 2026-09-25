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
                            materialize=True, fused_cuda=False, resident_grid=None):
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
    if resident_grid is not None and not materialize and all(previous is None for _, previous in pending):
        results = resident_grid.joint_batch(rows, pairs, first["target_ids"], max_state_bytes,
                                           consume_block, cancelled)
        if results is not None:
            return results
    live = []
    state_bytes = 0
    for row, previous in pending:
        if previous is not None:
            continue
        task = row["task"]
        cells = task["resolution"] if singles else task["resolution"] ** 2
        state_bytes += (24 if materialize else 16) * len(pairs) * len(first["target_ids"]) * (task["group_stop"]-task["group_start"]) * cells
        if state_bytes > max_state_bytes:
            raise MemoryError("Batch accumulator state exceeds admission")
        live.append((task, SegmentedMoments(pairs=len(pairs), targets=len(first["target_ids"]),
                    groups=task["group_stop"]-task["group_start"], resolution=task["resolution"],
                    singles=singles, device=device, max_state_bytes=max_state_bytes,
                    track_sumsq=materialize)))
    fused = None
    if live and resident_grid is not None:
        resident_grid.accumulate(live, pairs, first["target_ids"], cancelled)
    elif live and fused_cuda and device != "cpu":
        from .segmented_cuda import FusedSegmentedBatch
        fused = FusedSegmentedBatch(live, left, right)
    for start in range(0, 0 if resident_grid is not None else reader.rows, row_chunk):
        if cancelled():
            raise InterruptedError("Coverage cancelled at observation-chunk boundary")
        stop = min(start + row_chunk, reader.rows)
        if not live:
            break
        partitions = {(task["grouping_id"], task["group_start"], task["group_stop"])
                      for task, _ in live}
        group_codes = {grouping: reader.read_groups(grouping, start, stop)
                       for grouping, _, _ in partitions}
        active = np.zeros(stop-start, dtype=np.bool_)
        for grouping, group_start, group_stop in partitions:
            codes = group_codes[grouping]
            active |= (codes >= group_start) & (codes < group_stop)
        if not active.any():
            continue
        sparse = np.flatnonzero(active) if not active.all() else None
        prepared = prepare_tile(reader.read_columns("bins", features, start, stop, sparse),
                                reader.read_columns("targets", first["target_ids"], start, stop, sparse), device)
        if fused is not None:
            fused.update(prepared, {family: codes if sparse is None else codes[sparse]
                                    for family, codes in group_codes.items()})
            continue
        local_codes = {
            partition: local_group_codes(group_codes[partition[0]] if sparse is None else
                                         group_codes[partition[0]][sparse], partition[1], partition[2])
            for partition in partitions
        }
        for task, moments in live:
            partition = (task["grouping_id"], task["group_start"], task["group_stop"])
            moments.update_prepared(prepared, left, right, local_codes[partition])
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
