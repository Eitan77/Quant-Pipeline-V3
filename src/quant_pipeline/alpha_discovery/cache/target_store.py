from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import numpy as np

from .feature_store import ArrayStore


class TargetStore(ArrayStore):
    """Float target blocks with an explicit finite-observation contract."""

    def write(self, name: str, values: np.ndarray, columns: list[str], lineage_hash: str | None = None):
        array = np.asarray(values, dtype=float)
        if array.ndim != 2 or not columns:
            raise ValueError("Target blocks must be two-dimensional and named")
        if not np.isfinite(array).any(axis=0).all():
            missing = [column for column, valid in zip(columns, np.isfinite(array).any(axis=0)) if not valid]
            raise ValueError(f"Target columns contain no finite observations: {missing}")
        return super().write(name, array, columns, dtype=np.float32, lineage_hash=lineage_hash)

    def write_aligned(self, name: str, observation_ids: np.ndarray, values: np.ndarray,
                      columns: list[str], ledger_path: str | Path) -> Path:
        ledger = Path(ledger_path)
        lineage = sha256(ledger.read_bytes()).hexdigest()
        target = self.write(name, values, columns, lineage_hash=lineage)
        ids = np.asarray(observation_ids, dtype=np.int64)
        ids_path = self.root / f"{name}.observations.npy"
        pending = self.root / f"{name}.observations.tmp.npy"
        np.save(pending, ids, allow_pickle=False); pending.replace(ids_path)
        meta_path = target.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["observation_count"] = len(ids)
        tmp = meta_path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8"); tmp.replace(meta_path)
        return target

    def read_slice(self, name: str, rows: slice, columns: slice | np.ndarray | list[int]):
        values, names = self.read(name)
        return values[rows, columns], names

    def build_columns(self, name: str, observation_ids: np.ndarray, columns: list[str], loader,
                      ledger_path: str | Path) -> Path:
        """Build a bounded aligned matrix without holding all targets in RAM."""
        target = self.root / f"{name}.npy"; pending = self.root / f"{name}.tmp.npy"
        matrix = np.lib.format.open_memmap(pending, mode="w+", dtype=np.float32,
                                           shape=(len(observation_ids), len(columns)))
        for index, column in enumerate(columns): matrix[:, index] = loader(column)
        matrix.flush(); del matrix; pending.replace(target)
        ids_path = self.root / f"{name}.observations.npy"; ids_pending = self.root / f"{name}.observations.tmp.npy"
        np.save(ids_pending, np.asarray(observation_ids, np.int64), allow_pickle=False); ids_pending.replace(ids_path)
        payload = {"shape": [len(observation_ids), len(columns)], "dtype": "float32", "columns": columns,
                   "sha256": sha256(target.read_bytes()).hexdigest(),
                   "lineage_hash": sha256(Path(ledger_path).read_bytes()).hexdigest(),
                   "observation_count": len(observation_ids)}
        meta = target.with_suffix(".json"); tmp = meta.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8"); tmp.replace(meta)
        return target

    def build_batches(self, name: str, observation_ids: np.ndarray, columns: list[str], loader,
                      ledger_path: str | Path, batch_size: int = 8) -> Path:
        """Build aligned target columns in bounded batches to amortize source scans."""
        target=self.root/f"{name}.npy"; pending=self.root/f"{name}.tmp.npy"
        self.root.mkdir(parents=True,exist_ok=True)
        matrix=np.lib.format.open_memmap(pending,mode="w+",dtype=np.float32,shape=(len(observation_ids),len(columns)))
        for start in range(0,len(columns),batch_size):
            stop=min(start+batch_size,len(columns)); values=np.asarray(loader(columns[start:stop]),dtype=np.float32)
            if values.shape!=(len(observation_ids),stop-start): raise ValueError("Target batch shape disagrees with observation order")
            matrix[:,start:stop]=values
        matrix.flush(); del matrix; pending.replace(target)
        ids_path=self.root/f"{name}.observations.npy"; ids_pending=self.root/f"{name}.observations.tmp.npy"
        np.save(ids_pending,np.asarray(observation_ids,np.int64),allow_pickle=False); ids_pending.replace(ids_path)
        payload={"shape":[len(observation_ids),len(columns)],"dtype":"float32","columns":columns,
                 "sha256":sha256(target.read_bytes()).hexdigest(),"lineage_hash":sha256(Path(ledger_path).read_bytes()).hexdigest(),
                 "observation_count":len(observation_ids)}
        meta=target.with_suffix(".json"); tmp=meta.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(payload,indent=2),encoding="utf-8"); tmp.replace(meta)
        return target
