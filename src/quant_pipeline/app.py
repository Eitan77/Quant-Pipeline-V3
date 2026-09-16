from __future__ import annotations
import json, os, shutil, time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq, yaml
from quant_pipeline.analysis_bundle import AnalysisBundleBuilder
from quant_pipeline.cache import ArtifactStore
from quant_pipeline.candidates import make_candidate
from quant_pipeline.contracts import ArtifactKey,FeatureSpec,TargetSpec
from quant_pipeline.discovery import plan_pairs,scan_surface_cpu,summarize_surface
from quant_pipeline.discovery.specialist import specialist_probe
from quant_pipeline.forensics.distribution import distribution_stats,contribution_concentration
from quant_pipeline.forensics.interaction import interaction_decomposition
from quant_pipeline.forensics.opportunities import build_episodes,independent_entries_fixed_hold
from quant_pipeline.forensics.redundancy import signal_jaccard
from quant_pipeline.hashing import content_hash
from quant_pipeline.telemetry import Telemetry

STAGES=("preflight","observation_index","registry_compile","features","targets","canonical_bins","singles","canonical_duals","specialist_probe","variant_expansion","candidate_materialization","forensics","analysis_bundle")

def _write_json(path,payload):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".partial"); tmp.write_text(json.dumps(payload,indent=2,sort_keys=True,default=str),encoding="utf-8"); os.replace(tmp,path)
def _write_table(path,rows):
    path=Path(path); tmp=path.with_suffix(".parquet.partial"); pq.write_table(pa.Table.from_pylist(rows),tmp,compression="zstd"); os.replace(tmp,path)
def _done(run_dir,stage): return (run_dir/"stages"/f"{stage}.complete.json").exists()
def _mark(run_dir,stage,metrics): _write_json(run_dir/"stages"/f"{stage}.complete.json",{"stage":stage,"completed_at_utc":datetime.now(timezone.utc).isoformat(),"metrics":metrics})

def _spec_feature(fid,concept,family,canonical=True,params=None):
    base=dict(feature_id=fid,concept_id=concept,family=family,grid="intraday_1m",canonical=canonical,required_inputs=("close",),required_history_bars=1,availability_rule="bar_end",price_basis="split_consistent",parameters=params or {},implementation_id=f"v3.{fid}.v1")
    return FeatureSpec(**base,definition_hash=content_hash(base))
def _spec_target(tid,h):
    base=dict(target_id=tid,family="forward_return",grid="intraday_1m",horizon_minutes=h,return_basis="raw",entry_rule="next_bar_open",exit_rule=f"entry_plus_{h}m",same_day_requirement=True,validity_rule="finite_same_session",implementation_id=f"v3.{tid}.v1")
    return TargetSpec(**base,definition_hash=content_hash(base))

