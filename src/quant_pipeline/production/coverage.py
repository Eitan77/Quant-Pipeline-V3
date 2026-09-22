"""Deterministic full-scope subgroup tasks with conservative storage admission."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import duckdb
import numpy as np

from .evidence_identity import atomic_json,digest,task_identity
from .segmented_task import execute_segmented_task


def preflight_comprehensive(repo_root,machine,scope,research):
    """Detect a known oversized durable sweep before launching the core."""
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
    status="blocked_storage" if dense>budget else "admitted_preliminary"
    return {"status":status,"security_only_dense_bytes_estimate":dense,"symbols":symbols,
            "free_bytes":free,"reserve_bytes":reserve,"budget_bytes":budget,
            "note":"Pre-core estimate from declared features/targets and PIT security count; actual pair aliases and compression remain unmeasured"}


def plan_storage(reader_manifest,run_root,machine,resolutions):
    """Worst-case dense bound; blocks unsafe materialization before any task runs."""
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
    return {"dense_upper_bytes":dense,"available_bytes":free,"reserve_bytes":reserve,
            "budget_bytes":budget,"status":"admitted" if dense<=budget else "blocked_storage",
            "note":"Dense uncompressed upper bound; no compression assumed", "logical_rows_upper":tasks}


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
    pair_cap=16; target_cap=2; group_cap=32
    stage_id=digest({"evidence_id":reader_manifest["evidence_id"],"resolutions":resolutions,
                     "groupings":{grid:{key:value["definition_id"] for key,value in record["groups"].items()}
                                  for grid,record in reader_manifest["grids"].items()},"schema":1})
    plan_path=root/"evidence"/"coverage_plan.jsonl"
    temporary=plan_path.with_suffix(".partial")
    plan_path.parent.mkdir(parents=True,exist_ok=True)
    counts={}; task_count=0
    with temporary.open("w",encoding="utf-8") as stream:
        for grid,record in reader_manifest["grids"].items():
            target_ids=sorted(record["targets"])
            for state_kind in ("single","dual"):
                pair_ids,definitions=_members(root,grid,record,state_kind)
                if not pair_ids: continue
                for grouping_id,grouping in record["groups"].items():
                    group_count=int(grouping["groups"])
                    scope_key=f"{grid}/{grouping_id}/{state_kind}"
                    if group_count==0:
                        counts[scope_key]={"outcome":"empty","tasks":0}
                        continue
                    for resolution in resolutions:
                        cells=resolution if state_kind=="single" else resolution**2
                        for pair_start in range(0,len(pair_ids),pair_cap):
                            subset=pair_ids[pair_start:pair_start+pair_cap]
                            for target_start in range(0,len(target_ids),target_cap):
                                targets=target_ids[target_start:target_start+target_cap]
                                groups_per=min(group_count,group_cap)
                                if 24*len(subset)*len(targets)*cells*groups_per>max_state_bytes:
                                    raise MemoryError("Stable logical tile exceeds accumulator limit")
                                for group_start in range(0,group_count,groups_per):
                                    task=task_identity(stage_id,pair_ids=subset,target_ids=targets,resolution=resolution,
                                                       grouping_id=grouping_id,group_start=group_start,
                                                       group_stop=min(group_start+groups_per,group_count),state_kind=state_kind)
                                    row={"grid":grid,"task":task,"pairs":{item:definitions[item] for item in subset}}
                                    stream.write(json.dumps(row,separators=(",",":"),sort_keys=True)+"\n")
                                    task_count+=1
                                    counts.setdefault(scope_key,{"outcome":"planned","tasks":0})["tasks"]+=1
    os.replace(temporary,plan_path)
    manifest={"stage_id":stage_id,"evidence_id":reader_manifest["evidence_id"],"task_count":task_count,
              "scope_counts":counts,"path":plan_path.relative_to(root).as_posix(),"status":"planned"}
    atomic_json(root/"evidence"/"coverage_plan.json",manifest)
    return manifest


def execute_coverage(root,reader_manifest,plan,*,device,row_chunk,max_state_bytes,cancelled=lambda:False):
    """Execute an admitted small plan, reusing exact committed logical tasks."""
    from .evidence_store import EvidenceReader
    root=Path(root)
    records_path=root/"evidence"/"coverage_records.jsonl"
    catalog={}; completed=0
    with (root/plan["path"]).open(encoding="utf-8") as stream, records_path.open("w",encoding="utf-8") as records:
        for line in stream:
            if cancelled(): raise InterruptedError("Coverage cancelled")
            row=json.loads(line); grid=row["grid"]; task=row["task"]
            reader=EvidenceReader(root,"evidence/reader.json",grid)
            result=execute_segmented_task(root=root,task=task,reader=reader,pair_definitions=row["pairs"],
                                          observation_id=reader.grid["observation_id"],row_chunk=row_chunk,
                                          max_state_bytes=max_state_bytes,device=device,cancelled=cancelled)
            record={"task_id":task["task_id"],"stage_id":task["stage_id"],"grid_id":grid,
                    "resolution":task["resolution"],"grouping_definition_id":reader.grid["groups"][task["grouping_id"]]["definition_id"],
                    "group_partition_id":f"{task['group_start']}:{task['group_stop']}",
                    "compute_status":"complete","materialization_status":"durable","artifact_ids":[result["sha256"]],
                    "rows_evaluated":reader.rows,"populated_groups":result["populated_groups"]}
            records.write(json.dumps(record,sort_keys=True)+"\n")
            table=f"{grid}_{task['grouping_id']}_{task['state_kind']}"
            catalog.setdefault(table,{"files":[]})["files"].append(result["artifact"])
            completed+=1
    atomic_json(root/"evidence"/"catalog.json",{"evidence_id":reader_manifest["evidence_id"],"tables":catalog})
    summary={"core_complete":True,"mandatory_coverage_complete":bool(plan["task_count"]) and completed==plan["task_count"],
             "materialization_complete_for_policy":True,"completed_tasks":completed,"planned_tasks":plan["task_count"]}
    atomic_json(root/"evidence"/"coverage_status.json",summary)
    return summary
