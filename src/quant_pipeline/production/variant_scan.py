from __future__ import annotations
from pathlib import Path
import numpy as np,pandas as pd
from quant_pipeline.alpha_discovery.cache.rank_store import build_packed_bins
from quant_pipeline.alpha_discovery.scan.dual_coarse import DualTileScanner
from quant_pipeline.alpha_discovery.scan.dual_pairs import pair_id
from quant_pipeline.hashing import content_hash
from quant_pipeline.production.materialization import materialization_pool
from quant_pipeline.production.zoom_requests import load_canonical_rows,resolve_explicit_variant_requests
from quant_pipeline.production.variant_batches import plan_batches,scan_batch


def _scan_missing_batches(legacy_run,requests,resolutions,root):
    """Construct each bounded feature tile once for its compatible target set."""
    if not requests:return set()
    if not hasattr(legacy_run,"_load_features"):
        # Tiny legacy test adapters have only the historical scanner hook.
        executed=set()
        for item in requests:
            for row in _scan_one(legacy_run,item["feature_a"],item["feature_b"],item["target_id"],resolutions):
                base=f"{pair_id(item['feature_a'],item['feature_b'])}::{item['target_id']}"
                path=root/f"r{row['resolution']}"/(content_hash({"trial":base,"resolution":row["resolution"]})[:20]+".parquet")
                path.parent.mkdir(parents=True,exist_ok=True)
                pd.DataFrame([row]).to_parquet(path,index=False)
            executed.add((item["feature_a"],item["feature_b"],item["target_id"]))
        return executed
    fmap={item.feature_id:item for item in legacy_run.compile_registry().features}
    feature_grid={key:value.decision_grid for key,value in fmap.items()}
    executed=set()
    prepared_key=None
    for batch in plan_batches(requests,feature_grid,max_pairs=16,max_targets=2):
        grid=batch["grid"]
        key=(grid,tuple(batch["features"]))
        if key!=prepared_key:
            observations,values=legacy_run._load_features(grid,batch["features"])
            codes=pd.factorize(observations.decision_ts,sort=True)[0]
            packed=build_packed_bins(values,codes)
            cluster=pd.factorize(observations.session_date,sort=True)[0].astype(np.int32)
            sessions=np.sort(pd.unique(pd.to_datetime(observations.session_date)))
            folds={session:fold for fold,part in enumerate(np.array_split(sessions,int(legacy_run.config.stability["chronological_folds"]))) for session in part}
            fold_codes=pd.to_datetime(observations.session_date).map(folds).to_numpy(np.int16)
            prepared_key=key
        targets=np.column_stack([np.asarray(legacy_run._target_ids_and_vector(grid,observations,target),dtype=float)
                                 for target in batch["targets"]])
        scanner=DualTileScanner(bins=10,device_name=legacy_run.config.compute.gpu_device,
            prefer_cuda=legacy_run.config.compute.prefer_cuda,
            memory_fraction=legacy_run.config.compute.dynamic_memory_fraction)
        for row in scan_batch(scanner,batch,observations=len(observations),
                              packed_reader=lambda ids,start,stop: packed[start:stop],
                              target_reader=lambda ids,start,stop: targets[start:stop],
                              cluster_codes=cluster,fold_codes=fold_codes,resolutions=tuple(resolutions)):
            pair=pair_id(row["feature_a"],row["feature_b"])
            row["pair_id"]=pair
            base=f"{pair}::{row['target_id']}"
            path=root/f"r{row['resolution']}"/(content_hash({"trial":base,"resolution":row["resolution"]})[:20]+".parquet")
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix(".partial.parquet")
            pd.DataFrame([row]).to_parquet(temporary,index=False)
            temporary.replace(path)
            executed.add((row["feature_a"],row["feature_b"],row["target_id"]))
    return executed

def _scan_one(legacy_run,left,right,target_id,resolutions):
    feature_map={x.feature_id:x for x in legacy_run.compile_registry().features}; grid=feature_map[left].decision_grid
    observations,values=legacy_run._load_features(grid,[left,right]); codes=pd.factorize(observations.decision_ts,sort=True)[0]; packed=build_packed_bins(values,codes); target=np.asarray(legacy_run._target_ids_and_vector(grid,observations,target_id)); cluster=pd.factorize(observations.session_date,sort=True)[0].astype(np.int32); sessions=np.sort(pd.unique(pd.to_datetime(observations.session_date))); folds={s:f for f,g in enumerate(np.array_split(sessions,int(legacy_run.config.stability["chronological_folds"]))) for s in g}; fold_codes=pd.to_datetime(observations.session_date).map(folds).to_numpy(np.int16); scanner=DualTileScanner(bins=10,device_name=legacy_run.config.compute.gpu_device,prefer_cuda=legacy_run.config.compute.prefer_cuda,memory_fraction=legacy_run.config.compute.dynamic_memory_fraction)
    def reader(start,end): return packed[start:end,0:1],packed[start:end,1:2],target[start:end]
    results=scanner.scan_packed_resolutions(len(target),1,reader,resolutions=tuple(resolutions),cluster_codes=cluster,fold_codes=fold_codes)
    out=[]
    for resolution,frame in results.items():
        row=frame.iloc[0].to_dict(); row|={"pair_id":pair_id(left,right),"feature_a":left,"feature_b":right,"target_id":target_id,"resolution":int(resolution),"v3_resolution":int(resolution)}; out.append(row)
    return out

