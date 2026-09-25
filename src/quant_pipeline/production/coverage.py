"""Deterministic full-scope subgroup tasks with conservative storage admission."""
from __future__ import annotations

import json
import os
import shutil
import time
from itertools import groupby
from pathlib import Path

import duckdb
import numpy as np
import psutil

from .evidence_identity import atomic_json,digest,task_identity
from .segmented_task import execute_segmented_batch,execute_segmented_task
from .evidence_cache import EvidenceCache
from .evidence_artifacts import load_tile
from .evidence_reducer import consume_block
from .compatibility_moments import CompatibilitySink


def preflight_comprehensive(repo_root,machine,scope,research):
    """Record the dense bound; streamed coverage only needs a bounded cache."""
    root=Path(machine["run_root"]); root.mkdir(parents=True,exist_ok=True)
    free=shutil.disk_usage(root).free
    reserve=max(40*(1<<30),int(free*.25))
    budget=int(machine.get("evidence_disk_budget_gb",max(0,(free-reserve)*.5)/(1<<30))*(1<<30))
    definitions=research.get("evidence",{}).get("mandatory_groupings",[])
    if ["security"] not in definitions and ("security",) not in definitions:
        return {"status":"needs_post_core_measurement","free_bytes":free,"budget_bytes":budget}
    membership=Path(repo_root)/"reference"/"sp500_pit_membership_daily.parquet"
    with duckdb.connect() as con:
        symbols=int(con.execute("SELECT count(DISTINCT security_id) FROM read_parquet(?) WHERE in_universe AND session_date BETWEEN ? AND ?",
                                [str(membership),scope["discovery"]["start"],scope["discovery"]["end"]]).fetchone()[0])
    dense=0
    for grid in scope["grids"]:
        features=sum(item["grid"]==grid for item in scope["features"])
        targets=sum(item["grid"]==grid for item in scope["targets"])
        pairs=features*(features-1)//2
        dense+=24*symbols*targets*sum(pairs*r*r+features*r for r in research["resolutions"])
    # Alias exclusions and compression are unknown before core output exists.
    status="admitted_streaming" if budget>0 else "blocked_storage"
    return {"status":status,"security_only_dense_bytes_estimate":dense,"symbols":symbols,
            "free_bytes":free,"reserve_bytes":reserve,"budget_bytes":budget,
            "note":"Dense bytes are a nonmaterialized upper bound. Sampled compression and pinned input sizes are checked after core publication."}


