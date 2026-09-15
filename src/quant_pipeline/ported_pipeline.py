from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from quant_pipeline.alpha_discovery.config import AlphaDiscoveryConfig,SourceConfig,ResearchPeriodsConfig,ComputeConfig
from quant_pipeline.alpha_discovery.run import AlphaDiscoveryRun
from quant_pipeline.data.bridge import build_source_bridge
import duckdb,json,os

def ported_config(research,machine,repo_root:Path):
    p=research["periods"]; smoke=research.get("external_smoke",{}); warmup=smoke.get("warmup",{"auto_derive_transitive_history":True})
    bridge_start=warmup.get("snapshot_start","2024-04-01") if not warmup.get("auto_derive_transitive_history",True) else "2024-04-01"
    bridge=build_source_bridge(repo_root=repo_root,machine=machine,start=bridge_start,end=p["discovery"]["end"])
    return AlphaDiscoveryConfig(
      run_name=research["run_name"],project_root=str(repo_root),output_root=machine["run_root"],
      source=SourceConfig(duckdb_path=str(bridge),corporate_actions_path=str(repo_root/"reference/corporate_actions.parquet")),
      research_periods=ResearchPeriodsConfig(discovery_start=p["discovery"]["start"],discovery_end=p["discovery"]["end"],replication_start=p["replication"]["start"],replication_end=p["replication"]["end"],final_holdout_start=p["final_holdout"]["start"],allow_replication_access=False,allow_final_holdout_access=False),
      compute=ComputeConfig(prefer_cuda=True,gpu_device=machine.get("gpu_device","cuda:0"),dynamic_memory_fraction=.85,cpu_fallback=True,deterministic=True,feature_block_size="auto",target_block_size="auto",cpu_workers=int(machine.get("feature_workers",6)),host_memory_fraction=.80,duckdb_memory_limit=f"{machine.get('duckdb_memory_limit_gb',18)}GB",duckdb_temp_directory=machine["duckdb_temp"]),
      decision_grids=smoke.get("decision_grids",{"intraday_5m":True,"daily_close":True,"preclose_1555":True,"intraday_1m":False}),
      feature_windows=smoke.get("feature_windows",{"intraday":["1m","2m","5m","10m","15m","30m","60m","120m","240m","session"],"daily":["1d","2d","3d","5d","10d","20d","30d","40d","63d","126d","252d"]}),
      feature_search={"initial_scope":"canonical_concepts","canonical_scale_anchors":{"intraday_5m":"30m","daily_close":"20d","preclose_1555":"20d"}},
      targets=smoke.get("targets",{"intraday":["1m","2m","5m","10m","15m","30m","60m","120m","240m","EOD"],"interday":["1d","2d","3d","5d","10d","20d","30d","40d","63d","126d"],"overnight":True,"bases":["raw","benchmark_adjusted","beta_residual"],"intraday_entry_delay_minutes":1,"daily_entry_delay_minutes":1}),
      universe={"minimum_price":3.0,"minimum_prior_20d_median_dollar_volume":10_000_000,"require_stable_security_id":True,"require_point_in_time_membership":True,**smoke.get("universe",{})},
      duals={"enabled":True,"search_scope":"canonical_concepts","resolutions":[3,5,10],"single_parent_gate":False,"canonical_scale_anchors":{"intraday_5m":"30m","daily_close":"20d","preclose_1555":"20d"},"coarse_bins":3,"extreme_quantiles":[.1,.2],"exhaustive_5x5_all_pairs":True,"exhaustive_10x10_all_pairs":True,"exact_bins":10},
      stability={"chronological_folds":smoke.get("folds",5),"require_neighbor_analysis":True,"require_plateau_detection":True,"minimum_symbol_breadth":.5,"global_fdr_alpha":.05,"minimum_fold_sign_consistency":.6,"minimum_fold_magnitude_ratio":.05,"minimum_cell_count":20,"minimum_neighbor_retention":.25,"minimum_plateau_area":2,"maximum_outlier_cluster_share":.25},
      warmup=warmup if smoke else {"auto_derive_transitive_history":True,"safety_margin_sessions":5,"fail_if_full_coverage_warmup_missing":True},
      context_expansion={"enabled":True,"only_from_stable_base_structures":True,"variant_neighbors_per_side":3,"require_new_confirmation":True},formula_factory={"enabled":False,"max_expression_depth":3,"max_binary_operators":2},ml={"enabled":False,"purged_chronological_folds":True,"symbol_embeddings":False},edge_autopsy={"enabled":True,"mandatory_before_replication":True,"max_candidates":8,"threshold_tails":[.2,.1,.05,.02,.01],"cost_bps_per_side":[0,1,2,3,5,10],"entry_delay_minutes":[1,2,5,10],"placebo_runs":100},governance={"enforce_state_machine":True,"require_candidate_freeze_manifest":True,"require_portfolio_freeze_manifest":True,"require_exhaustiveness_pass_for_freeze":True})

