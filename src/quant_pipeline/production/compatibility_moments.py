"""Legacy specialist and temporal tables derived from authoritative moments."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .cell_specialist import SCHEMA as SPECIALIST_SCHEMA, _summaries
from .cell_temporal import SCHEMA as TEMPORAL_SCHEMA, _reduce
from .evidence_artifacts import load_tile
from .evidence_store import EvidenceReader
from .segmented_task import execute_segmented_task
from .evidence_identity import atomic_json


class CompatibilitySink:
    """Reduce security/fold moments while their coverage tile is already live."""

    def __init__(self, root, reader_manifest, stage_id, *, minimum, expected_folds):
        self.root=Path(root);self.reader_manifest=reader_manifest;self.stage_id=stage_id
        self.minimum=minimum;self.expected_folds=expected_folds;self.parts={}
        self.manifest=self.root/"evidence"/"compatibility.json"
        previous=json.loads(self.manifest.read_text()) if self.manifest.exists() else {}
        self.ready=(previous.get("stage_id")==stage_id and
                    all((self.root/name).exists() for name in
                        ("cell_specialist_summary.parquet","cell_temporal_summary.parquet")))
        self.writers={};self.temporary={};self.counts={"security":0,"fold":0}
        if not self.ready:
            for grouping,name,schema in (("security","cell_specialist_summary.parquet",SPECIALIST_SCHEMA),
                                         ("fold","cell_temporal_summary.parquet",TEMPORAL_SCHEMA)):
                temporary=(self.root/name).with_suffix(".partial.parquet")
                self.temporary[grouping]=temporary
                self.writers[grouping]=pq.ParquetWriter(temporary,schema,compression="zstd")

    def consume(self, grid, task, moments):
        grouping=task["grouping_id"]
        if self.ready or task["state_kind"]!="dual" or grouping not in self.writers:return
        groups=int(self.reader_manifest["grids"][grid]["groups"][grouping]["groups"])
        key=(grid,tuple(task["pair_ids"]),tuple(task["target_ids"]),task["resolution"],grouping)
        if key not in self.parts:
            shape=(len(task["target_ids"]),len(task["pair_ids"]),groups,task["resolution"]**2)
            self.parts[key]=(np.zeros(shape,np.int64),np.zeros(shape,np.float64),np.zeros(groups,bool))
        counts,sums,seen=self.parts[key]
        start,stop=task["group_start"],task["group_stop"]
        if seen[start:stop].any():raise ValueError("Duplicate compatibility group partition")
        n,s,_=moments.numpy()
        counts[:,:,start:stop]=n;sums[:,:,start:stop]=s;seen[start:stop]=True

    def finish_group(self):
        if self.ready:return
        for key,(counts,sums,seen) in self.parts.items():
            if not seen.all():raise ValueError("Incomplete compatibility group partitions")
            grid,pairs,targets,resolution,grouping=key
            schema=SPECIALIST_SCHEMA if grouping=="security" else TEMPORAL_SCHEMA
            records=[]
            for ti,target in enumerate(targets):
                reduced=(_summaries(counts[ti],sums[ti],self.minimum) if grouping=="security"
                         else _reduce(counts[ti],sums[ti],expected_folds=self.expected_folds or
                                      self.reader_manifest["grids"][grid]["groups"]["fold"]["expected_folds"]))
                records.extend({"pair_id":pair,"target_id":target,"resolution":resolution,**metrics}
                               for pair,metrics in zip(pairs,reduced))
            self.writers[grouping].write_table(pa.Table.from_pylist(records,schema=schema))
            self.counts[grouping]+=len(records)
        self.parts.clear()

    def publish(self):
        if self.ready:return
        for grouping,writer in self.writers.items():
            writer.close()
            name="cell_specialist_summary.parquet" if grouping=="security" else "cell_temporal_summary.parquet"
            os.replace(self.temporary[grouping],self.root/name)
        atomic_json(self.manifest,{"stage_id":self.stage_id,"rows":self.counts,"status":"complete"})
        self.ready=True

    def abort(self):
        for grouping,writer in self.writers.items():
            if not self.ready:
                writer.close()
                self.temporary[grouping].unlink(missing_ok=True)


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
