from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json,pandas as pd

def build_production_trial_ledger(*,legacy_run,duals:pd.DataFrame,core_results:list[dict],variant_trials:pd.DataFrame|None=None,specialist_count:int=0,candidate_count:int=0)->Path:
    now=datetime.now(timezone.utc); rows=[]; audit_path=legacy_run.root/"exhaustiveness_manifest.json"; audit=json.loads(audit_path.read_text()) if audit_path.exists() else {}; core={x["stage"]:x for x in core_results}; single_status="reused" if core["scan-singles"].get("shared_cache_reused",False) else "executed"; dual_status="reused" if core["scan-duals-coarse"].get("shared_cache_reused",False) else "executed"
    for row in duals.to_dict("records"): rows.append({"trial_id":f"canonical_dual::{row['pair_id']}::{row['target_id']}::r{int(row['v3_resolution'])}","trial_family_id":f"canonical_dual_r{int(row['v3_resolution'])}","run_id":legacy_run.root.name,"trial_type":"canonical_dual","feature_a_id":row["feature_a"],"feature_b_id":row["feature_b"],"target_id":row["target_id"],"resolution":int(row["v3_resolution"]),"variant_definition":None,"status":dual_status,"artifact_hash":None,"reason":None,"created_at_utc":now,"work_units":1})
    for path in (legacy_run.root/"single_results").rglob("*.parquet"):
        frame=pd.read_parquet(path); frame=frame[frame.fold_id.eq("all")] if "fold_id" in frame else frame
        for row in frame.to_dict("records"): rows.append({"trial_id":f"single::{row['feature_id']}::{row['target_id']}","trial_family_id":"canonical_singles","run_id":legacy_run.root.name,"trial_type":"canonical_single","feature_a_id":row["feature_id"],"feature_b_id":None,"target_id":row["target_id"],"resolution":None,"variant_definition":None,"status":single_status,"artifact_hash":None,"reason":None,"created_at_utc":now,"work_units":1})
    unavailable_singles=int(audit.get("unavailable_single_tests",0))
    if unavailable_singles: rows.append({"trial_id":"single::unavailable","trial_family_id":"canonical_singles","run_id":legacy_run.root.name,"trial_type":"canonical_single","status":"unavailable","reason":"target_unavailable","created_at_utc":now,"work_units":unavailable_singles})
    mapping={"noncanonical_concept_variant":"structurally_excluded","exact_alias":"structurally_excluded","realized_exact_alias":"structurally_excluded","unavailable_target":"unavailable"}
    for reason,count in audit.get("dual_exclusions_by_reason",{}).items():
        if int(count): rows.append({"trial_id":None,"trial_family_id":"canonical_dual_exclusions","run_id":legacy_run.root.name,"trial_type":"canonical_dual_scope","status":mapping.get(reason,"structurally_excluded"),"reason":reason,"created_at_utc":now,"work_units":int(count)})
    for i in range(specialist_count): rows.append({"trial_id":f"specialist::{i}","trial_family_id":"specialist_followup","run_id":legacy_run.root.name,"trial_type":"specialist","status":"executed","created_at_utc":now,"work_units":1})
    for i in range(candidate_count): rows.append({"trial_id":f"dossier::{i}","trial_family_id":"dossiers","run_id":legacy_run.root.name,"trial_type":"dossier","status":"executed","created_at_utc":now,"work_units":1})
    frame=pd.DataFrame(rows)
    if variant_trials is not None and len(variant_trials):
        variants=variant_trials.copy(); variants["run_id"]=legacy_run.root.name; variants["created_at_utc"]=now; frame=pd.concat([frame,variants],ignore_index=True,sort=False)
    allowed={"executed","reused","structurally_excluded","unavailable","failed"}
    if not set(frame.status)<=allowed: raise RuntimeError("Invalid production trial status")
    destination=legacy_run.root/"trial_ledger.parquet"; frame.to_parquet(destination,index=False); return destination