def run_ported_pipeline(research,machine,repo_root:Path):
    cfg=ported_config(research,machine,repo_root); cfg.validate(); run=AlphaDiscoveryRun(cfg)
    stages=research.get("external_smoke",{}).get("stages",["validate-config","snapshot","build-panel","compile-registry","build-features","build-targets","scan-singles","scan-duals-coarse","build-stability","expand-context","run-edge-autopsy","audit-exhaustiveness","build-report"])
    results=[run.execute(stage) for stage in stages]; build_ported_analysis_bundle(run.root); return results

def build_ported_analysis_bundle(run_root:Path):
    run_root=Path(run_root); out=run_root/"analysis_bundle"; out.mkdir(exist_ok=True); db=out/"research.duckdb"; db.unlink(missing_ok=True); con=duckdb.connect(str(db))
    sources={"single_summary":run_root/"single_results/**/*.parquet","dual_summary":run_root/"dual_coarse_results/**/*.parquet","raw_exclusions":run_root/"dual_trial_ledger/**/*.parquet","single_stability":run_root/"stability/single_stability.parquet","candidate_stability":run_root/"stability/candidate_stability.parquet"}
    try:
        for name,source in sources.items():
            if not list(source.parent.glob(source.name)) and "**" not in str(source): continue
            if "**" in str(source) and not list((run_root/name.replace("_summary","")).rglob("*.parquet")):
                # Directory names differ from view names; rely on the explicit path check below.
                prefix=Path(str(source).split("**")[0])
                if not prefix.exists() or not list(prefix.rglob("*.parquet")): continue
            src=str(source).replace("'","''"); dest=out/f"{name}.parquet"; dst=str(dest).replace("'","''")
            con.execute(f"COPY (SELECT * FROM read_parquet('{src}',union_by_name=true)) TO '{dst}' (FORMAT PARQUET,COMPRESSION ZSTD)")
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{dst}')")
        for name in ("feature_registry","target_registry"):
            src=run_root/f"{name}.parquet"
            if src.exists():
                dest=out/src.name; dest.write_bytes(src.read_bytes()); s=str(dest).replace("'","''"); con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{s}')")
        ledger=out/"trial_ledger.parquet"; ledger_sql=str(ledger).replace("'","''")
        pieces=[]
        if "single_summary" in [x[0] for x in con.execute("show tables").fetchall()]:
            pieces.append("SELECT 'single__'||feature_id||'__'||target_id||'__'||fold_id trial_id,'canonical_singles' trial_family_id,'single' trial_type,'executed' status,feature_id feature_a_id,NULL::VARCHAR feature_b_id,target_id,NULL::INTEGER resolution,NULL::VARCHAR reason FROM single_summary GROUP BY ALL")
        if "dual_summary" in [x[0] for x in con.execute("show tables").fetchall()]:
            pieces.append("SELECT 'dual__'||pair_id||'__'||target_id||'__'||CAST(resolution AS VARCHAR) trial_id,'canonical_discovery' trial_family_id,'canonical_dual' trial_type,'executed' status,feature_a feature_a_id,feature_b feature_b_id,target_id,CAST(resolution AS INTEGER) resolution,NULL::VARCHAR reason FROM dual_summary")
        if "raw_exclusions" in [x[0] for x in con.execute("show tables").fetchall()]:
            pieces.append("SELECT 'excluded__'||feature_a||'__'||feature_b||'__'||CAST(row_number() OVER() AS VARCHAR) trial_id,'canonical_discovery' trial_family_id,'canonical_dual' trial_type,'structurally_excluded' status,feature_a feature_a_id,feature_b feature_b_id,CAST(target_id AS VARCHAR) target_id,NULL::INTEGER resolution,reason FROM raw_exclusions")
        if pieces:
            con.execute(f"COPY ({' UNION ALL '.join(pieces)}) TO '{ledger_sql}' (FORMAT PARQUET,COMPRESSION ZSTD)")
            con.execute(f"CREATE VIEW trial_ledger AS SELECT * FROM read_parquet('{ledger_sql}')")
        con.execute("CREATE TABLE specialist_summary(trial_id VARCHAR,symbols_active BIGINT,symbols_eligible BIGINT,effect_dispersion_bps DOUBLE)")
        con.execute("CREATE TABLE edge_registry(candidate_id VARCHAR,status VARCHAR,replication_status VARCHAR)")
    finally: con.close()
    audit=run_root/"checkpoints/audit-exhaustiveness.json"; coverage=json.loads(audit.read_text()) if audit.exists() else {}
    manifest={"run_id":run_root.name,"replication_accessed":False,"final_holdout_accessed":False,"resolutions":[3,5,10],"recommendations_generated":False,"trial_coverage":coverage,"research_duckdb":"research.duckdb"}
    tmp=out/"bundle_manifest.json.partial"; tmp.write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding="utf-8"); os.replace(tmp,out/"bundle_manifest.json")
    (out/"data_dictionary.md").write_text("# Analysis bundle\n\nDiscovery-year outputs are diagnostics, not sealed OOS. Return bases remain explicit in source tables.\n",encoding="utf-8")
    return out
