from pathlib import Path
from types import SimpleNamespace
import numpy as np,pandas as pd,pytest
from quant_pipeline.alpha_discovery.scan.dual_coarse import DualTileScanner
from quant_pipeline.alpha_discovery.data.universe import apply_point_in_time_universe
from quant_pipeline.data.source_manifest import build_production_source_manifest,build_source_manifest
from quant_pipeline.discovery.specialist import specialist_probe
from quant_pipeline.production.cache_keys import SharedStageCache,core_stage_key,stage_implementation_hash
from quant_pipeline.production.legacy_core import LOW_LEVEL_STAGES,LegacyCoreAdapter
from quant_pipeline.production.materialization import materialization_pool,materialize_candidates
from quant_pipeline.production.runner import V3ProductionRunner
from quant_pipeline.production.resolution_diagnostics import build_resolution_diagnostics
from quant_pipeline.production.variant_scan import execute_variant_expansion

def duals():
    return pd.DataFrame([
        {"pair_id":"p","target_id":"t","v3_resolution":5,"selected_n":500,"selected_state_bps":5.0,"selected_interaction_lift_bps":2.0},
        {"pair_id":"p","target_id":"t","v3_resolution":10,"selected_n":500,"selected_state_bps":-0.1,"selected_interaction_lift_bps":-0.1},
        {"pair_id":"n","target_id":"t","v3_resolution":3,"selected_n":500,"selected_state_bps":-4.0,"selected_interaction_lift_bps":-3.0},
    ])

def test_resolution_independence_and_negative_retention():
    got=materialization_pool(duals(),min_active_n=100,min_abs_edge_bps=1,top_k=10)
    assert set(zip(got.pair_id,got.v3_resolution))=={("p",5),("n",3)}
    assert got.loc[got.pair_id.eq("n"),"selected_state_bps"].iloc[0]<0

def test_scanner_persists_separate_economic_fields():
    rng=np.random.default_rng(2); a=rng.integers(0,5,(200,1),dtype=np.int8); b=rng.integers(0,5,(200,1),dtype=np.int8); y=rng.normal(0,.01,200)
    row=DualTileScanner(bins=5,prefer_cuda=False).scan(a,b,y).iloc[0]
    for name in ("selected_state_bps","selected_interaction_lift_bps","selected_frequency","selected_n","weighted_state_contribution_bps","weighted_interaction_contribution_bps"): assert name in row.index
    assert row.selected_direction==np.sign(row.selected_state_return)

def test_specialist_cancellation_is_visible():
    security=np.repeat(np.arange(10),20); returns=np.where(security<5,10.0,-10.0); got=specialist_probe(security_id=security,active=np.ones(len(security),bool),returns_bps=returns,min_local_n=20)
    assert got["fraction_positive"]==.5 and got["fraction_negative"]==.5 and got["effect_dispersion_bps"]>9

def test_source_manifest_changes_cache_identity(tmp_path):
    source=tmp_path/"data"; source.mkdir(); part=source/"part.parquet"; part.write_bytes(b"one"); first=build_source_manifest(source); part.write_bytes(b"two-two"); second=build_source_manifest(source); assert first["source_manifest_hash"]!=second["source_manifest_hash"]
    assert core_stage_key(stage="features",source_manifest_hash=first["source_manifest_hash"],semantic_config={},implementation_hash="x")!=core_stage_key(stage="features",source_manifest_hash=second["source_manifest_hash"],semantic_config={},implementation_hash="x")

def test_production_source_hash_includes_reference_identity(tmp_path):
    data=tmp_path/"data"; data.mkdir(); (data/"part.parquet").write_bytes(b"raw"); repo=tmp_path/"repo"; refs=repo/"reference"; refs.mkdir(parents=True)
    for name in ("security_master.parquet","sp500_pit_membership_daily.parquet","corporate_actions.parquet"): (refs/name).write_bytes(name.encode())
    first=build_production_source_manifest(data_root=data,repo_root=repo); (refs/"security_master.parquet").write_bytes(b"changed"); second=build_production_source_manifest(data_root=data,repo_root=repo)
    assert first["source_manifest_hash"]!=second["source_manifest_hash"] and not Path(first["reference_files"][0]["relative_path"]).is_absolute()

def test_component_hashes_are_stage_scoped():
    root=Path(__file__).resolve().parents[2]
    assert stage_implementation_hash("build-features",root)!=stage_implementation_hash("scan-duals-coarse",root)

def test_shared_stage_cache_materializes_compatible_artifacts(tmp_path):
    first=tmp_path/"run-a"; artifact=first/"cache/features/g/observations.parquet"; artifact.parent.mkdir(parents=True); artifact.write_bytes(b"immutable"); store=SharedStageCache(tmp_path/"shared"); store.publish("build-features","key",first,{"rows":1}); second=tmp_path/"run-b"; result=store.restore("build-features","key",second); assert result["rows"]==1 and (second/"cache/features/g/observations.parquet").read_bytes()==b"immutable"

def test_restored_fused_scan_manifest_is_rebased_to_new_run_identity(tmp_path):
    class Config: definition_hash="new-config"
    class Run:
        root=tmp_path; config=Config(); implementation_hash="new-implementation"
        def _atomic_json(self,relative,payload):
            path=self.root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(__import__("json").dumps(payload),encoding="utf-8")
    path=tmp_path/"cache/fused_dual_scan.json"; path.parent.mkdir(parents=True); path.write_text('{"config_hash":"old","implementation_hash":"old","resolutions":[3,5,10]}',encoding="utf-8")
    LegacyCoreAdapter._rebase_restored_stage_metadata(Run(),"scan-duals-coarse")
    restored=__import__("json").loads(path.read_text(encoding="utf-8")); assert restored["config_hash"]=="new-config" and restored["implementation_hash"]=="new-implementation"

