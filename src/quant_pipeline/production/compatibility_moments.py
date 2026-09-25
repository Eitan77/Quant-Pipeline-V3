"""Legacy specialist and temporal tables derived from authoritative moments."""
from __future__ import annotations

import json
import os
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .cell_specialist import SCHEMA as SPECIALIST_SCHEMA, _summaries, _summaries_cuda
from .cell_temporal import SCHEMA as TEMPORAL_SCHEMA, _reduce
from .evidence_artifacts import load_tile
from .evidence_store import EvidenceReader
from .segmented_task import execute_segmented_task
from .evidence_identity import atomic_json


class CompatibilitySink:
    """Reduce security/fold moments while their coverage tile is already live."""

    def __init__(self, root, reader_manifest, stage_id, *, minimum, expected_folds, workers=1, device="cpu"):
        self.root=Path(root);self.reader_manifest=reader_manifest;self.stage_id=stage_id
        self.minimum=minimum;self.expected_folds=expected_folds;self.parts={}
        self.device=device
        self.workers=max(1,int(workers));self.executor=None
        self.manifest=self.root/"evidence"/"compatibility.json"
        previous=json.loads(self.manifest.read_text()) if self.manifest.exists() else {}
        self.ready=(previous.get("stage_id")==stage_id and
                    all((self.root/name).exists() for name in
                        ("cell_specialist_summary.parquet","cell_temporal_summary.parquet")))
        self.part_dir=self.root/"evidence"/"compatibility_parts"/stage_id
        self.completed={}
        if not self.ready:
            self.part_dir.mkdir(parents=True,exist_ok=True)
            for marker in self.part_dir.glob("*.json"):
                payload=json.loads(marker.read_text(encoding="utf-8"))
                if payload.get("stage_id")!=stage_id or payload.get("schema_version")!=1:
                    continue
                if all((self.part_dir/name).exists() for name in payload["files"].values()):
                    key=payload["key"]
                    self.completed[(key[0],key[1],tuple(key[2]),tuple(key[3]))]=payload
            if self.workers>1:self.executor=ThreadPoolExecutor(max_workers=self.workers,
                                                               thread_name_prefix="compatibility")

    def has_group(self, key):
        return self.ready or key in self.completed

    def consume_existing(self, grid, rows):
        """Load reusable moment tiles concurrently; return rows whose tile was evicted."""
        if self.ready or not rows:return []
        load=lambda row:load_tile(self.root,row["task"])
        moments=(map(load,rows) if self.executor is None else self.executor.map(load,rows))
        missing=[]
        for row,value in zip(rows,moments):
            if value is None:missing.append(row)
            else:self.consume(grid,row["task"],value)
        return missing

    def consume(self, grid, task, moments):
        grouping=task["grouping_id"]
        key=(grid,task["state_kind"],tuple(task["pair_ids"]),tuple(task["target_ids"]))
        if self.has_group(key) or task["state_kind"]!="dual" or grouping not in {"security","fold"}:return
        groups=int(self.reader_manifest["grids"][grid]["groups"][grouping]["groups"])
        part_key=(grid,tuple(task["pair_ids"]),tuple(task["target_ids"]),task["resolution"],grouping)
        if part_key not in self.parts:
            shape=(len(task["target_ids"]),len(task["pair_ids"]),groups,task["resolution"]**2)
            self.parts[part_key]=(np.zeros(shape,np.int64),np.zeros(shape,np.float64),np.zeros(groups,bool))
        counts,sums,seen=self.parts[part_key]
        start,stop=task["group_start"],task["group_stop"]
        if seen[start:stop].any():raise ValueError("Duplicate compatibility group partition")
        n,s=moments.counts_and_sums() if hasattr(moments,"counts_and_sums") else moments.numpy()[:2]
        counts[:,:,start:stop]=n;sums[:,:,start:stop]=s;seen[start:stop]=True

    def finish_group(self, group_key):
        if self.has_group(group_key):return
        jobs=[]
        for key,(counts,sums,seen) in self.parts.items():
            if not seen.all():raise ValueError("Incomplete compatibility group partitions")
            grid,pairs,targets,resolution,grouping=key
            for ti,target in enumerate(targets):
                jobs.append((grid,pairs,target,resolution,grouping,counts[ti],sums[ti]))

        def reduce_job(job):
            grid,pairs,target,resolution,grouping,counts,sums=job
            reduced=((_summaries_cuda(counts,sums,self.minimum) if self.device.startswith("cuda") and counts.size>=100_000
                      else _summaries(counts,sums,self.minimum)) if grouping=="security"
                     else _reduce(counts,sums,expected_folds=self.expected_folds or
                                  self.reader_manifest["grids"][grid]["groups"]["fold"]["expected_folds"]))
            return grouping,[{"pair_id":pair,"target_id":target,"resolution":resolution,**metrics}
                             for pair,metrics in zip(pairs,reduced)]

        results=(map(reduce_job,jobs) if self.executor is None else self.executor.map(reduce_job,jobs))
        grouped={"security":[],"fold":[]}
        for grouping,records in results:grouped[grouping].extend(records)
        key_json=json.dumps(group_key,separators=(",",":"))
        prefix=sha256(key_json.encode()).hexdigest()[:24]
        files={};rows={}
        for grouping,records in grouped.items():
            if not records:continue
            schema=SPECIALIST_SCHEMA if grouping=="security" else TEMPORAL_SCHEMA
            table=pa.Table.from_pylist(records,schema=schema)
            name=f"{prefix}-{grouping}.parquet"
            temporary=self.part_dir/f"{name}.partial"
            pq.write_table(table,temporary,compression="zstd")
            os.replace(temporary,self.part_dir/name)
            files[grouping]=name;rows[grouping]=len(records)
        if files:
            payload={"schema_version":1,"stage_id":self.stage_id,"key":group_key,
                     "files":files,"rows":rows}
            atomic_json(self.part_dir/f"{prefix}.json",payload)
            self.completed[group_key]=payload
        self.parts.clear()

    def _shutdown(self):
        if self.executor is not None:
            self.executor.shutdown(wait=True);self.executor=None

    def publish(self):
        if self.ready:return
        self._shutdown()
        counts={"security":0,"fold":0}
        for grouping,schema in (("security",SPECIALIST_SCHEMA),("fold",TEMPORAL_SCHEMA)):
            name="cell_specialist_summary.parquet" if grouping=="security" else "cell_temporal_summary.parquet"
            temporary=(self.root/name).with_suffix(".partial.parquet")
            with pq.ParquetWriter(temporary,schema,compression="zstd") as writer:
                for key in sorted(self.completed):
                    payload=self.completed[key]
                    if grouping in payload["files"]:
                        writer.write_table(pq.read_table(self.part_dir/payload["files"][grouping]))
                        counts[grouping]+=payload["rows"][grouping]
            os.replace(temporary,self.root/name)
        atomic_json(self.manifest,{"stage_id":self.stage_id,"rows":counts,"status":"complete"})
        self.ready=True

    def abort(self):
        self._shutdown()