def execute_variant_expansion(*,legacy_run,duals:pd.DataFrame,research:dict,canonical_path:Path|None=None,resolved_requests:pd.DataFrame|None=None):
    settings=research.get("variant_expansion",{}); mode=settings.get("mode","automatic"); parent_limit=settings.get("parent_limit"); neighbors=int(settings.get("neighbors_per_side",3)); audit_count=int(settings.get("rejected_audit_count",2)); bundle=legacy_run.compile_registry(); fmap={x.feature_id:x for x in bundle.features}
    policy=research.get("forensics",{}).get("candidate_policy",{}); requests=[]; audited_pairs=set()
    if mode in {"automatic","automatic_plus_explicit"}:
        parents=materialization_pool(duals,min_active_n=int(policy.get("min_active_n",250)),min_abs_edge_bps=float(policy.get("min_abs_edge_bps",1.0)),top_k=int(policy.get("keep_top_k_per_target_resolution",250)))
        normal=parents.sort_values("materialization_score",ascending=False).drop_duplicates(["pair_id","target_id"])
        if parent_limit is not None and int(parent_limit)>0: normal=normal.head(int(parent_limit))
        selected_pairs=set(normal.pair_id); unique_rejected=duals[~duals.pair_id.isin(selected_pairs)].drop_duplicates("pair_id").copy(); unique_rejected["audit_key"]=[content_hash({"pair_id":p,"run":legacy_run.root.name,"audit_version":1}) for p in unique_rejected.pair_id]; audited_pairs=set(unique_rejected.sort_values("audit_key").head(audit_count).pair_id)
        audited=duals[duals.pair_id.isin(audited_pairs)].drop_duplicates(["pair_id","target_id"]); parent_rows=pd.concat([normal.assign(audited_pair=False),audited.assign(audited_pair=True)],ignore_index=True,sort=False)
        for parent in parent_rows.to_dict("records"):
            pa,pb=fmap[parent["feature_a"]],fmap[parent["feature_b"]]; left=sorted((x for x in bundle.features if x.concept_id==pa.concept_id and x.decision_grid==pa.decision_grid),key=lambda x:(x.feature_id!=pa.feature_id,abs(x.minimum_history-pa.minimum_history),x.feature_id))[:neighbors+1]; right=sorted((x for x in bundle.features if x.concept_id==pb.concept_id and x.decision_grid==pb.decision_grid),key=lambda x:(x.feature_id!=pb.feature_id,abs(x.minimum_history-pb.minimum_history),x.feature_id))[:neighbors+1]
            for a in left:
                for b in right:
                    if a.feature_id==pa.feature_id and b.feature_id==pb.feature_id:continue
                    x,y=sorted((a.feature_id,b.feature_id)); requests.append({"source_pair_id":parent["pair_id"],"source_feature_a":pa.feature_id,"source_feature_b":pb.feature_id,"feature_a":x,"feature_b":y,"target_id":parent["target_id"],"selection_role":"rejected_pair_audit" if bool(parent.get("audited_pair",False)) else "requires_new_chronological_confirmation","family":"automatic_variant","role":"rejected_pair_audit" if bool(parent.get("audited_pair",False)) else "variant_confirmation","explicit_request":False,"canonical_existing":False})
    planned=pd.DataFrame(requests) if requests else pd.DataFrame(columns=["source_pair_id","source_feature_a","source_feature_b","feature_a","feature_b","target_id","selection_role","family","role","explicit_request","canonical_existing"])
    if mode in {"explicit","automatic_plus_explicit"}:
        explicit=resolved_requests if resolved_requests is not None else resolve_explicit_variant_requests(legacy_run=legacy_run,canonical_path=canonical_path,research=research)
        if len(explicit):
            explicit=explicit.copy(); explicit["selection_role"]=explicit.role; explicit["explicit_request"]=True
            planned=pd.concat([planned,explicit],ignore_index=True,sort=False)
    registry_path=legacy_run.root/"context_expansion"/"variant_dual_registry.parquet"; registry_path.parent.mkdir(parents=True,exist_ok=True); planned.to_parquet(registry_path,index=False)
    canonical_requests=planned[planned.canonical_existing.fillna(False).astype(bool)] if "canonical_existing" in planned else planned.head(0); canonical_rows=load_canonical_rows(canonical_path=canonical_path,requests=canonical_requests,all_resolutions=True)
    root=legacy_run.root/"variant_results"; root.mkdir(exist_ok=True); rows=[]; trials=[]
    numerical=planned.drop_duplicates(["feature_a","feature_b","target_id"])
    missing=[]
    for item in numerical.to_dict("records"):
        if bool(item.get("canonical_existing",False)):continue
        base=f"{pair_id(item['feature_a'],item['feature_b'])}::{item['target_id']}"
        expected=[root/f"r{r}"/(content_hash({"trial":base,"resolution":r})[:20]+".parquet") for r in research["resolutions"]]
        if not all(path.exists() for path in expected):missing.append(item)
    scan_error=None
    try:executed=_scan_missing_batches(legacy_run,missing,research["resolutions"],root) if missing else set()
    except (KeyError,FileNotFoundError) as error:
        executed=set();scan_error=("unavailable",f"{type(error).__name__}: {error}")
    except Exception as error:
        executed=set();scan_error=("failed",f"{type(error).__name__}: {error}")
    seen_execution=set()
    for item in planned.to_dict("records"):
        request_id=item.get("request_id"); request_id=None if request_id is None or pd.isna(request_id) else request_id
        base=f"{pair_id(item['feature_a'],item['feature_b'])}::{item['target_id']}"; expected=[root/f"r{r}"/(content_hash({"trial":base,"resolution":r})[:20]+".parquet") for r in research["resolutions"]]
        if bool(item.get("canonical_existing",False)):
            requested_pair=pair_id(item["feature_a"],item["feature_b"]); scanned=canonical_rows[(canonical_rows.pair_id==requested_pair)&(canonical_rows.target_id==item["target_id"])&canonical_rows.v3_resolution.isin(research["resolutions"])].copy(); status="reused"
        elif all(x.exists() for x in expected):
            scanned=pd.concat([pd.read_parquet(x) for x in expected],ignore_index=True)
            numerical_key=(item["feature_a"],item["feature_b"],item["target_id"])
            status="executed" if numerical_key in executed and numerical_key not in seen_execution else "reused"
            seen_execution.add(numerical_key)
        else:
            scanned=pd.DataFrame();status=scan_error[0] if scan_error else "unavailable"
            item["error"]=scan_error[1] if scan_error else "Numerical batch did not publish all requested resolutions"
        if len(scanned):
            explicit_request=bool(item.get("explicit_request",False)); canonical_reuse=bool(item.get("canonical_existing",False)); scanned["source_pair_id"]=item["source_pair_id"]; scanned["source_feature_a"]=item["source_feature_a"]; scanned["source_feature_b"]=item["source_feature_b"]; scanned["selection_role"]=item["selection_role"]; scanned["request_id"]=request_id; scanned["family"]=item.get("family"); scanned["role"]=item.get("role"); scanned["explicit_request"]=explicit_request; scanned["execution_status"]=status; scanned["canonical_reuse"]=canonical_reuse; scanned["requested_canonical_parent"]=explicit_request and canonical_reuse; rows.extend(scanned.to_dict("records"))
        for resolution in research["resolutions"]: trials.append({"trial_id":f"variant::{request_id or base}::r{resolution}","trial_family_id":"variant_expansion","trial_type":"explicit_variant_dual" if item.get("explicit_request",False) else "variant_dual","feature_a_id":item["feature_a"],"feature_b_id":item["feature_b"],"target_id":item["target_id"],"resolution":resolution,"status":status,"reason":item.get("error"),"work_units":1,"request_id":request_id,"family":item.get("family"),"role":item.get("role")})
    summary=pd.DataFrame(rows) if rows else pd.DataFrame(columns=["pair_id","feature_a","feature_b","target_id","resolution","v3_resolution","selected_n","selected_frequency","selected_state_return","selected_state_bps","selected_interaction_lift_bps","weighted_state_contribution_bps","weighted_interaction_contribution_bps","selected_direction","selection_role"]); trial_frame=pd.DataFrame(trials) if trials else pd.DataFrame(columns=["trial_id","trial_family_id","trial_type","feature_a_id","feature_b_id","target_id","resolution","status","reason","work_units"]); summary.to_parquet(legacy_run.root/"variant_summary.parquet",index=False); trial_frame.to_parquet(legacy_run.root/"variant_trial_ledger.parquet",index=False)
    threshold=float(policy.get("min_abs_edge_bps",1.0)); meaningful_mask=((summary.selected_state_bps.abs()>=threshold)|(summary.selected_interaction_lift_bps.abs()>=threshold)) if len(summary) else pd.Series(dtype=bool)
    audited_reject_count=len(audited_pairs); meaningful_pairs=set(summary.loc[(summary.selection_role=="rejected_pair_audit")&meaningful_mask,"source_pair_id"]) if len(summary) else set(); meaningful=len(meaningful_pairs); miss_rate=meaningful/audited_reject_count if audited_reject_count else 0.0
    metrics={"planned":len(planned),"executed":sum(x["status"]=="executed" for x in trials),"reused":sum(x["status"]=="reused" for x in trials),"unavailable":sum(x["status"]=="unavailable" for x in trials),"failed":sum(x["status"]=="failed" for x in trials),"meaningful_variant_count":meaningful,"audited_reject_count":audited_reject_count,"estimated_miss_rate":min(1.0,max(0.0,miss_rate))}; (legacy_run.root/"variant_metrics.json").write_text(__import__('json').dumps(metrics,indent=2),encoding="utf-8"); return summary,trial_frame,metrics
