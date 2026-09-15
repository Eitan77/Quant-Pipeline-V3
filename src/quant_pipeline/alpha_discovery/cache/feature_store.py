from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import numpy as np


class ArrayStore:
    """Memory-mapped feature/target blocks with atomic metadata."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, values: np.ndarray, columns: list[str], dtype=np.float32,
              lineage_hash: str | None = None) -> Path:
        if values.ndim != 2 or values.shape[1] != len(columns):
            raise ValueError("Array shape and columns disagree")
        target = self.root / f"{name}.npy"; temporary = self.root / f"{name}.tmp.npy"
        array = np.asarray(values, dtype=dtype)
        np.save(temporary, array, allow_pickle=False)
        temporary.replace(target)
        meta = target.with_suffix(".json"); tmp_meta = meta.with_suffix(".tmp.json")
        hasher=sha256()
        with target.open('rb') as stream:
            for chunk in iter(lambda:stream.read(8*1024*1024),b''): hasher.update(chunk)
        digest=hasher.hexdigest()
        tmp_meta.write_text(json.dumps({"shape": list(array.shape), "dtype": str(array.dtype),
                                        "columns": columns, "sha256": digest,
                                        "lineage_hash": lineage_hash}, indent=2), encoding="utf-8")
        tmp_meta.replace(meta)
        return target

    def read(self, name: str) -> tuple[np.memmap, list[str]]:
        target = self.root / f"{name}.npy"; metadata = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
        values = np.load(target, mmap_mode="r", allow_pickle=False)
        if list(values.shape) != metadata["shape"]:
            raise ValueError("Array store shape mismatch")
        if str(values.dtype) != metadata["dtype"]:
            raise ValueError("Array store dtype mismatch")
        return values, list(metadata["columns"])
