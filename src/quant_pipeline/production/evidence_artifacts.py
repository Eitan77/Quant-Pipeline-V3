from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .evidence_identity import atomic_json, digest, file_digest, inside


SCHEMA = pa.schema([
    ("pair_id", pa.string()), ("target_id", pa.string()),
    ("resolution", pa.int16()), ("group_id", pa.int64()),
    ("counts", pa.list_(pa.uint64())),
    ("sums", pa.list_(pa.float64())), ("sumsq", pa.list_(pa.float64())),
])


def _task_dir(root, task):
    identity = {k: v for k, v in task.items() if k != "task_id"}
    if digest(identity) != task["task_id"]:
        raise ValueError("Task identity mismatch")
    # Keep the manifest's full hashes; shorten directory components for Windows paths.
    return inside(root, f"segments/{task['stage_id'][:24]}/{task['task_id'][:24]}")


def committed_tile(root, task):
    marker = _task_dir(root, task) / "complete.json"
    if not marker.exists():
        return None
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    if manifest.get("task") != task or manifest.get("schema_version") != 1:
        raise ValueError("Incompatible task manifest")
    path = inside(root, manifest["artifact"])
    if not path.exists():
        return None  # Computed previously; currently absent/evicted. Do not infer zero.
    if path.stat().st_size != manifest["bytes"] or file_digest(path) != manifest["sha256"]:
        raise ValueError("Committed artifact integrity failure")
    return manifest


def commit_tile(root, task, moments, *, rows_per_group=1024):
    """Caller must hold exclusive task ownership. No concurrent writers per task."""
    root = Path(root).resolve()
    previous = committed_tile(root, task)
    if previous is not None:
        return previous
    if rows_per_group < 1:
        raise ValueError("rows_per_group must be positive")
    n, sums, sumsq = moments.numpy()
    expected = (len(task["target_ids"]), len(task["pair_ids"]),
                task["group_stop"] - task["group_start"], moments.cells)
    if (n.shape != expected or moments.resolution != task["resolution"]
            or moments.singles != (task["state_kind"] == "single")):
        raise ValueError("Task and accumulator axes disagree")
    if np.any(n < 0):
        raise OverflowError("Negative accumulated count")
    directory = _task_dir(root, task)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "moments.parquet"
    temporary = directory / "moments.partial.parquet"
    rows, written = [], 0
    try:
        with pq.ParquetWriter(temporary, SCHEMA, compression="zstd") as writer:
            for t, target in enumerate(task["target_ids"]):
                for p, pair in enumerate(task["pair_ids"]):
                    for g in range(expected[2]):
                        if not np.any(n[t, p, g]):
                            continue
                        rows.append(dict(pair_id=pair, target_id=target,
                                         resolution=task["resolution"], group_id=task["group_start"] + g,
                                         counts=n[t, p, g].tolist(), sums=sums[t, p, g].tolist(),
                                         sumsq=sumsq[t, p, g].tolist()))
                        if len(rows) >= rows_per_group:
                            writer.write_table(pa.Table.from_pylist(rows, schema=SCHEMA))
                            written += len(rows)
                            rows.clear()
            if rows:
                writer.write_table(pa.Table.from_pylist(rows, schema=SCHEMA))
                written += len(rows)
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        manifest = dict(schema_version=1, task=task, compute_status="complete",
                        materialization_status="durable", populated_groups=written,
                        artifact=destination.relative_to(root).as_posix(),
                        bytes=destination.stat().st_size, sha256=file_digest(destination))
        atomic_json(directory / "complete.json", manifest)
        return manifest
    finally:
        temporary.unlink(missing_ok=True)