def test_production_boundary_and_oos_seal(tmp_path):
    assert not {"build-stability","expand-context","run-edge-autopsy","build-report"}&set(LOW_LEVEL_STAGES)
    research={"periods":{"discovery":{"start":"2025-05-01","end":"2026-05-01"}}}; runner=V3ProductionRunner(research=research,machine={"data_root":str(tmp_path)},repo_root=tmp_path,telemetry=None)
    with pytest.raises(PermissionError): runner.run()

def test_resolution_bundle_keeps_three_independent_rows(tmp_path):
    for resolution,tree in ((3,"dual_coarse_results"),(5,"dual_fine_results"),(10,"dual_exact_results")):
        root=tmp_path/tree/"grid"/"target"; root.mkdir(parents=True); pd.DataFrame([{"pair_id":"p","target_id":"t","resolution":resolution}]).to_parquet(root/"part.parquet",index=False)
    result=pd.read_parquet(build_resolution_diagnostics(run_root=tmp_path,research={"resolutions":[3,5,10]})); assert set(result.v3_resolution)=={3,5,10}

def test_variant_is_planned_scanned_and_trial_accounted(tmp_path,monkeypatch):
    features=[SimpleNamespace(feature_id="a30",concept_id="a",decision_grid="g",minimum_history=30),SimpleNamespace(feature_id="a15",concept_id="a",decision_grid="g",minimum_history=15),SimpleNamespace(feature_id="b30",concept_id="b",decision_grid="g",minimum_history=30)]
    fake=SimpleNamespace(root=tmp_path,compile_registry=lambda:SimpleNamespace(features=features),config=SimpleNamespace())
    frame=pd.DataFrame([{"pair_id":"p","feature_a":"a30","feature_b":"b30","target_id":"t","v3_resolution":5,"selected_n":500,"selected_state_bps":4.0,"selected_interaction_lift_bps":2.0}])
    monkeypatch.setattr("quant_pipeline.production.variant_scan._scan_one",lambda *a,**k:[{"selected_state_bps":3.0,"selected_interaction_lift_bps":1.0,"selected_n":100,"selected_frequency":.1,"selected_state_return":.0003,"selected_cell":0,"surface_counts":[100],"surface_sums":[.03],"surface_sumsq":[.000009],"best_cell_effect":.0003,"worst_cell_effect":-.0001,"neighbor_effect_retention":.5,"plateau_area":2,"weighted_state_contribution_bps":.3,"weighted_interaction_contribution_bps":.1,"selected_direction":1,"pair_id":"x","feature_a":"a15","feature_b":"b30","target_id":"t","resolution":r,"v3_resolution":r} for r in (3,5,10)])
    summary,trials,metrics=execute_variant_expansion(legacy_run=fake,duals=frame,research={"resolutions":[3,5,10],"forensics":{"candidate_policy":{"min_active_n":100,"min_abs_edge_bps":1,"keep_top_k_per_target_resolution":10}},"variant_expansion":{"parent_limit":1,"neighbors_per_side":2,"rejected_audit_count":0}})
    assert len(summary)==3 and set(trials.status)=={"executed"} and metrics["planned"]==1

def test_universe_filters_use_only_prior_sessions():
    sessions=pd.date_range("2025-01-01",periods=21).date; rows=[]
    for security,price,prior_volume,current_volume in (("liquid",10.,100.,100.),("current_spike",10.,10.,100000.),("low_price",2.,1000.,1000.)):
        for index,session in enumerate(sessions): rows.append({"security_id":security,"session_date":session,"bar_start_ts_utc":pd.Timestamp(session),"close":price,"vwap":price,"volume":current_volume if index==20 else prior_volume})
    bars=pd.DataFrame(rows); panel=bars[bars.session_date.eq(sessions[-1])].copy(); membership=panel[["security_id","session_date"]].assign(in_universe=True); master=pd.DataFrame({"security_id":["liquid","current_spike","low_price"]})
    got=apply_point_in_time_universe(panel,membership,master,{"minimum_price":3.,"minimum_prior_20d_median_dollar_volume":500.},bars)
    assert got.security_id.tolist()==["liquid"]

def test_interaction_only_candidate_is_preserved_and_non_directional(tmp_path):
    feature=lambda feature_id:SimpleNamespace(feature_id=feature_id,definition_hash=feature_id+"_hash",decision_grid="g")
    target=SimpleNamespace(target_id="t",definition_hash="t_hash",return_basis="raw")
    fake=SimpleNamespace(root=tmp_path,compile_registry=lambda:SimpleNamespace(features=[feature("a"),feature("b")],targets=[target]))
    dual=pd.DataFrame([{"pair_id":"p","feature_a":"a","feature_b":"b","target_id":"t","v3_resolution":3,"selected_cell":0,"selected_n":500,"selected_frequency":.1,"selected_state_return":0.,"selected_state_bps":0.,"selected_interaction_lift_bps":5.,"weighted_state_contribution_bps":0.,"weighted_interaction_contribution_bps":.5,"selected_direction":0}])
    registry,summary=materialize_candidates(legacy_run=fake,duals=dual,specialist=pd.DataFrame(),research={"forensics":{"candidate_policy":{"min_active_n":100,"min_abs_edge_bps":1.,"keep_top_k_per_target_resolution":10}}},source_manifest_hash="source")
    assert len(registry)==1 and registry.iloc[0].candidate_type=="interaction_only" and registry.iloc[0].direction==0 and summary.iloc[0].candidate_type=="interaction_only"
