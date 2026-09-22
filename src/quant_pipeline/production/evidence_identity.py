from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stage_identity(*, stage, sources, observation_id, upstream,
                   definitions, semantics, implementation, schema, numeric):
    # Inputs must already be JSON primitives; never stringify unknown objects.
    return digest(dict(stage=stage, sources=sources, observation_id=observation_id,
                       upstream=upstream, definitions=definitions,
                       semantics=semantics, implementation=implementation,
                       schema=schema, numeric=numeric))


def task_identity(stage_id, *, pair_ids, target_ids, resolution,
                  grouping_id, group_start, group_stop, state_kind="dual"):
    if len(set(pair_ids)) != len(pair_ids) or len(set(target_ids)) != len(target_ids):
        raise ValueError("Task axes must have unique IDs")
    if not 0 <= group_start < group_stop:
        raise ValueError("Invalid group partition")
    if state_kind not in ("single", "dual"):
        raise ValueError("Invalid state kind")
    task = dict(stage_id=stage_id, pair_ids=list(pair_ids), target_ids=list(target_ids),
                resolution=int(resolution), grouping_id=grouping_id,
                group_start=int(group_start), group_stop=int(group_stop), state_kind=state_kind)
    return {**task, "task_id": digest(task)}


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    path = Path(relative)
    if path.is_absolute():
        raise ValueError("Artifact paths must be relative")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Artifact escapes evidence root")
    return resolved
