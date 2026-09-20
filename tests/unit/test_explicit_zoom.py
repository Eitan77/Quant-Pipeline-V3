from types import SimpleNamespace
import numpy as np,pandas as pd,pytest
from quant_pipeline.alpha_discovery.scan.dual_pairs import pair_id
from quant_pipeline.production.dossiers import _active_symbol_breakdown,_aligned_stats,_concentration
from quant_pipeline.production.materialization import materialize_candidates
from quant_pipeline.production.specialist_stage import run_production_specialist_probe
from quant_pipeline.production.surface_math import reselect_surface_cell
from quant_pipeline.production.variant_scan import execute_variant_expansion
from quant_pipeline.production.zoom_requests import resolve_explicit_candidate_requests,resolve_explicit_variant_requests,state_key
from quant_pipeline.production.zoom_selection import build_pre_specialist_contenders

def specs():
    feature=lambda name,grid="g":SimpleNamespace(feature_id=name,concept_id=name,family=name,decision_grid=grid,minimum_history=1,definition_hash=name+"_hash")
    target=SimpleNamespace(target_id="t",decision_grid="g",definition_hash="t_hash",return_basis="raw")
    return [feature("a"),feature("b"),feature("c")],[target]

def surface(a="a",b="b",resolution=2,cell=0):
    row={"pair_id":pair_id(a,b),"feature_a":a,"feature_b":b,"target_id":"t","resolution":resolution,"v3_resolution":resolution,"selected_cell":cell,"selected_n":2,"selected_frequency":1/3,"selected_state_return":.00015,"selected_state_bps":1.5,"selected_interaction_lift":-.00025,"selected_interaction_lift_bps":-2.5,"weighted_state_contribution_bps":.5,"weighted_interaction_contribution_bps":-.833,"selected_direction":1,"selected_cell_se":.5,"neighbor_effect_retention":.2,"plateau_area":1,"best_cell_effect":.00065,"worst_cell_effect":.00015,"surface_counts":[2,1,1,2],"surface_sums":[.0003,.0004,.0005,.0013],"surface_sumsq":[5e-8,1.6e-7,2.5e-7,8.5e-7],"selection_test_effect":.1,"cluster_se":.2,"p_value":.3}
    return row

def fake_run(tmp_path):
    features,targets=specs(); return SimpleNamespace(root=tmp_path,compile_registry=lambda:SimpleNamespace(features=features,targets=targets),config=SimpleNamespace())

def test_exact_explicit_cell_reconstruction_preserves_scanner_provenance():
    got=reselect_surface_cell(surface(),1)
    assert got["selected_cell"]==1 and got["selected_n"]==1 and got["selected_state_bps"]==pytest.approx(4.0)
    assert got["selected_frequency"]==pytest.approx(1/6) and got["weighted_state_contribution_bps"]==pytest.approx(4/6)
    assert got["scanner_selected_cell"]==0 and got["scanner_cluster_se"]==.2 and got["cluster_se"] is None and got["p_value"] is None

def test_canonical_explicit_variant_is_reused_and_ledger_reconciles(tmp_path,monkeypatch):
    run=fake_run(tmp_path); canonical=pd.DataFrame([surface(resolution=r) for r in (3,5,10)])
    research={"resolutions":[3,5,10],"forensics":{"candidate_policy":{"min_active_n":1,"min_abs_edge_bps":1,"keep_top_k_per_target_resolution":1}},"variant_expansion":{"mode":"explicit","explicit_requests":[{"source_feature_a":"a","source_feature_b":"b","feature_a":"b","feature_b":"a","target_id":"t","family":"requested","role":"check"}]}}
    resolved=resolve_explicit_variant_requests(legacy_run=run,canonical_duals=canonical,research=research); assert resolved.iloc[0].canonical_existing
    monkeypatch.setattr("quant_pipeline.production.variant_scan._scan_one",lambda *a,**k:pytest.fail("canonical request rescanned"))
    summary,trials,_=execute_variant_expansion(legacy_run=run,duals=canonical,research=research,canonical_duals=canonical,resolved_requests=resolved)
    assert len(summary)==3 and summary.canonical_reuse.all() and set(trials.status)=={"reused"} and len(trials)==3

def test_explicit_cell_rejects_reversed_authoritative_orientation(tmp_path):
    run=fake_run(tmp_path); canonical=pd.DataFrame([surface()]); research={"forensics":{"explicit_candidates":[{"feature_a":"b","feature_b":"a","target_id":"t","resolution":2,"cell_mode":"explicit","cell_index":1,"direction_mode":"auto","family":"f","role":"r"}]}}
    with pytest.raises(ValueError,match="orientation is reversed"): resolve_explicit_candidate_requests(legacy_run=run,canonical_duals=canonical,variant_duals=pd.DataFrame(),research=research)