def derive_compatibility(root, plan, reader_manifest, *, minimum, expected_folds,
                         device, row_chunk, max_state_bytes, cancelled=lambda: False):
    root = Path(root)
    outputs = {}
    readers = {}
    for grouping, destination, schema in (
        ("security", root / "cell_specialist_summary.parquet", SPECIALIST_SCHEMA),
        ("fold", root / "cell_temporal_summary.parquet", TEMPORAL_SCHEMA),
    ):
        temporary = destination.with_suffix(".moments.partial.parquet")
        pending = None
        seen = 0
        with pq.ParquetWriter(temporary, schema, compression="zstd") as writer:
            with (root / plan["path"]).open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    task = row["task"]
                    if task["state_kind"] != "dual" or task["grouping_id"] != grouping:
                        continue
                    if cancelled(): raise InterruptedError("Compatibility reduction cancelled")
                    grid = row["grid"]
                    if grid not in readers:
                        readers[grid] = EvidenceReader(root, "evidence/reader.json", grid)
                    reader = readers[grid]
                    key = (grid, tuple(task["pair_ids"]), tuple(task["target_ids"]), task["resolution"])
                    groups = reader_manifest["grids"][grid]["groups"][grouping]["groups"]
                    if pending is None or pending[0] != key:
                        if pending is not None:
                            raise ValueError("Incomplete compatibility group partitions")
                        shape = (len(task["target_ids"]), len(task["pair_ids"]), groups, task["resolution"] ** 2)
                        pending = (key, np.zeros(shape, np.int64), np.zeros(shape, np.float64))
                    moments = load_tile(root, task)
                    if moments is None:
                        execute_segmented_task(root=root, task=task, reader=reader,
                            pair_definitions=row["pairs"], observation_id=reader.grid["observation_id"],
                            row_chunk=row_chunk, max_state_bytes=max_state_bytes,
                            device=device, cancelled=cancelled)
                        moments = load_tile(root, task)
                    counts, sums, _ = moments.numpy()
                    pending[1][:, :, task["group_start"]:task["group_stop"]] = counts
                    pending[2][:, :, task["group_start"]:task["group_stop"]] = sums
                    if task["group_stop"] == groups:
                        records = []
                        for ti, target in enumerate(task["target_ids"]):
                            reduced = (_summaries(pending[1][ti], pending[2][ti], minimum) if grouping == "security"
                                       else _reduce(pending[1][ti], pending[2][ti], expected_folds=expected_folds))
                            for pair, metrics in zip(task["pair_ids"], reduced):
                                records.append({"pair_id":pair,"target_id":target,
                                                "resolution":task["resolution"], **metrics})
                        writer.write_table(pa.Table.from_pylist(records, schema=schema))
                        seen += len(records)
                        pending = None
        if pending is not None:
            raise ValueError("Unfinished compatibility moment partition")
        os.replace(temporary, destination)
        outputs[grouping] = {"path": str(destination), "rows": seen}
    return outputs
