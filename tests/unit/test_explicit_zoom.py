from types import SimpleNamespace
import numpy as np,pandas as pd,pytest
from quant_pipeline.alpha_discovery.scan.dual_pairs import pair_id
from quant_pipeline.production.dossiers import _active_symbol_breakdown,_aligned_stats,_concentration,_resolution_comparison_rows
from quant_pipeline.production.materialization import materialize_candidates
from quant_pipeline.production.runner import V3ProductionRunner
from quant_pipeline.production.specialist_stage import run_production_specialist_probe
from quant_pipeline.production.surface_math import reselect_surface_cell
from quant_pipeline.production.variant_scan import execute_variant_expansion
from quant_pipeline.production.zoom_requests import load_resolution_comparison_rows,resolve_explicit_candidate_requests,resolve_explicit_variant_requests,state_key
from quant_pipeline.production.zoom_selection import build_pre_specialist_contenders,finalize_dossier_selection

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
    run=fake_run(tmp_path); canonical=pd.DataFrame([surface(resolution=r) for r in (3,5,10)]); canonical_path=tmp_path/"canonical.parquet"; canonical.to_parquet(canonical_path,index=False)
    research={"resolutions":[3,5,10],"forensics":{"candidate_policy":{"min_active_n":1,"min_abs_edge_bps":1,"keep_top_k_per_target_resolution":1}},"variant_expansion":{"mode":"explicit","explicit_requests":[{"source_feature_a":"a","source_feature_b":"b","feature_a":"b","feature_b":"a","target_id":"t","family":"requested","role":"check"}]}}
    resolved=resolve_explicit_variant_requests(legacy_run=run,canonical_path=canonical_path,research=research); assert resolved.iloc[0].canonical_existing
    monkeypatch.setattr("quant_pipeline.production.variant_scan._scan_one",lambda *a,**k:pytest.fail("canonical request rescanned"))
    summary,trials,_=execute_variant_expansion(legacy_run=run,duals=canonical,research=research,canonical_path=canonical_path,resolved_requests=resolved)
    assert len(summary)==3 and summary.canonical_reuse.all() and set(trials.status)=={"reused"} and len(trials)==3

def test_explicit_cell_rejects_reversed_authoritative_orientation(tmp_path):
    run=fake_run(tmp_path); canonical=pd.DataFrame([surface()]); canonical_path=tmp_path/"canonical.parquet"; canonical.to_parquet(canonical_path,index=False); research={"forensics":{"explicit_candidates":[{"feature_a":"b","feature_b":"a","target_id":"t","resolution":2,"cell_mode":"explicit","cell_index":1,"direction_mode":"auto","family":"f","role":"r"}]}}
    with pytest.raises(ValueError,match="orientation is reversed"): resolve_explicit_candidate_requests(legacy_run=run,canonical_path=canonical_path,variant_duals=pd.DataFrame(),research=research)

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

def test_explicit_plus_rules_universe_excludes_unrelated_zoom_rows():
    variants=pd.DataFrame({"pair_id":["global","requested"],"request_id":[None,"req-1"],"selected_n":[999,1]})
    got=V3ProductionRunner._explicit_rule_universe(variants)
    assert got.pair_id.tolist()==["requested"]

def test_requested_variants_are_not_regated_before_role_selection():
    row=surface(a="a",b="c",resolution=3); row.update(family="A",request_id="req",selected_n=1,selected_state_bps=.01,selected_interaction_lift_bps=.01); row["state_key"]=state_key(row)
    got=build_pre_specialist_contenders(candidate_rows=pd.DataFrame([row]),explicit_rows=pd.DataFrame(),settings={"pre_specialist_per_family":8})
    assert got.state_key.tolist()==[row["state_key"]]

def test_dynamic_cap_allocates_every_family_before_extra_capacity():
    rows=[]
    for family in ("A","B","C"):
        for index in range(2): rows.append({"state_key":f"{family}{index}","family":family,"dossier_role":"interaction","dossier_role_codes":["interaction"],"role_reason_codes":["interaction"],"dynamic_dossier":True})
    contenders=pd.DataFrame(rows); specialist=pd.DataFrame({"state_key":[x["state_key"] for x in rows],"symbols_eligible":[100,90,2,1,3,2]})
    got=finalize_dossier_selection(contenders=contenders,specialist=specialist,settings={"max_dynamic_dossiers":3})
    assert set(got.family)=={"A","B","C"}

