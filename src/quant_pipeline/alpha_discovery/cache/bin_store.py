from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .feature_store import ArrayStore


class BinStore(ArrayStore):
    """Compact rank-bin blocks. Missing observations are encoded as -1."""

    def write(self, name: str, values: np.ndarray, columns: list[str], bins: int = 5) -> Path:
        array = np.asarray(values)
        if array.ndim != 2 or array.shape[1] != len(columns):
            raise ValueError("Bin block shape and columns disagree")
        if not np.issubdtype(array.dtype, np.integer):
            raise ValueError("Rank bins must use an integer dtype")
        if ((array < -1) | (array >= bins)).any():
            raise ValueError(f"Rank-bin values must be -1 or in [0, {bins - 1}]")
        target = super().write(name, array.astype(np.int8, copy=False), columns, dtype=np.int8)
        metadata = target.with_suffix(".json"); payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload["bins"] = bins; pending = metadata.with_suffix(".tmp.json")
        pending.write_text(json.dumps(payload, indent=2), encoding="utf-8"); pending.replace(metadata)
        return target

    def read(self, name: str) -> tuple[np.memmap, list[str]]:
        values, columns = super().read(name)
        metadata = json.loads((self.root / f"{name}.json").read_text(encoding="utf-8"))
        if values.dtype != np.int8 or ((values < -1) | (values >= int(metadata["bins"]))).any():
            raise ValueError("Persisted rank-bin block violates its metadata contract")
        return values, columns


class PackedBinStore(ArrayStore):
    """One-byte lossless storage for combined 3/5/10 rank-bin labels."""

    def write(self, name: str, values: np.ndarray, columns: list[str]) -> Path:
        array = np.asarray(values)
        if array.ndim != 2 or array.shape[1] != len(columns):
            raise ValueError("Packed-bin block shape and columns disagree")
        if not np.issubdtype(array.dtype, np.integer):
            raise ValueError("Packed bins must use an integer dtype")
        if ((array > 149) & (array != 255)).any():
            raise ValueError("Packed-bin values must be in [0, 149] or 255")
        target = super().write(name, array.astype(np.uint8, copy=False), columns, dtype=np.uint8)
        metadata = target.with_suffix(".json"); payload = json.loads(metadata.read_text(encoding="utf-8"))
        payload.update({"packed_resolutions": [3, 5, 10], "missing_code": 255})
        pending = metadata.with_suffix(".tmp.json")
        pending.write_text(json.dumps(payload, indent=2), encoding="utf-8"); pending.replace(metadata)
        return target

    def read(self, name: str) -> tuple[np.memmap, list[str]]:
        values, columns = super().read(name)
        metadata = json.loads((self.root / f"{name}.json").read_text(encoding="utf-8"))
        if values.dtype != np.uint8 or metadata.get("packed_resolutions") != [3, 5, 10]:
            raise ValueError("Persisted packed-bin block violates its metadata contract")
        return values, columns