def smoke_fixture():
    symbols=np.array(["AAA","BBB","CCC","DDD","EEE"]); sessions=10; bars=12; n=len(symbols)*sessions*bars
    sec=np.repeat(np.arange(5),sessions*bars); session=np.tile(np.repeat(np.arange(sessions),bars),5); seq=np.tile(np.arange(bars),5*sessions)
    base=pd.Timestamp("2025-05-01",tz="UTC"); ts=np.array([(base+pd.Timedelta(days=int(s))+pd.Timedelta(hours=14,minutes=30+int(q))).value for s,q in zip(session,seq)],dtype=np.int64)
    obs=np.arange(n,dtype=np.int64); rng=np.random.default_rng(731)
    a=((seq+session+sec)%10).astype(np.uint8); b=((2*seq+3*session+sec)%10).astype(np.uint8); c=((7*seq+session+2*sec)%10).astype(np.uint8)
    noise=rng.normal(0,0.35,n); y1=noise+np.where((a//2==4)&(b//2==4),6.0,0)-np.where((a//2==0)&(c//2==4),5.0,0)
    y2=rng.normal(0,0.4,n)+np.where((a%5==2)&(b%5==3),3.5,0); y3=rng.normal(0,0.5,n)
    features=[_spec_feature("v2_rank_path_30m","path","path"),_spec_feature("v2_rank_flow_30m","flow","price_volume"),_spec_feature("v2_rank_volatility_30m","volatility","volatility"),_spec_feature("v2_rank_path_15m","path","path",False,{"window":"15m"})]
    targets=[_spec_target("fwd_1m_raw",1),_spec_target("fwd_5m_raw",5),_spec_target("fwd_10m_raw",10)]
    index=pd.DataFrame({"obs_id":obs,"security_id":sec,"symbol":symbols[sec],"session_id":session,"security_session_seq":seq,"session_date":[(base+pd.Timedelta(days=int(x))).date() for x in session],"decision_ts_utc":pd.to_datetime(ts,utc=True),"grid_id":"intraday_1m","entry_reference_ts_utc":pd.to_datetime(ts+60_000_000_000,utc=True),"universe_eligible":True})
    return index,features,targets,{features[0].feature_id:a,features[1].feature_id:b,features[2].feature_id:c,features[3].feature_id:(a+1)%10},{targets[0].target_id:y1.astype("float32"),targets[1].target_id:y2.astype("float32"),targets[2].target_id:y3.astype("float32")}

def _states(rank10,res):
    if res==10:return rank10.astype(np.uint8)
    if res==5:return (rank10//2).astype(np.uint8)
    return np.minimum((rank10.astype(np.uint16)*3)//10,2).astype(np.uint8)

def run_pipeline(*,research,machine,resume=False):
    run_id=research["run_name"]; run_dir=Path(machine["run_root"])/run_id; run_dir.mkdir(parents=True,exist_ok=True); telemetry=Telemetry(run_dir); start=time.perf_counter(); reused=[]
    request_path=run_dir/"request.yaml"
    if not request_path.exists(): request_path.write_text(yaml.safe_dump(research,sort_keys=False),encoding="utf-8")
    for p in (machine["cache_root"],machine["scratch_root"],machine["duckdb_temp"]): Path(p).mkdir(parents=True,exist_ok=True)
    if research.get("fixture") in ("external_port",None):
        from quant_pipeline.production.runner import V3ProductionRunner
        result=V3ProductionRunner(research=research,machine=machine,repo_root=Path(__file__).resolve().parents[2],telemetry=telemetry).run()
        telemetry.status.update({"stage":"complete","completed":1,"expected":1,"elapsed_seconds":time.perf_counter()-start,"replication_accessed":False,"final_holdout_accessed":False,"production_result":result})
        telemetry.event("run_complete",stage="complete",elapsed_seconds=time.perf_counter()-start)
        return run_id
    if research.get("fixture")!="deterministic_smoke": raise RuntimeError("Unknown fixture")
    index,features,targets,rank10,target_values=smoke_fixture(); source_hash=content_hash({"fixture":"deterministic_smoke","rows":len(index)}); artifact_store=ArtifactStore(Path(machine["cache_root"])/"artifacts")
    def stage(name,fn):
        if _done(run_dir,name): reused.append(name); telemetry.event("stage_reused",stage=name); return
        telemetry.event("stage_start",stage=name); m=fn() or {}; _mark(run_dir,name,m); telemetry.event("stage_complete",stage=name,metrics=m)
    stage("preflight",lambda:{"source_catalog":machine["source_catalog"],"source_read_only":True,"replication_accessed":False,"final_holdout_accessed":False})
    stage("observation_index",lambda:(_write_table(run_dir/"observation_index.parquet",index.to_dict("records")) or {"rows":len(index)}))
    def registry():
        _write_table(run_dir/"feature_registry.parquet",[asdict(x) for x in features]); _write_table(run_dir/"target_registry.parquet",[asdict(x) for x in targets]); return {"features":len(features),"canonical_features":sum(x.canonical for x in features),"targets":len(targets)}
    stage("registry_compile",registry)
    def feature_stage():
        d=run_dir/"feature_values"; d.mkdir(exist_ok=True); hits=0
        for k,v in rank10.items():
            key=ArtifactKey("feature",k,content_hash({"source":source_hash,"feature":k,"values":v.tolist()}))
            if artifact_store.has_complete(key,".npy"): cached=artifact_store.validate_file(key,".npy"); hits+=1
            else:
                partial=artifact_store.begin_file(key,".npy"); np.save(partial,v); cached=artifact_store.commit_file(key,partial,".npy",{"rows":len(v),"dtype":str(v.dtype)})
            shutil.copy2(cached,d/f"{k}.npy")
        return {"features":len(rank10),"obs":len(index),"cache_hits":hits,"cache_misses":len(rank10)-hits}
    stage("features",feature_stage)
    def target_stage():
        d=run_dir/"target_values"; d.mkdir(exist_ok=True); hits=0
        for k,v in target_values.items():
            key=ArtifactKey("target",k,content_hash({"source":source_hash,"target":k,"values":v.tolist()}))
            if artifact_store.has_complete(key,".npy"): cached=artifact_store.validate_file(key,".npy"); hits+=1
            else:
                partial=artifact_store.begin_file(key,".npy"); np.save(partial,v); cached=artifact_store.commit_file(key,partial,".npy",{"rows":len(v),"dtype":str(v.dtype)})
            shutil.copy2(cached,d/f"{k}.npy")
        return {"targets":len(target_values),"cache_hits":hits,"cache_misses":len(target_values)-hits}
    stage("targets",target_stage)
    def bins_stage():
        d=run_dir/"canonical_states"; d.mkdir(exist_ok=True); hits=0; total=0
        for f in features:
            if f.canonical:
                for r in research["resolutions"]:
                    total+=1; values=_states(rank10[f.feature_id],r); semantic=f"{f.feature_id}__r{r}"; key=ArtifactKey("canonical_state",semantic,content_hash({"source":source_hash,"feature_hash":f.definition_hash,"resolution":r}))
                    if artifact_store.has_complete(key,".npy"): cached=artifact_store.validate_file(key,".npy"); hits+=1
                    else:
                        partial=artifact_store.begin_file(key,".npy"); np.save(partial,values); cached=artifact_store.commit_file(key,partial,".npy",{"rows":len(values),"dtype":str(values.dtype)})
                    shutil.copy2(cached,d/f"{semantic}.npy")
        return {"artifacts":total,"cache_hits":hits,"cache_misses":total-hits}
    stage("canonical_bins",bins_stage)
    def singles_stage():
        rows=[]
        for f in (x for x in features if x.canonical):
            for t in targets:
                y=target_values[t.target_id]
                for r in research["resolutions"]:
                    s=_states(rank10[f.feature_id],r)
                    for cell in range(r):
                        m=s==cell; rows.append({"feature_id":f.feature_id,"target_id":t.target_id,"grid":f.grid,"resolution":r,"state_id":cell,"active_edge_bps":float(y[m].mean()),"active_frequency":float(m.mean()),"active_n":int(m.sum()),"weighted_contribution_bps":float(y[m].mean()*m.mean()),"direction":1 if y[m].mean()>=0 else -1,"return_basis":t.return_basis})
        _write_table(run_dir/"single_summary.parquet",rows); return {"trials":len(features)*len(targets)*3,"rows":len(rows),"gated_duals":0}
    stage("singles",singles_stage)
    def dual_stage():
        pairs=plan_pairs(features); summaries=[]; cells=[]; trials=[]
        for pi,pair in enumerate(pairs):
            for t in targets:
                y=target_values[t.target_id]
                for r in research["resolutions"]:
                    a=_states(rank10[pair.feature_a_id],r); b=_states(rank10[pair.feature_b_id],r); st=scan_surface_cpu(state_a=a,state_b=b,target_bps=y,target_valid=np.isfinite(y),resolution=r); sm=summarize_surface(counts=st.counts,sums_bps=st.sums_bps,min_cell_n=3)
                    trial=f"dual__{pair.pair_id}__{t.target_id}__r{r}"; selected=sm["best_cell"] if abs(sm["best_mean_bps"])>=abs(sm["worst_mean_bps"]) else sm["worst_cell"]; edge=sm["best_mean_bps"] if selected==sm["best_cell"] else sm["worst_mean_bps"]; direction=1 if edge>=0 else -1; mask=(a==selected[0])&(b==selected[1])
                    summaries.append({"pair_id":pair.pair_id,"feature_a_id":pair.feature_a_id,"feature_b_id":pair.feature_b_id,"target_id":t.target_id,"grid":"intraday_1m","resolution":r,"trial_id":trial,"best_state_id":str(sm["best_cell"]),"worst_state_id":str(sm["worst_cell"]),"selected_state_definition":str(selected),"selected_a":int(selected[0]),"selected_b":int(selected[1]),"active_edge_bps":float(edge),"active_frequency":float(mask.mean()),"active_n":int(mask.sum()),"weighted_contribution_bps":float(edge*mask.mean()),"best_worst_spread_bps":sm["spread_bps"],"direction":direction,"return_basis":t.return_basis,"trial_family_id":"canonical_discovery"})
                    for i,j in np.ndindex(st.counts.shape): cells.append({"trial_id":trial,"pair_id":pair.pair_id,"target_id":t.target_id,"resolution":r,"state_a":i,"state_b":j,"active_n":int(st.counts[i,j]),"sum_bps":float(st.sums_bps[i,j]),"active_edge_bps":float(st.means_bps[i,j]) if np.isfinite(st.means_bps[i,j]) else None})
                    trials.append({"trial_id":trial,"trial_family_id":"canonical_discovery","run_id":run_id,"trial_type":"canonical_dual","status":"executed","feature_a_id":pair.feature_a_id,"feature_b_id":pair.feature_b_id,"target_id":t.target_id,"resolution":r,"reason":None})
            telemetry.progress("canonical_duals",pi+1,len(pairs),pairs_completed=pi+1)
        _write_table(run_dir/"dual_summary.parquet",summaries); _write_table(run_dir/"surface_cells.parquet",cells); _write_table(run_dir/"trial_ledger.parquet",trials)
        return {"expected":len(pairs)*len(targets)*3,"executed":len(trials),"reused":0,"excluded":0,"unavailable":0,"failed":0,"unexplained":0}
    stage("canonical_duals",dual_stage)
    def specialist_stage():
        dual=pq.read_table(run_dir/"dual_summary.parquet").to_pylist(); rows=[]
        for d in dual:
            a=_states(rank10[d["feature_a_id"]],d["resolution"]); b=_states(rank10[d["feature_b_id"]],d["resolution"]); active=(a==d["selected_a"])&(b==d["selected_b"])
            probe=specialist_probe(security_id=index.security_id.to_numpy(),active=active,returns_bps=target_values[d["target_id"]],min_local_n=2); global_effect=float(d["active_edge_bps"]); positive=probe.get("fraction_positive") or 0.0; negative=probe.get("fraction_negative") or 0.0; majority_sign=1 if positive>=negative else -1
            rows.append({"trial_id":d["trial_id"],"pair_id":d["pair_id"],"target_id":d["target_id"],"resolution":d["resolution"],"global_effect_bps":global_effect,"global_weak":abs(global_effect)<1.0,"specialist_majority_sign":majority_sign,"global_cancellation_flag":abs(global_effect)<1.0 and (probe.get("effect_dispersion_bps") or 0.0)>1.0,**probe})
        _write_table(run_dir/"specialist_summary.parquet",rows); return {"rows":len(rows)}
    stage("specialist_probe",specialist_stage)
    def variant_stage():
        dual=pq.read_table(run_dir/"dual_summary.parquet").to_pylist(); ledger=pq.read_table(run_dir/"trial_ledger.parquet").to_pylist(); variants={f.concept_id:[x for x in features if x.concept_id==f.concept_id and not x.canonical] for f in features if f.canonical}; selected=[]
        for row in sorted(dual,key=lambda x:abs(x["active_edge_bps"]),reverse=True):
            if len(selected)>=2: break
            if variants.get(next(x.concept_id for x in features if x.feature_id==row["feature_a_id"])) or variants.get(next(x.concept_id for x in features if x.feature_id==row["feature_b_id"])): selected.append(row)
        rows=[]
        byid={x.feature_id:x for x in features}
        for parent in selected:
            fa,fb=byid[parent["feature_a_id"]],byid[parent["feature_b_id"]]; left=[fa,*variants.get(fa.concept_id,[])]; right=[fb,*variants.get(fb.concept_id,[])]
            for va in left:
                for vb in right:
                    if va.canonical and vb.canonical: continue
                    for target in targets:
                        for r in research["resolutions"]:
                            trial=f"variant__{parent['pair_id']}__{va.feature_id}__{vb.feature_id}__{target.target_id}__r{r}"; a=_states(rank10[va.feature_id],r); b=_states(rank10[vb.feature_id],r); st=scan_surface_cpu(state_a=a,state_b=b,target_bps=target_values[target.target_id],target_valid=np.isfinite(target_values[target.target_id]),resolution=r); sm=summarize_surface(counts=st.counts,sums_bps=st.sums_bps,min_cell_n=3); chosen=sm["best_cell"] if abs(sm["best_mean_bps"])>=abs(sm["worst_mean_bps"]) else sm["worst_cell"]; edge=sm["best_mean_bps"] if chosen==sm["best_cell"] else sm["worst_mean_bps"]
                            rows.append({"trial_id":trial,"trial_family_id":"variant_expansion","parent_trial_id":parent["trial_id"],"reason_codes":["strong_canonical_parent"],"feature_a_id":va.feature_id,"feature_b_id":vb.feature_id,"target_id":target.target_id,"resolution":r,"selected_a":int(chosen[0]),"selected_b":int(chosen[1]),"active_edge_bps":float(edge),"best_worst_spread_bps":float(sm["spread_bps"]),"status":"executed"}); ledger.append({"trial_id":trial,"trial_family_id":"variant_expansion","run_id":run_id,"trial_type":"hierarchical_variant_dual","status":"executed","feature_a_id":va.feature_id,"feature_b_id":vb.feature_id,"target_id":target.target_id,"resolution":r,"reason":"strong_canonical_parent"})
        _write_table(run_dir/"variant_summary.parquet",rows); _write_table(run_dir/"trial_ledger.parquet",ledger); return {"parents":len(selected),"executed":len(rows),"trial_family":"variant_expansion","hierarchical":True}
    stage("variant_expansion",variant_stage)
    def candidates_stage():
        dual=pq.read_table(run_dir/"dual_summary.parquet").to_pylist(); byid={x.feature_id:x for x in features}; tid={x.target_id:x for x in targets}; selected=sorted(dual,key=lambda x:abs(x["active_edge_bps"]),reverse=True)[:6]; rows=[]
        for d in selected:
            c=make_candidate(feature_a=byid[d["feature_a_id"]],feature_b=byid[d["feature_b_id"]],target=tid[d["target_id"]],grid=d["grid"],resolution=d["resolution"],state_payload={"kind":"cell_set","resolution":d["resolution"],"cells":[[d["selected_a"],d["selected_b"]]],"direction":d["direction"]},state_definition=d["selected_state_definition"],direction=d["direction"],source_snapshot_hash=source_hash,selection_run_id=run_id,selection_trial_id=d["trial_id"])
            rows.append({**asdict(c),"status":"frozen_discovery_candidate","created_from_run":run_id,"dossier_status":"pending","sip_status":"not_requested","replication_status":"sealed"})
        _write_table(run_dir/"edge_registry.parquet",rows); return {"candidates":len(rows)}
    stage("candidate_materialization",candidates_stage)
    def forensics_stage():
        cands=pq.read_table(run_dir/"edge_registry.parquet").to_pylist(); dual={x["trial_id"]:x for x in pq.read_table(run_dir/"dual_summary.parquet").to_pylist()}; out=run_dir/"dossiers"; out.mkdir(exist_ok=True)
        masks={}
        for c in cands:
            d=dual[c["selection_trial_id"]]; r=d["resolution"]; a=_states(rank10[d["feature_a_id"]],r); b=_states(rank10[d["feature_b_id"]],r); active=(a==d["selected_a"])&(b==d["selected_b"]); masks[c["candidate_id"]]=active; eps=build_episodes(obs_id=index.obs_id.to_numpy(),security_id=index.security_id.to_numpy(),session_id=index.session_id.to_numpy(),security_session_seq=index.security_session_seq.to_numpy(),decision_ts_ns=index.decision_ts_utc.astype("int64").to_numpy(),active=active); horizon=targets[[x.target_id for x in targets].index(d["target_id"])].horizon_minutes; opp=independent_entries_fixed_hold(episodes=eps,hold_ns=int(horizon*60e9)); pos=np.array([e.start_obs_id for e in opp],dtype=int); y=target_values[d["target_id"]]; returns=y[pos] if len(pos) else np.array([]); cdir=out/c["candidate_id"]; cdir.mkdir(parents=True,exist_ok=True)
            dist={**distribution_stats(returns),**contribution_concentration(returns)}; interaction=interaction_decomposition(target_bps=y,active_a=a==d["selected_a"],active_b=b==d["selected_b"]); payload={"candidate_id":c["candidate_id"],"definition_hash":c["definition_hash"],"return_basis":c["return_basis"],"evidence_label":"discovery_diagnostic","active_observations":int(active.sum()),"episode_count":len(eps),"independent_opportunity_count":len(opp),"opportunities_per_day":len(opp)/10,**dist,**interaction}; _write_json(cdir/"summary.json",payload); _write_json(cdir/"distribution.json",dist); _write_json(cdir/"interaction.json",interaction)
            _write_table(cdir/"episodes.parquet",[asdict(e) for e in eps]); _write_table(cdir/"symbol_breakdown.parquet",[{"security_id":int(s),"symbol":str(index.loc[index.security_id==s,"symbol"].iloc[0]),"opportunities":int(np.sum(index.iloc[pos].security_id.to_numpy()==s)) if len(pos) else 0,"mean_bps":float(y[pos[index.iloc[pos].security_id.to_numpy()==s]].mean()) if len(pos) and np.any(index.iloc[pos].security_id.to_numpy()==s) else None} for s in np.unique(index.security_id)])
            chronological=[]
            for sid in sorted(index.session_id.unique()):
                p=pos[index.iloc[pos].session_id.to_numpy()==sid] if len(pos) else np.array([],dtype=int); chronological.append({"session_id":int(sid),"period_label":"discovery_diagnostic","n":len(p),"mean_bps":float(y[p].mean()) if len(p) else None})
            _write_table(cdir/"chronological_diagnostics.parquet",chronological); ranked=np.sort(returns)[::-1] if len(returns) else returns; _write_table(cdir/"tail_ladder.parquet",[{"tail_percent":p,"n":max(1,int(np.ceil(len(ranked)*p/100))) if len(ranked) else 0,"contribution_bps":float(ranked[:max(1,int(np.ceil(len(ranked)*p/100)))].sum()) if len(ranked) else 0.0} for p in (20,10,5,2,1)]); _write_table(cdir/"horizon_ladder.parquet",[{"target_id":t.target_id,"horizon_minutes":t.horizon_minutes,"n":int(active.sum()),"mean_bps":float(target_values[t.target_id][active].mean())} for t in targets]); _write_table(cdir/"event_path.parquet",[{"offset_bars":k,"mean_bps":float(target_values[t.target_id][active].mean()),"target_id":t.target_id} for k,t in enumerate(targets,1)]); surface=pq.read_table(run_dir/"surface_cells.parquet").to_pylist(); _write_table(cdir/"surface_cells.parquet",[x for x in surface if x["trial_id"]==d["trial_id"]]); sym=index.iloc[pos].security_id.to_numpy() if len(pos) else np.array([]); shares=pd.Series(sym).value_counts(normalize=True) if len(sym) else pd.Series(dtype=float); _write_json(cdir/"robustness.json",{"leave_best_symbol_n":int(len(returns)-np.sum(sym==shares.index[0])) if len(shares) else 0,"top_symbol_share":float(shares.iloc[0]) if len(shares) else None,"top5_symbol_share":float(shares.iloc[:5].sum()) if len(shares) else None,"discovery_only":True})
        for c in cands:
            peers=[{"candidate_id":other["candidate_id"],"signal_jaccard":signal_jaccard(masks[c["candidate_id"]],masks[other["candidate_id"]])} for other in cands if other["candidate_id"]!=c["candidate_id"]]; _write_json(out/c["candidate_id"]/"redundancy.json",{"candidate_id":c["candidate_id"],"peers":peers})
        _write_table(run_dir/"edge_registry.parquet",[{**c,"status":"dossier_complete","dossier_status":"complete"} for c in cands])
        return {"dossiers":len(cands),"discovery_diagnostic":True,"replication_accessed":False}
    stage("forensics",forensics_stage)
    def bundle_stage():
        bundle=AnalysisBundleBuilder(run_dir/"analysis_bundle"); bundle.collect(run_dir); db=bundle.build_duckdb(); manifest={"run_id":run_id,"source_snapshot_hash":source_hash,"replication_accessed":False,"final_holdout_accessed":False,"canonical_trial_coverage":"reconciled","resolutions":[3,5,10],"recommendations_generated":False}; bundle.write_manifest(manifest); _write_json(run_dir/"run_manifest.json",manifest); return {"duckdb":str(db),"bundle_files":len(list((run_dir/"analysis_bundle").iterdir()))}
    stage("analysis_bundle",bundle_stage)
    elapsed=time.perf_counter()-start; telemetry.status.update({"stage":"complete","elapsed_seconds":elapsed,"reused_stages":reused,"completed":len(STAGES),"expected":len(STAGES)}); telemetry.event("run_complete",stage="complete",elapsed_seconds=elapsed,reused_stages=reused)
    return run_id

def status(run_id,machine):
    p=Path(machine["run_root"])/run_id/"STATUS.json"
    if not p.exists(): raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))
