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
    directory = _task_dir(root, task)
    marker = directory / "complete.json"
    if not marker.exists():
        orphan = directory / "moments.parquet"
        if not orphan.exists():
            return None
        # The shard was atomically renamed before a crash wrote its marker.
        # Recover only exact membership; a numeric filename is not sufficient.
        expected_cells = task["resolution"] if task["state_kind"] == "single" else task["resolution"] ** 2
        allowed_pairs, allowed_targets = set(task["pair_ids"]), set(task["target_ids"])
        seen = set()
        parquet = pq.ParquetFile(orphan)
        if not parquet.schema_arrow.equals(SCHEMA):
            raise ValueError("Orphan tile schema mismatch")
        for batch in parquet.iter_batches(batch_size=1024):
            for row in batch.to_pylist():
                key = (row["pair_id"], row["target_id"], row["group_id"])
                if (key in seen or key[0] not in allowed_pairs or key[1] not in allowed_targets
                        or not task["group_start"] <= key[2] < task["group_stop"]
                        or row["resolution"] != task["resolution"]
                        or any(len(row[name]) != expected_cells for name in ("counts", "sums", "sumsq"))):
                    raise ValueError("Orphan tile membership mismatch")
                seen.add(key)
        root = Path(root).resolve()
        atomic_json(marker, dict(schema_version=1, task=task, compute_status="complete",
                                 materialization_status="durable", populated_groups=len(seen),
                                 artifact=orphan.relative_to(root).as_posix(),
                                 bytes=orphan.stat().st_size, sha256=file_digest(orphan)))
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


class _StoredMoments:
    def __init__(self, task, arrays):
        self.resolution = task["resolution"]
        self.singles = task["state_kind"] == "single"
        self.cells = self.resolution if self.singles else self.resolution ** 2
        self.arrays = arrays

    def numpy(self):
        return self.arrays


def load_tile(root, task):
    """Restore an exact committed tile, including zero-count groups."""
    manifest = committed_tile(root, task)
    if manifest is None:
        return None
    shape = (len(task["target_ids"]), len(task["pair_ids"]),
             task["group_stop"] - task["group_start"],
             task["resolution"] if task["state_kind"] == "single" else task["resolution"] ** 2)
    arrays = (np.zeros(shape, np.int64), np.zeros(shape, np.float64), np.zeros(shape, np.float64))
    targets = {value: i for i, value in enumerate(task["target_ids"])}
    pairs = {value: i for i, value in enumerate(task["pair_ids"])}
    for batch in pq.ParquetFile(inside(root, manifest["artifact"])).iter_batches(batch_size=1024):
        for row in batch.to_pylist():
            key = (targets[row["target_id"]], pairs[row["pair_id"]], row["group_id"] - task["group_start"])
            for array, column in zip(arrays, ("counts", "sums", "sumsq")):
                array[key] = row[column]
    return _StoredMoments(task, arrays)
