from __future__ import annotations
from pathlib import Path
import numpy as np,pandas as pd
from quant_pipeline.alpha_discovery.cache.rank_store import build_packed_bins
from quant_pipeline.alpha_discovery.scan.dual_coarse import DualTileScanner
from quant_pipeline.alpha_discovery.scan.dual_pairs import pair_id
from quant_pipeline.hashing import content_hash
from quant_pipeline.production.materialization import materialization_pool

def _scan_one(legacy_run,left,right,target_id,resolutions):
    feature_map={x.feature_id:x for x in legacy_run.compile_registry().features}; grid=feature_map[left].decision_grid
    observations,values=legacy_run._load_features(grid,[left,right]); codes=pd.factorize(observations.decision_ts,sort=True)[0]; packed=build_packed_bins(values,codes); target=np.asarray(legacy_run._target_ids_and_vector(grid,observations,target_id)); cluster=pd.factorize(observations.session_date,sort=True)[0].astype(np.int32); sessions=np.sort(pd.unique(pd.to_datetime(observations.session_date))); folds={s:f for f,g in enumerate(np.array_split(sessions,int(legacy_run.config.stability["chronological_folds"]))) for s in g}; fold_codes=pd.to_datetime(observations.session_date).map(folds).to_numpy(np.int16); scanner=DualTileScanner(bins=10,device_name=legacy_run.config.compute.gpu_device,prefer_cuda=legacy_run.config.compute.prefer_cuda,memory_fraction=legacy_run.config.compute.dynamic_memory_fraction)
    def reader(start,end): return packed[start:end,0:1],packed[start:end,1:2],target[start:end]
    results=scanner.scan_packed_resolutions(len(target),1,reader,resolutions=tuple(resolutions),cluster_codes=cluster,fold_codes=fold_codes)
    out=[]
    for resolution,frame in results.items():
        row=frame.iloc[0].to_dict(); row|={"pair_id":pair_id(left,right),"feature_a":left,"feature_b":right,"target_id":target_id,"resolution":int(resolution),"v3_resolution":int(resolution)}; out.append(row)
    return out

