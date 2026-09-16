from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json,duckdb,pandas as pd

def build_production_trial_ledger(*,legacy_run,dual_path:Path,core_results:list[dict],variant_trials:pd.DataFrame|None=None,specialist_count:int=0,temporal_count:int=0,candidate_count:int=0)->Path:
    audit=json.loads((legacy_run.root/"exhaustiveness_manifest.json").read_text()); core={x["stage"]:x for x in core_results}; single_status="reused" if core["scan-singles"].get("shared_cache_reused",False) else "executed"; dual_status="reused" if core["scan-duals-coarse"].get("shared_cache_reused",False) else "executed"; now=datetime.now(timezone.utc).isoformat(); extras=[]
    unavailable=int(audit.get("unavailable_single_tests",0))
    if unavailable: extras.append({"trial_id":None,"trial_family_id":"canonical_singles","run_id":legacy_run.root.name,"trial_type":"canonical_single","status":"unavailable","reason":"target_unavailable","work_units":unavailable,"created_at_utc":now})
    mapping={"noncanonical_concept_variant":"structurally_excluded","exact_alias":"structurally_excluded","unavailable_target":"unavailable"}
    for reason,count in audit.get("dual_exclusions_by_reason",{}).items():
        if int(count): extras.append({"trial_id":None,"trial_family_id":"canonical_dual_exclusions","run_id":legacy_run.root.name,"trial_type":"canonical_dual_scope","status":mapping.get(reason,"structurally_excluded"),"reason":reason,"work_units":int(count),"created_at_utc":now})
    if specialist_count: extras.append({"trial_id":None,"trial_family_id":"cell_specialist","run_id":legacy_run.root.name,"trial_type":"all_cell_specialist","status":"executed","reason":None,"work_units":int(specialist_count),"created_at_utc":now})
    if temporal_count: extras.append({"trial_id":None,"trial_family_id":"cell_temporal","run_id":legacy_run.root.name,"trial_type":"all_cell_temporal","status":"executed","reason":None,"work_units":int(temporal_count),"created_at_utc":now})
    if candidate_count: extras.append({"trial_id":None,"trial_family_id":"dossiers","run_id":legacy_run.root.name,"trial_type":"dossier","status":"executed","reason":None,"work_units":int(candidate_count),"created_at_utc":now})
    if variant_trials is not None and len(variant_trials):
        frame=variant_trials.copy(); frame["run_id"]=legacy_run.root.name; frame["created_at_utc"]=now; extras.extend(frame.to_dict("records"))
    columns=["trial_id","trial_family_id","run_id","trial_type","feature_a_id","feature_b_id","target_id","resolution","status","reason","work_units","created_at_utc"]
    extra=pd.DataFrame(extras,columns=columns); destination=legacy_run.root/"trial_ledger.parquet"; source=str(Path(dual_path)).replace("'","''"); singles=str(legacy_run.root/"single_results"/"**"/"*.parquet").replace("'","''")
    with duckdb.connect() as con:
        con.register("extras",extra)
        extra_sql="SELECT * FROM extras" if len(extra) else "SELECT NULL::VARCHAR trial_id,NULL::VARCHAR trial_family_id,NULL::VARCHAR run_id,NULL::VARCHAR trial_type,NULL::VARCHAR feature_a_id,NULL::VARCHAR feature_b_id,NULL::VARCHAR target_id,NULL::INTEGER resolution,NULL::VARCHAR status,NULL::VARCHAR reason,NULL::BIGINT work_units,NULL::VARCHAR created_at_utc WHERE false"
        con.execute(f"""COPY (
          SELECT 'canonical_dual::'||pair_id||'::'||target_id||'::r'||v3_resolution trial_id,'canonical_dual_r'||v3_resolution trial_family_id,'{legacy_run.root.name}' run_id,'canonical_dual' trial_type,feature_a feature_a_id,feature_b feature_b_id,target_id,v3_resolution::INTEGER resolution,'{dual_status}' status,NULL::VARCHAR reason,1::BIGINT work_units,'{now}' created_at_utc FROM read_parquet('{source}')
          UNION ALL BY NAME
          SELECT 'single::'||feature_id||'::'||target_id trial_id,'canonical_singles' trial_family_id,'{legacy_run.root.name}' run_id,'canonical_single' trial_type,feature_id feature_a_id,NULL::VARCHAR feature_b_id,target_id,NULL::INTEGER resolution,'{single_status}' status,NULL::VARCHAR reason,1::BIGINT work_units,'{now}' created_at_utc FROM read_parquet('{singles}',union_by_name=true) WHERE fold_id='all'
          UNION ALL BY NAME {extra_sql}
        ) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)""",[str(destination)])
    return destination