def plan_storage(reader_manifest,run_root,machine,resolutions):
    """Budget pinned inputs and a bounded cache; report the dense bound separately."""
    root=Path(run_root)
    free=shutil.disk_usage(root).free
    reserve=max(40*(1<<30),int(free*.25))
    derived=max(0,int((free-reserve)*.5))
    budget=int(machine.get("evidence_disk_budget_gb",derived/(1<<30))*(1<<30))
    dense=0; tasks=0
    for grid,record in reader_manifest["grids"].items():
        plan=np.load(root/"cache"/"pair_plans"/f"{grid}.npz",allow_pickle=False)
        pairs=len(plan["pair_ids"]); singles=len(record["bins"]); targets=len(record["targets"])
        for grouping in record["groups"].values():
            groups=grouping["groups"]
            for resolution in resolutions:
                dense+=24*targets*groups*(pairs*resolution**2+singles*resolution)
                tasks+=pairs*targets*max(groups,1)
    pinned=sum(Path(root/item["path"]).stat().st_size for record in reader_manifest["grids"].values()
               for family in ("bins","targets") for item in record[family].values())
    pinned+=sum(Path(root/group["path"]).stat().st_size for record in reader_manifest["grids"].values()
                for group in record["groups"].values())
    cache=max(0,min(budget//2,free-reserve))
    return {"dense_upper_bytes":dense,"available_bytes":free,"reserve_bytes":reserve,
            "budget_bytes":budget,"pinned_input_bytes":pinned,"cache_bytes":cache,
            "status":"admitted_streaming" if cache>0 else "blocked_storage",
            "note":"Dense upper bound is not permanent storage. Exact compressed density is sampled from completed tiles.",
            "logical_rows_upper":tasks}


def _members(root,grid,reader_grid,state_kind):
    if state_kind=="single":
        ids=sorted(reader_grid["bins"])
        return ids,{item:(item,) for item in ids}
    plan=np.load(Path(root)/"cache"/"pair_plans"/f"{grid}.npz",allow_pickle=False)
    features=plan["feature_ids"].tolist()
    pair_ids=plan["pair_ids"].tolist()
    definitions={pair_id:(features[int(left)],features[int(right)]) for pair_id,left,right in zip(pair_ids,plan["left"],plan["right"])}
    if len(definitions)!=len(pair_ids): raise ValueError("Duplicate pair IDs")
    if any(feature not in reader_grid["bins"] for pair in definitions.values() for feature in pair):
        raise ValueError("Pair plan references unverified feature bins")
    return pair_ids,definitions


def plan_coverage(root,reader_manifest,resolutions,*,max_state_bytes=512*(1<<20)):
    """Persist exact logical membership independently of global promotion."""
    root=Path(root)
    # Larger logical tiles avoid rereading the full observation stream for
    # millions of tiny pair/target/group partitions. The largest r10 tile is
    # 24 * 64 * 4 * 256 * 100 = 150 MiB, within the 512 MiB state budget.
    pair_cap=64; target_cap=4; group_cap=256
    stage_id=digest({"evidence_id":reader_manifest["evidence_id"],"resolutions":resolutions,
                     "groupings":{grid:{key:value["definition_id"] for key,value in record["groups"].items()}
                                  for grid,record in reader_manifest["grids"].items()},
                     "tile_policy":{"pairs":pair_cap,"targets":target_cap,"groups":group_cap},"schema":4})
    plan_path=root/"evidence"/"coverage_plan.jsonl"
    manifest_path=root/"evidence"/"coverage_plan.json"
    if manifest_path.exists() and plan_path.exists():
        previous=json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("stage_id")==stage_id and previous.get("task_count",0)>0:
            return previous
    temporary=plan_path.with_suffix(".partial")
    plan_path.parent.mkdir(parents=True,exist_ok=True)
    counts={}; resolution_counts={}; task_count=0
    with temporary.open("w",encoding="utf-8") as stream:
        for grid,record in reader_manifest["grids"].items():
            target_ids=sorted(record["targets"])
            for state_kind in ("single","dual"):
                pair_ids,definitions=_members(root,grid,record,state_kind)
                if not pair_ids: continue
                for pair_start in range(0,len(pair_ids),pair_cap):
                    subset=pair_ids[pair_start:pair_start+pair_cap]
                    for target_start in range(0,len(target_ids),target_cap):
                        targets=target_ids[target_start:target_start+target_cap]
                        for grouping_id,grouping in record["groups"].items():
                            group_count=int(grouping["groups"])
                            scope_key=f"{grid}/{grouping_id}/{state_kind}"
                            if group_count==0:
                                counts[scope_key]={"outcome":grouping.get("availability","empty") if grouping.get("availability")=="unavailable" else "empty","tasks":0}
                                continue
                            groups_per=min(group_count,group_cap)
                            for group_start in range(0,group_count,groups_per):
                                for resolution in resolutions:
                                    cells=resolution if state_kind=="single" else resolution**2
                                    if 24*len(subset)*len(targets)*groups_per*cells>max_state_bytes:
                                        raise MemoryError("Logical group partition exceeds live resource admission")
                                    task=task_identity(stage_id,pair_ids=subset,target_ids=targets,resolution=resolution,
                                                       grouping_id=grouping_id,group_start=group_start,
                                                       group_stop=min(group_start+groups_per,group_count),state_kind=state_kind)
                                    row={"grid":grid,"task":task,"pairs":{item:definitions[item] for item in subset}}
                                    stream.write(json.dumps(row,separators=(",",":"),sort_keys=True)+"\n")
                                    task_count+=1
                                    counts.setdefault(scope_key,{"outcome":"planned","tasks":0})["tasks"]+=1
                                    sample_key=f"{grid}/{grouping_id}/{state_kind}/{resolution}"
                                    resolution_counts[sample_key]=resolution_counts.get(sample_key,0)+1
    os.replace(temporary,plan_path)
    manifest={"stage_id":stage_id,"evidence_id":reader_manifest["evidence_id"],"task_count":task_count,
              "scope_counts":counts,"resolution_task_counts":resolution_counts,
              "path":plan_path.relative_to(root).as_posix(),"status":"planned"}
    atomic_json(manifest_path,manifest)
    return manifest


def sample_storage(root,reader_manifest,plan,storage,*,device,row_chunk,max_state_bytes,cancelled=lambda:False):
    """Measure actual compressed density on bounded, dispersed core tiles."""
    from .evidence_store import EvidenceReader
    root=Path(root)
    selected={}
    with (root/plan["path"]).open(encoding="utf-8") as stream:
        for line in stream:
            row=json.loads(line);task=row["task"]
            key=(row["grid"],task["grouping_id"],task["resolution"],task["state_kind"])
            # Deterministic spread over pair/group identities, independent of run order.
            score=digest({"task":task["task_id"],"sample_schema":1})
            if key not in selected or score<selected[key][0]:selected[key]=(score,row)
    readers={};samples=[]
    for _,row in sorted(selected.values()):
        started=time.perf_counter()
        if cancelled():raise InterruptedError("Storage sampling cancelled")
        grid=row["grid"];task=row["task"]
        reader=readers.setdefault(grid,EvidenceReader(root,"evidence/reader.json",grid))
        result=execute_segmented_task(root=root,task=task,reader=reader,pair_definitions=row["pairs"],
            observation_id=reader.grid["observation_id"],row_chunk=row_chunk,
            max_state_bytes=max_state_bytes,device=device,cancelled=cancelled)
        possible=len(task["pair_ids"])*len(task["target_ids"])*(task["group_stop"]-task["group_start"])
        dense=24*possible*(task["resolution"] if task["state_kind"]=="single" else task["resolution"]**2)
        samples.append({"task_id":task["task_id"],"grid":grid,"grouping":task["grouping_id"],
                        "resolution":task["resolution"],"state_kind":task["state_kind"],
                        "possible_group_rows":possible,"populated_group_rows":result["populated_groups"],
                        "dense_bytes":dense,"compressed_bytes":result["bytes"],
                        "elapsed_seconds":time.perf_counter()-started,
                        "estimated_input_bytes":reader.rows*(len({feature for pair in row["pairs"].values() for feature in pair})+8*len(task["target_ids"])+8)})
    storage["representative_tiles"]=samples
    storage["sampled_density"]=sum(x["populated_group_rows"] for x in samples)/max(1,sum(x["possible_group_rows"] for x in samples))
    storage["sampled_compression_ratio"]=sum(x["compressed_bytes"] for x in samples)/max(1,sum(x["dense_bytes"] for x in samples))
    storage["sampled_input_bytes_per_second"]=sum(x["estimated_input_bytes"] for x in samples)/max(1e-9,sum(x["elapsed_seconds"] for x in samples))
    storage["temporary_bytes_required"]=max((x["compressed_bytes"] for x in samples),default=0)*2
    atomic_json(root/"evidence"/"storage_plan.json",storage)
    return storage


def execute_coverage(root,reader_manifest,plan,*,device,row_chunk,max_state_bytes,cancelled=lambda:False,
                     cache_bytes=None,compatibility_minimum=20,expected_folds=None,
                     compatibility_workers=1, fused_cuda=False, resident_inputs=False):
    """Resume and stream all declared tasks through a bounded recomputable cache."""
    from .evidence_store import EvidenceReader
    root=Path(root)
    cache=EvidenceCache(root)
    completed_task_ids=cache.completed_task_ids(plan["stage_id"])
    sink=CompatibilitySink(root,reader_manifest,plan["stage_id"],
                           minimum=compatibility_minimum,expected_folds=expected_folds,
                           workers=compatibility_workers,device=device)
    storage_path=root/"evidence"/"storage_plan.json"
    storage=json.loads(storage_path.read_text()) if storage_path.exists() else {}
    budget=storage.get("cache_bytes",2*(1<<30)) if cache_bytes is None else cache_bytes
    if budget < 1: raise ValueError("A positive recomputable cache budget is required")
    samples=storage.setdefault("samples",{})
    readers={}
    resident_grid=None
    resident_grid_id=None
    started=time.perf_counter()
    metrics={"tasks_processed":0,"bytes_written":0,"estimated_input_bytes_read":0,"peak_process_rss_bytes":0,
             "peak_cuda_allocated_bytes":0}
    process=psutil.Process()
    batches=0
    unavailable=[key for key,value in plan["scope_counts"].items() if value["outcome"]=="unavailable"]
    def coverage_status():
        current=cache.status(plan["task_count"],plan["stage_id"])
        current["unavailable_groupings"]=unavailable
        if unavailable:
            current["mandatory_coverage_complete"]=False
            current["status"]="unavailable"
        return current
    if cache.stored_bytes(plan["stage_id"])>budget:
        cache.evict_to_budget(budget,reader_manifest["evidence_id"],plan["stage_id"])
        if cache.stored_bytes(plan["stage_id"])>budget:
            raise RuntimeError("Active query pins prevent bounded coverage cache eviction")
    def key(row):
        task=row["task"]
        return (row["grid"],task["state_kind"],tuple(task["pair_ids"]),tuple(task["target_ids"]))
    try:
        with (root/plan["path"]).open(encoding="utf-8") as stream:
            rows=(json.loads(line) for line in stream)
            for group_key, grouped in groupby(rows,key):
                grouped=list(grouped)
                grid=group_key[0]
                if grid not in readers:
                    readers[grid]=EvidenceReader(root,"evidence/reader.json",grid)
                reader=readers[grid]
                batch=[]; live_bytes=0
                replay=[]
                def flush():
                    nonlocal batch,live_bytes,batches,resident_grid,resident_grid_id
                    if not batch:return
                    if fused_cuda and resident_inputs and device!="cpu" and resident_grid_id!=grid:
                        import torch
                        from .segmented_cuda import ResidentEvidenceGrid
                        resident_grid=None
                        torch.cuda.empty_cache()
                        try:
                            resident_grid=ResidentEvidenceGrid(reader,device,
                                reserve_bytes=max_state_bytes+512*(1<<20),row_chunk=row_chunk,cancelled=cancelled)
                        except MemoryError:
                            # The fused streaming path preserves bounded operation
                            # on machines whose verified grid cannot fit on device.
                            resident_grid=None
                        resident_grid_id=grid
                        metrics["resident_input_bytes"]=0 if resident_grid is None else resident_grid.bytes
                        metrics["cuda_backend"]="fused_resident" if resident_grid is not None else "fused_streaming"
                    reduced_in_batch=set()
                    def reduce_task(task,moments,metadata):
                        if task["task_id"] not in completed_task_ids:
                            consume_block({"journal":root/"evidence"/"sweep_summary.jsonl"},moments,
                                          {"task":task,"rows_evaluated":metadata["rows_evaluated"]})
                        sink.consume(grid,task,moments)
                        reduced_in_batch.add(task["task_id"])
                    results=execute_segmented_batch(root=root,rows=batch,reader=reader,row_chunk=row_chunk,
                          max_state_bytes=max_state_bytes,device=device,cancelled=cancelled,
                          consume_block=reduce_task,materialize=False,fused_cuda=fused_cuda,
                          resident_grid=resident_grid)
                    if resident_grid is not None:
                        metrics["joint_bin_codes"]=len(resident_grid.joint_codes)
                        metrics["joint_resolution_batches"]=resident_grid.joint_batches
                    for row,result in zip(batch,results):
                        task=row["task"]
                        if task["task_id"] not in completed_task_ids and task["task_id"] not in reduced_in_batch:
                            moments=load_tile(root,task)
                            consume_block({"journal":root/"evidence"/"sweep_summary.jsonl"},moments,
                                          {"task":task,"rows_evaluated":reader.rows})
                            sink.consume(grid,task,moments)

                        if task["task_id"] not in completed_task_ids:
                            cache.record(grid,task,result,reader.rows)
                            completed_task_ids.add(task["task_id"])
                        metrics["tasks_processed"]+=1
                        metrics["bytes_written"]+=result["bytes"]
                        metrics["estimated_input_bytes_read"]+=reader.rows*(len({feature for pair in row["pairs"].values() for feature in pair})+8*len(task["target_ids"])+8)
                        sample_key=f"{grid}/{task['grouping_id']}/{task['state_kind']}/{task['resolution']}"
                        sample=samples.setdefault(sample_key,{"tiles":0,"populated_groups":0,"possible_groups":0,"compressed_bytes":0})
                        if sample["tiles"]<3:
                            sample["tiles"]+=1;sample["compressed_bytes"]+=result["bytes"]
                            sample["populated_groups"]+=result["populated_groups"]
                            sample["possible_groups"]+=len(task["pair_ids"])*len(task["target_ids"])*(task["group_stop"]-task["group_start"])
                    metrics["peak_process_rss_bytes"]=max(metrics["peak_process_rss_bytes"],process.memory_info().rss)
                    if device!="cpu":
                        import torch
                        metrics["peak_cuda_allocated_bytes"]=max(metrics["peak_cuda_allocated_bytes"],torch.cuda.max_memory_allocated(device))
                    batches+=1
                    if batches%32==0:
                        cache.evict_to_budget(budget,reader_manifest["evidence_id"],plan["stage_id"])
                        if cache.stored_bytes(plan["stage_id"])>budget:
                            blocked=coverage_status()
                            blocked.update(status="blocked_storage",mandatory_coverage_complete=False,
                                           reason="Active query snapshot pins prevent cache eviction",
                                           stored_bytes=cache.stored_bytes(plan["stage_id"]),cache_budget_bytes=budget)
                            atomic_json(root/"evidence"/"coverage_status.json",blocked)
                            raise RuntimeError("Active query pins prevent bounded coverage cache eviction")
                        cache.publish_catalog(reader_manifest["evidence_id"],plan["stage_id"])
                        storage["sampled_density"]={key:value["populated_groups"]/value["possible_groups"] if value["possible_groups"] else 0 for key,value in samples.items()}
                        storage["projected_compressed_bytes"]={key:int(value["compressed_bytes"]/value["tiles"]*plan["resolution_task_counts"][key]) for key,value in samples.items() if value["tiles"]}
                        atomic_json(storage_path,storage)
                        atomic_json(root/"evidence"/"coverage_resource_metrics.json",{**metrics,"elapsed_seconds":time.perf_counter()-started})
                        atomic_json(root/"evidence"/"coverage_status.json",coverage_status())
                    batch=[];live_bytes=0
                for row in grouped:
                    if cancelled(): raise InterruptedError("Coverage cancelled")
                    task=row["task"]
                    task_id=task["task_id"]
                    if task_id in completed_task_ids:
                        if not sink.has_group(group_key) and task["state_kind"]=="dual" and task["grouping_id"] in {"security","fold"}:
                            replay.append(row)
                        continue
                    cells=task["resolution"] if task["state_kind"]=="single" else task["resolution"]**2
                    need=16*len(task["pair_ids"])*len(task["target_ids"])*(task["group_stop"]-task["group_start"])*cells
                    if batch and live_bytes+need>max_state_bytes*9//10:flush()
                    batch.append(row);live_bytes+=need
                for row in sink.consume_existing(grid,replay):
                    task=row["task"]
                    cells=task["resolution"]**2
                    need=16*len(task["pair_ids"])*len(task["target_ids"])*(task["group_stop"]-task["group_start"])*cells
                    if batch and live_bytes+need>max_state_bytes*9//10:flush()
                    batch.append(row);live_bytes+=need
                flush()
                sink.finish_group(group_key)
        cache.evict_to_budget(budget,reader_manifest["evidence_id"],plan["stage_id"])
        sink.publish()
        summary=coverage_status()
        cache.publish_catalog(reader_manifest["evidence_id"],plan["stage_id"])
        storage["sampled_density"]={key:value["populated_groups"]/value["possible_groups"] if value["possible_groups"] else 0
                                     for key,value in samples.items()}
        storage["elapsed_seconds"]=time.perf_counter()-started
        atomic_json(storage_path,storage)
        atomic_json(root/"evidence"/"coverage_resource_metrics.json",{**metrics,"elapsed_seconds":time.perf_counter()-started})
        atomic_json(root/"evidence"/"coverage_status.json",summary)
        return summary
    finally:
        sink.abort()
        cache.close()