def test_multi_role_reason_codes_survive_deduplication():
    row=surface(resolution=3); row.update(family="A",requested_canonical_parent=True,selected_n=100,plateau_area=5,fold_sign_consistency=1.0); row["state_key"]=state_key(row)
    contenders=build_pre_specialist_contenders(candidate_rows=pd.DataFrame([row]),explicit_rows=pd.DataFrame(),settings={"pre_specialist_per_family":8}); got=finalize_dossier_selection(contenders=contenders,specialist=pd.DataFrame({"state_key":[row["state_key"]],"symbols_eligible":[4]}),settings={"max_dynamic_dossiers":1}); codes=set(got.iloc[0].role_reason_codes)
    assert {"canonical_parent","plateau","interaction","economic_footprint","temporal_breadth","specialist_breadth"}<=codes

def test_cross_resolution_prefers_same_nonzero_sign_and_canonical_role_is_requested_only():
    rows=[]
    for pair,feature_b,edges,requested in (("consistent","b",[1.,2.,3.],True),("mixed","c",[100.,-100.,100.],False)):
        for resolution,edge in zip((3,5,10),edges):
            row=surface(a="a",b=feature_b,resolution=resolution); row.update(pair_id=pair,family="A",selected_state_bps=edge,selected_state_return=edge/1e4,selected_n=100 if pair=="mixed" else 10,requested_canonical_parent=requested); row["state_key"]=state_key(row); rows.append(row)
    got=build_pre_specialist_contenders(candidate_rows=pd.DataFrame(rows),explicit_rows=pd.DataFrame(),settings={"pre_specialist_per_family":8}); canonical=got[got.role_reason_codes.map(lambda x:"canonical_parent" in x)].iloc[0]; cross=got[got.role_reason_codes.map(lambda x:"cross_resolution" in x)].iloc[0]
    assert canonical.pair_id=="consistent" and cross.pair_id=="consistent"

def test_explicit_resolution_comparison_fetches_all_canonical_scanner_rows(tmp_path):
    canonical=pd.DataFrame([surface(resolution=r,cell=0) for r in (3,5,10)]); path=tmp_path/"canonical.parquet"; canonical.to_parquet(path,index=False); frozen=surface(resolution=5,cell=2); frozen["cell_mode"]="explicit"; candidates=pd.DataFrame([frozen])
    targeted=load_resolution_comparison_rows(canonical_path=path,variant_duals=pd.DataFrame(),candidates=candidates); rows=_resolution_comparison_rows(candidate_id="E",row=frozen,duals=targeted)
    assert [x["resolution"] for x in rows if x["selection_kind"]=="scanner_selected"]==[3,5,10] and rows[-1]["selection_kind"]=="frozen_candidate"

def test_automatic_variant_materialization_gets_own_specialist_state(tmp_path,monkeypatch):
    canonical=surface(a="a",b="b",resolution=3); variant=surface(a="a",b="c",resolution=3); variant["selection_role"]="variant_confirmation"
    frame=pd.DataFrame([canonical,variant]); frame["state_key"]=[state_key(x) for x in frame.to_dict("records")]; runner=V3ProductionRunner(research={"forensics":{"candidate_policy":{"min_active_n":1,"min_abs_edge_bps":1,"keep_top_k_per_target_resolution":10}}},machine={},repo_root=tmp_path,telemetry=None); selected=runner._automatic_materialization_states(frame)
    obs=pd.DataFrame({"security_id":[1,1],"session_date":["2025-01-01"]*2}); data=SimpleNamespace(selected=lambda r:("g",obs,None,None,np.array([.01,.02]),np.array([True,True]),0,0)); monkeypatch.setattr("quant_pipeline.production.specialist_stage.ProductionData",lambda _:data)
    path=run_production_specialist_probe(legacy_run=SimpleNamespace(root=tmp_path),duals=selected,research={"specialist":{"min_local_n":1,"min_selected_n":1}}); got=pd.read_parquet(path)
    assert state_key(variant) in set(got.state_key)