def test_exact_rows_bypass_top_k_and_cells_make_distinct_candidates(tmp_path):
    run=fake_run(tmp_path); first=surface(cell=0); second=reselect_surface_cell(first,1)
    for row in (first,second): row["state_key"]=state_key(row); row["direction_mode"]="auto"
    exact=pd.DataFrame([first,second]); specialist=pd.DataFrame(columns=["state_key"])
    registry,summary=materialize_candidates(legacy_run=run,duals=exact,specialist=specialist,research={"forensics":{"candidate_policy":{"min_active_n":999999,"min_abs_edge_bps":999,"keep_top_k_per_target_resolution":0}}},source_manifest_hash="source",candidate_rows=exact)
    assert len(registry)==2 and registry.candidate_id.nunique()==2 and summary.selection_trial_id.str.contains("::cell").all()

def test_guaranteed_explicit_state_bypasses_specialist_selected_n_screen(tmp_path,monkeypatch):
    row=surface(); row.update(selected_n=1,guaranteed_explicit=True); row["state_key"]=state_key(row); other=reselect_surface_cell(row,1); other.update(selected_n=1,guaranteed_explicit=True); other["state_key"]=state_key(other); frame=pd.DataFrame([row,other]); obs=pd.DataFrame({"security_id":[1,1],"session_date":["2025-01-01"]*2})
    data=SimpleNamespace(selected=lambda r: ("g",obs,None,None,np.array([.01,.02]),np.array([r["selected_cell"]==0,r["selected_cell"]==1]),0,0))
    monkeypatch.setattr("quant_pipeline.production.specialist_stage.ProductionData",lambda _:data)
    run=SimpleNamespace(root=tmp_path); path=run_production_specialist_probe(legacy_run=run,duals=frame,research={"specialist":{"min_local_n":1,"min_selected_n":100}}); got=pd.read_parquet(path)
    assert len(got)==2 and got.state_key.nunique()==2 and set(got.selected_cell)=={0,1}

def test_descriptive_raw_evidence_and_absolute_concentration_remain_available():
    raw=np.array([-5.,2.,7.]); stats=_aligned_stats(raw,0); assert stats["raw_mean_bps"]==pytest.approx(raw.mean()) and np.isnan(stats["direction_aligned_mean_bps"]) and np.isnan(stats["favorable_rate"])
    selected=pd.DataFrame({"security_id":[1,1,2],"session_date":pd.to_datetime(["2025-01-01","2025-01-02","2025-01-02"])}); concentration=_concentration(raw,np.full(3,np.nan),selected,0)
    assert concentration[0]["contribution_basis"]=="raw_absolute" and concentration[0]["absolute_contribution_bps"]==14 and np.isnan(concentration[0]["direction_aligned_mean_bps"])

def test_symbol_active_breakdown_uses_every_active_observation():
    obs=pd.DataFrame({"security_id":[1,1,1,2]}); y=np.array([.01,.02,.03,-.01]); mask=np.array([True,True,True,True]); security=pd.DataFrame({"security_id":[1,2],"symbol":["AAA","BBB"]})
    got=pd.DataFrame(_active_symbol_breakdown(candidate_id="c",obs=obs,y=y,mask=mask,security=security,min_local_n=3))
    assert got.active_n.sum()==4 and got.set_index("symbol").loc["AAA","active_n"]==3 and got.set_index("symbol").loc["AAA","specialist_min_n_eligible"]

def test_deterministic_dossier_selection_is_row_order_independent():
    rows=[]
    for i in range(6):
        row=surface(a="a",b="b",cell=i%4); row.update(pair_id=f"p{i}",family="f",selected_n=10+i,selected_state_bps=(-1)**i*(i+1),selected_interaction_lift_bps=i+.5,weighted_state_contribution_bps=i,weighted_interaction_contribution_bps=i/2,neighbor_effect_retention=.1*i,plateau_area=i%3+1,fold_sign_consistency=.1*i); row["state_key"]=f"s{i}"; rows.append(row)
    frame=pd.DataFrame(rows); settings={"pre_specialist_per_family":4}; a=build_pre_specialist_contenders(candidate_rows=frame,explicit_rows=frame.head(0),settings=settings); b=build_pre_specialist_contenders(candidate_rows=frame.sample(frac=1,random_state=4),explicit_rows=frame.head(0),settings=settings)
    assert a.state_key.tolist()==b.state_key.tolist()
