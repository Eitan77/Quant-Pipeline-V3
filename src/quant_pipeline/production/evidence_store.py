from __future__ import annotations

from collections import OrderedDict
import json
import os
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

from .evidence_identity import inside,atomic_json,digest,file_digest
from .segmented_scan import encode_groups

DEFAULT_GROUPINGS=(("security",),("month",),("fold",),("time_bucket",),
                   ("security","time_bucket"),("security","month"))


def build_groupings(root, grid, observations, observation_id, definitions=DEFAULT_GROUPINGS, folds=5,
                    condition_definitions=(), bin_refs=None):
    """Encode requested complete-grid groups once, with durable dictionaries."""
    root=Path(root)
    frame=pd.DataFrame(index=observations.index)
    frame["security"]=observations.security_id.astype(str)
    sessions=pd.to_datetime(observations.session_date)
    frame["month"]=sessions.dt.strftime("%Y-%m")
    ordered=np.sort(sessions.dt.normalize().unique())
    fold_lookup={session:index for index,part in enumerate(np.array_split(ordered,folds)) for session in part}
    frame["fold"]=sessions.dt.normalize().map(fold_lookup).astype("Int64")
    import exchange_calendars as xcals
    calendar=xcals.get_calendar("XNYS")
    trading_sessions=calendar.sessions_in_range(str(sessions.min().date()),str(sessions.max().date()))
    open_minute={pd.Timestamp(day).date():calendar.session_open(day).tz_convert("America/New_York").hour*60+
                 calendar.session_open(day).tz_convert("America/New_York").minute for day in trading_sessions}
    close_minute={pd.Timestamp(day).date():calendar.session_close(day).tz_convert("America/New_York").hour*60+
                  calendar.session_close(day).tz_convert("America/New_York").minute for day in trading_sessions}
    times=pd.to_datetime(observations.decision_ts,utc=True).dt.tz_convert("America/New_York")
    clock=times.dt.hour*60+times.dt.minute
    session_days=sessions.dt.date
    opening=session_days.map(open_minute)
    closing=session_days.map(close_minute)
    valid_session=opening.notna() & closing.notna() & (clock>=opening) & (clock<=closing)
    buckets=np.select([clock>=closing-60,clock<630,clock<720,clock<840],
                      ["close","open","morning","midday"],default="afternoon")
    frame["time_bucket"]=pd.Series(buckets,index=frame.index,dtype="string").where(valid_session,pd.NA)
    unavailable=set()
    for definition in condition_definitions:
        name=definition["id"]
        if definition["source"]=="decision_minute":
            values=clock.to_numpy(dtype=float)
        else:
            reference=(bin_refs or {}).get(definition["feature_id"])
            if reference is None:
                unavailable.add(name)
                frame[name]=pd.Series(pd.NA,index=frame.index,dtype="string")
                continue
            packed=np.load(root/reference["path"],mmap_mode="r",allow_pickle=False)[:,reference["column"]]
            values=np.where(packed==255,np.nan,packed//15).astype(float)
        cuts=np.asarray(definition["cutpoints"],dtype=float)
        codes=np.searchsorted(cuts,values,side="right")
        labels=np.asarray(definition["labels"],dtype=object)
        result_values=pd.Series(labels[np.minimum(codes,len(labels)-1)],index=frame.index,dtype="string")
        if definition.get("missing","unavailable")=="category":
            result_values.loc[~np.isfinite(values)]="missing"
        else:
            result_values.loc[~np.isfinite(values)]=pd.NA
        frame[name]=result_values
    result={}
    for columns in definitions:
        columns=tuple(columns)
        if not columns or any(column not in frame for column in columns): raise ValueError(f"Unsupported grouping: {columns}")
        grouping_id="_".join(columns)
        codes,labels=encode_groups(frame,list(columns))
        group_dir=root/"evidence"/"groups"/grid
        group_dir.mkdir(parents=True,exist_ok=True)
        path=group_dir/f"{grouping_id}.npy"; pending=path.with_suffix(".tmp.npy")
        np.save(pending,codes,allow_pickle=False); os.replace(pending,path)
        labels_path=group_dir/f"{grouping_id}.parquet"; labels.to_parquet(labels_path,index=False)
        relevant=[item for item in condition_definitions if item["id"] in columns]
        definition_id=digest({"columns":columns,"observation_id":observation_id,"folds":folds,
                              "time_bucket_version":2,"conditions":relevant,"missing":"excluded"})
        result[grouping_id]={"path":path.relative_to(root).as_posix(),"shape":list(codes.shape),
                             "dtype":str(codes.dtype),"observation_id":observation_id,
                             "definition_id":definition_id,"labels":labels_path.relative_to(root).as_posix(),
                             "groups":len(labels),"availability":"unavailable" if set(columns)&unavailable else "available",
                             "expected_folds":folds if "fold" in columns else None,
                             "missing_folds":sorted(set(range(folds))-set(frame["fold"].dropna().astype(int))) if "fold" in columns else []}
    return result


def publish_evidence(legacy_run,resolved_scope,committed_inputs,research):
    """Import only arrays with verified observation lineage into a portable local manifest."""
    root=Path(legacy_run.root)
    grids={}
    active_features={item["id"]:item for item in resolved_scope["features"]}
    active_targets={item["id"]:item for item in resolved_scope["targets"]}
    evidence=research.get("evidence",{})
    definitions=list(evidence.get("mandatory_groupings",DEFAULT_GROUPINGS))+list(evidence.get("condition_groupings",[]))
    for grid in resolved_scope["grids"]:
        obs_path=root/"cache"/"features"/grid/"observations.parquet"
        observations=pd.read_parquet(obs_path,columns=["observation_id","security_id","session_date","decision_ts"])
        ids=observations.observation_id.to_numpy(np.int64)
        observation_id=file_digest(obs_path)
        ordered_ids_hash=sha256(ids.tobytes()).hexdigest()
        if len(ids)==0 or not np.array_equal(ids,np.arange(len(ids),dtype=np.int64)):
            raise ValueError(f"Noncanonical observation order: {grid}")
        target_path=root/"cache"/"target_store"/grid/"aligned.npy"
        if not target_path.exists():
            from quant_pipeline.alpha_discovery.cache.target_store import TargetStore
            store=TargetStore(root/"cache"/"target_store"/grid)
            legacy_run._build_aligned_target_store(grid,observations,store)
        target_meta=json.loads(target_path.with_suffix(".json").read_text(encoding="utf-8"))
        target_obs=np.load(target_path.with_name("aligned.observations.npy"),mmap_mode="r",allow_pickle=False)
        if not np.array_equal(ids,target_obs): raise ValueError(f"Target observation mismatch: {grid}")
        if file_digest(target_path)!=target_meta["sha256"]: raise ValueError(f"Target checksum mismatch: {grid}")
        target_array=np.load(target_path,mmap_mode="r",allow_pickle=False)
        target_refs={}
        for column,target_id in enumerate(target_meta["columns"]):
            if target_id not in active_targets: continue
            if active_targets[target_id]["grid"]!=grid: raise ValueError("Target grid mismatch")
            target_refs[target_id]={"path":target_path.relative_to(root).as_posix(),"column":column,
                                    "shape":list(target_array.shape),"dtype":str(target_array.dtype),
                                    "observation_id":observation_id,"definition_hash":active_targets[target_id]["definition_hash"]}
        if not target_refs: raise ValueError(f"No targets in evidence grid {grid}")
        bin_refs={}
        for meta_path in sorted((root/"cache"/"bins"/"packed"/grid).glob("*.json")):
            meta=json.loads(meta_path.read_text(encoding="utf-8"))
            selected=[(column,item) for column,item in enumerate(meta["columns"]) if item in active_features]
            if not selected: continue
            if meta.get("observation_id_sha256")!=ordered_ids_hash or meta.get("observations_sha256")!=observation_id:
                raise ValueError(f"Unverified packed-bin observation lineage: {meta_path}")
            path=meta_path.with_suffix(".npy")
            if file_digest(path)!=meta["sha256"]: raise ValueError(f"Packed-bin checksum mismatch: {path}")
            array=np.load(path,mmap_mode="r",allow_pickle=False)
            if list(array.shape)!=meta["shape"] or len(array)!=len(ids): raise ValueError(f"Packed-bin shape mismatch: {path}")
            for column,feature_id in selected:
                if meta.get("feature_definition_hashes",{}).get(feature_id)!=active_features[feature_id]["definition_hash"]:
                    raise ValueError(f"Packed-bin definition mismatch: {feature_id}")
                if feature_id in bin_refs: raise ValueError(f"Duplicate packed feature: {feature_id}")
                bin_refs[feature_id]={"path":path.relative_to(root).as_posix(),"column":column,
                                      "shape":list(array.shape),"dtype":str(array.dtype),
                                      "observation_id":observation_id,"definition_hash":active_features[feature_id]["definition_hash"]}
        required={item for item,record in active_features.items() if record["grid"]==grid}
        if set(bin_refs)!=required: raise ValueError(f"Missing verified packed bins for {grid}: {sorted(required-set(bin_refs))[:5]}")
        group_refs=build_groupings(root,grid,observations,observation_id,definitions,
                                   folds=int(legacy_run.config.stability["chronological_folds"]),
                                   condition_definitions=evidence.get("condition_definitions",[]),bin_refs=bin_refs)
        grids[grid]={"rows":len(ids),"observation_id":observation_id,"observations":obs_path.relative_to(root).as_posix(),
                     "bins":bin_refs,"targets":target_refs,"groups":group_refs,
                     "source_stage_ids":committed_inputs}
    manifest={"schema_version":1,"grids":grids,"scope":resolved_scope,"committed_inputs":committed_inputs}
    manifest["evidence_id"]=digest(manifest)
    path=root/"evidence"/"reader.json"; atomic_json(path,manifest)
    return path


class ByteLRU:
    """Bound owned cached arrays, not all process memory or caller-held references."""

    def __init__(self, max_bytes):
        if max_bytes < 0:
            raise ValueError("Negative cache budget")
        self.max_bytes, self.used, self.items = int(max_bytes), 0, OrderedDict()

    def get_or_load(self, key, loader):
        if key in self.items:
            self.items.move_to_end(key)
            return self.items[key]
        value = loader()
        size = int(value.nbytes)
        while self.items and self.used + size > self.max_bytes:
            _, old = self.items.popitem(last=False)
            self.used -= int(old.nbytes)
        if size <= self.max_bytes:
            self.items[key] = value
            self.used += size
        return value


class EvidenceReader:
    """Read an imported, verified immutable grid; never call legacy initialization."""

    def __init__(self, root, manifest_path, grid_id, max_open_arrays=16):
        if max_open_arrays < 1:
            raise ValueError("max_open_arrays must be positive")
        self.root = root
        self.manifest = json.loads(inside(root, manifest_path).read_text(encoding="utf-8"))
        self.grid = self.manifest["grids"][grid_id]
        self.rows = int(self.grid["rows"])
        self.limit, self.arrays = max_open_arrays, OrderedDict()

    def _array(self, reference):
        if reference["observation_id"] != self.grid["observation_id"]:
            raise ValueError("Array belongs to a different observation order")
        path = str(inside(self.root, reference["path"]))
        if path not in self.arrays:
            self.arrays[path] = np.load(path, mmap_mode="r", allow_pickle=False)
        array = self.arrays[path]
        self.arrays.move_to_end(path)
        if (list(array.shape) != reference["shape"] or str(array.dtype) != reference["dtype"]
                or len(array) != self.rows):
            raise ValueError("Manifest/array mismatch")
        while len(self.arrays) > self.limit:
            self.arrays.popitem(last=False)
        return array

    def read_columns(self, kind, ids, start, stop, indices=None):
        if not 0 <= start <= stop <= self.rows or not ids:
            raise ValueError("Invalid read range or empty column request")
        result = []
        for key in ids:
            ref = self.grid[kind][key]
            array = self._array(ref)
            if array.ndim != 2 or not 0 <= ref["column"] < array.shape[1]:
                raise ValueError("Invalid column mapping")
            values = array[start:stop, ref["column"]]
            result.append(values if indices is None else values[indices])
        return np.column_stack(result)

    def read_groups(self, grouping_id, start, stop):
        if not 0 <= start <= stop <= self.rows:
            raise ValueError("Invalid read range")
        array = self._array(self.grid["groups"][grouping_id])
        if array.ndim != 1 or not np.issubdtype(array.dtype, np.signedinteger):
            raise ValueError("Group array must be signed integer codes")
        return array[start:stop]