def execute_variant_expansion(*,legacy_run,duals:pd.DataFrame,research:dict):
    policy=research.get("forensics",{}).get("candidate_policy",{}); parents=materialization_pool(duals,min_active_n=int(policy.get("min_active_n",250)),min_abs_edge_bps=float(policy.get("min_abs_edge_bps",1.0)),top_k=int(policy.get("keep_top_k_per_target_resolution",250))); parent_limit=int(research.get("variant_expansion",{}).get("parent_limit",12)); neighbors=int(research.get("variant_expansion",{}).get("neighbors_per_side",3)); audit_count=int(research.get("variant_expansion",{}).get("rejected_audit_count",2)); bundle=legacy_run.compile_registry(); fmap={x.feature_id:x for x in bundle.features}; selected_keys=set(zip(parents.pair_id,parents.target_id)); rejected=duals[~duals.set_index(["pair_id","target_id"]).index.isin(selected_keys)].copy(); rejected["audit_key"]=[content_hash({"pair_id":p,"run":legacy_run.root.name,"audit_version":1}) for p in rejected.pair_id]; audited=rejected.sort_values("audit_key").head(audit_count); parent_rows=pd.concat([parents.sort_values("materialization_score",ascending=False).drop_duplicates(["pair_id","target_id"]).head(parent_limit),audited],ignore_index=True); requests=[]
    for parent in parent_rows.to_dict("records"):
        pa,pb=fmap[parent["feature_a"]],fmap[parent["feature_b"]]; left=sorted((x for x in bundle.features if x.concept_id==pa.concept_id and x.decision_grid==pa.decision_grid),key=lambda x:(x.feature_id!=pa.feature_id,abs(x.minimum_history-pa.minimum_history),x.feature_id))[:neighbors+1]; right=sorted((x for x in bundle.features if x.concept_id==pb.concept_id and x.decision_grid==pb.decision_grid),key=lambda x:(x.feature_id!=pb.feature_id,abs(x.minimum_history-pb.minimum_history),x.feature_id))[:neighbors+1]
        for a in left:
            for b in right:
                if a.feature_id==pa.feature_id and b.feature_id==pb.feature_id:continue
                x,y=sorted((a.feature_id,b.feature_id)); requests.append({"source_feature_a":pa.feature_id,"source_feature_b":pb.feature_id,"feature_a":x,"feature_b":y,"target_id":parent["target_id"],"selection_role":"rejected_pair_audit" if "audit_key" in parent and pd.notna(parent.get("audit_key")) else "requires_new_chronological_confirmation"})
    planned=pd.DataFrame(requests).drop_duplicates(["feature_a","feature_b","target_id"]) if requests else pd.DataFrame(columns=["source_feature_a","source_feature_b","feature_a","feature_b","target_id","selection_role"]); root=legacy_run.root/"variant_results"; root.mkdir(exist_ok=True); rows=[]; trials=[]
    for item in planned.to_dict("records"):
        base=f"{pair_id(item['feature_a'],item['feature_b'])}::{item['target_id']}"; expected=[root/f"r{r}"/(content_hash({"trial":base,"resolution":r})[:20]+".parquet") for r in research["resolutions"]]
        if all(x.exists() for x in expected):
            scanned=pd.concat([pd.read_parquet(x) for x in expected],ignore_index=True); status="reused"
        else:
            try:
                scanned=pd.DataFrame(_scan_one(legacy_run,item["feature_a"],item["feature_b"],item["target_id"],research["resolutions"])); status="executed"
                for row,path in zip(scanned.to_dict("records"),expected): path.parent.mkdir(parents=True,exist_ok=True); pd.DataFrame([row]).to_parquet(path,index=False)
            except (KeyError,FileNotFoundError): scanned=pd.DataFrame(); status="unavailable"
            except Exception as error: scanned=pd.DataFrame(); status="failed"; item["error"]=f"{type(error).__name__}: {error}"
        if len(scanned):
            scanned["source_feature_a"]=item["source_feature_a"]; scanned["source_feature_b"]=item["source_feature_b"]; scanned["selection_role"]=item["selection_role"]; rows.extend(scanned.to_dict("records"))
        for resolution in research["resolutions"]: trials.append({"trial_id":f"variant::{base}::r{resolution}","trial_family_id":"variant_expansion","trial_type":"variant_dual","feature_a_id":item["feature_a"],"feature_b_id":item["feature_b"],"target_id":item["target_id"],"resolution":resolution,"status":status,"reason":item.get("error"),"work_units":1})
    summary=pd.DataFrame(rows) if rows else pd.DataFrame(columns=["pair_id","feature_a","feature_b","target_id","resolution","v3_resolution","selected_n","selected_frequency","selected_state_return","selected_state_bps","selected_interaction_lift_bps","weighted_state_contribution_bps","weighted_interaction_contribution_bps","selected_direction","selection_role"]); trial_frame=pd.DataFrame(trials) if trials else pd.DataFrame(columns=["trial_id","trial_family_id","trial_type","feature_a_id","feature_b_id","target_id","resolution","status","reason","work_units"]); summary.to_parquet(legacy_run.root/"variant_summary.parquet",index=False); trial_frame.to_parquet(legacy_run.root/"variant_trial_ledger.parquet",index=False)
    threshold=float(policy.get("min_abs_edge_bps",1.0)); meaningful_mask=((summary.selected_state_bps.abs()>=threshold)|(summary.selected_interaction_lift_bps.abs()>=threshold)) if len(summary) else pd.Series(dtype=bool)
    meaningful=int(meaningful_mask.sum()); audit_planned=int(planned.selection_role.eq("rejected_pair_audit").sum()) if len(planned) else 0; audit_meaningful=int(((summary.selection_role=="rejected_pair_audit")&meaningful_mask).sum()) if len(summary) else 0
    metrics={"planned":len(planned),"executed":sum(x["status"]=="executed" for x in trials),"reused":sum(x["status"]=="reused" for x in trials),"unavailable":sum(x["status"]=="unavailable" for x in trials),"failed":sum(x["status"]=="failed" for x in trials),"meaningful_variant_count":meaningful,"audited_reject_count":audit_planned,"estimated_miss_rate":audit_meaningful/max(audit_planned,1)}; (legacy_run.root/"variant_metrics.json").write_text(__import__('json').dumps(metrics,indent=2),encoding="utf-8"); return summary,trial_frame,metrics
