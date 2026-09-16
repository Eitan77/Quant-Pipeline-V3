from __future__ import annotations
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np,pandas as pd
from quant_pipeline.candidates import make_candidate

def materialization_pool(duals:pd.DataFrame,*,min_active_n:int,min_abs_edge_bps:float,top_k:int)->pd.DataFrame:
    frame=duals.copy(); frame=frame[frame.selected_n.ge(min_active_n)].copy(); frame["abs_state_edge_bps"]=frame.selected_state_bps.abs(); frame["abs_interaction_bps"]=frame.selected_interaction_lift_bps.abs(); eligible=frame[(frame.abs_state_edge_bps.ge(min_abs_edge_bps))|(frame.abs_interaction_bps.ge(min_abs_edge_bps))].copy(); eligible["materialization_score"]=np.maximum(eligible.abs_state_edge_bps,eligible.abs_interaction_bps)
    return eligible.sort_values(["target_id","v3_resolution","materialization_score"],ascending=[True,True,False]).groupby(["target_id","v3_resolution"],group_keys=False).head(top_k)

def materialize_candidates(*,legacy_run,duals:pd.DataFrame,specialist:pd.DataFrame,research:dict,source_manifest_hash:str):
    policy=research.get("forensics",{}).get("candidate_policy",{}); pool=materialization_pool(duals,min_active_n=int(policy.get("min_active_n",250)),min_abs_edge_bps=float(policy.get("min_abs_edge_bps",1.0)),top_k=int(policy.get("keep_top_k_per_target_resolution",250))); bundle=legacy_run.compile_registry(); features={x.feature_id:x for x in bundle.features}; targets={x.target_id:x for x in bundle.targets}; specialist_by={(x.pair_id,x.target_id,int(x.resolution)):x for x in specialist.itertuples()}; rows=[]; summaries=[]; now=datetime.now(timezone.utc).isoformat()
    for row in pool.to_dict("records"):
        resolution=int(row["v3_resolution"]); cell=int(row["selected_cell"]); a_cell,b_cell=divmod(cell,resolution); direction=int(np.sign(row["selected_state_return"])); reasons=[]
        if abs(row["selected_state_bps"])>=float(policy.get("min_abs_edge_bps",1.0)):reasons.append("large_state_edge")
        if abs(row["selected_interaction_lift_bps"])>=float(policy.get("min_abs_edge_bps",1.0)):reasons.append("large_interaction_lift")
        if row.get("plateau_area",0)>=2:reasons.append("neighbor_plateau")
        is_variant=pd.notna(row.get("selection_role")) and bool(row.get("selection_role"))
        if is_variant:reasons.append("variant_confirmation")
        sp=specialist_by.get((row["pair_id"],row["target_id"],resolution))
        if sp is not None and getattr(sp,"global_vs_local_disagreement",0)>0:reasons.append("specialist_disagreement")
        family="variant" if is_variant else "canonical_dual"; candidate=make_candidate(feature_a=features[row["feature_a"]],feature_b=features[row["feature_b"]],target=targets[row["target_id"]],grid=features[row["feature_a"]].decision_grid,resolution=resolution,state_payload={"kind":"cell_set","resolution":resolution,"cells":[[a_cell,b_cell]]},state_definition=f"cell({a_cell},{b_cell})",direction=direction,source_snapshot_hash=source_manifest_hash,selection_run_id=legacy_run.root.name,selection_trial_id=f"{family}::{row['pair_id']}::{row['target_id']}::r{resolution}")
        registry={**asdict(candidate),"reason_codes":reasons,"edge_family_id":row["pair_id"],"parent_candidate_id":None,"status":"frozen_discovery_candidate","dossier_status":"pending","sip_status":"not_requested","replication_status":"sealed","superseded_by":None,"created_at_utc":now}; rows.append(registry); summaries.append({**registry,**row})
    registry_columns=["candidate_id","feature_a_id","feature_b_id","target_id","grid","resolution","state_payload","state_definition","direction","source_snapshot_hash","selection_run_id","selection_trial_id","return_basis","definition_hash","reason_codes","edge_family_id","parent_candidate_id","status","dossier_status","sip_status","replication_status","superseded_by","created_at_utc"]
    registry=pd.DataFrame(rows) if rows else pd.DataFrame(columns=registry_columns); summary=pd.DataFrame(summaries) if summaries else pd.DataFrame(columns=[*registry_columns,"pair_id","feature_a","feature_b","v3_resolution","selected_n","selected_frequency","selected_state_bps","selected_interaction_lift_bps","weighted_state_contribution_bps","weighted_interaction_contribution_bps","selected_direction"]); registry.to_parquet(legacy_run.root/"edge_registry.parquet",index=False); summary.to_parquet(legacy_run.root/"candidate_summary.parquet",index=False); return registry,summary
