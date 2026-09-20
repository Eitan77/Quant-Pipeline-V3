from __future__ import annotations
import json,os,shutil
from pathlib import Path
import duckdb,pandas as pd

def _concat_parquet(files,destination):
    files=[Path(x) for x in files if Path(x).exists()]
    if not files:return
    sources=",".join("'"+str(path).replace("'","''")+"'" for path in files)
    with duckdb.connect() as con: con.execute(f"COPY (SELECT * FROM read_parquet([{sources}],union_by_name=true)) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",[str(destination)])

def _link_or_copy(source,destination):
    destination=Path(destination); destination.unlink(missing_ok=True)
    try:os.link(source,destination)
    except OSError:shutil.copy2(source,destination)

def build_v3_analysis_bundle(*,run_root:Path,research:dict,source_manifest_hash:str,trial_coverage:dict)->Path:
    run_root=Path(run_root); out=run_root/"analysis_bundle"; out.mkdir(exist_ok=True); zoom_enabled=bool(research.get("zoom",{}).get("enabled",False)); copies={"feature_registry":run_root/"feature_registry.parquet","target_registry":run_root/"target_registry.parquet","single_summary":run_root/"single_summary.parquet","dual_summary":run_root/"v3_diagnostics/dual_resolution_summary.parquet","trial_ledger":run_root/"trial_ledger.parquet","cell_specialist_summary":run_root/"cell_specialist_summary.parquet","cell_temporal_summary":run_root/"cell_temporal_summary.parquet"}
    if zoom_enabled: copies.update({"specialist_summary":run_root/"specialist_summary.parquet","variant_summary":run_root/"variant_summary.parquet","edge_registry":run_root/"edge_registry.parquet","candidate_summary":run_root/"candidate_summary.parquet"})
    if not copies["single_summary"].exists() and list((run_root/"single_results").rglob("*.parquet")):
        source=str(run_root/"single_results"/"**"/"*.parquet").replace("'","''"); destination=str(copies["single_summary"]).replace("'","''")
        with duckdb.connect() as con: con.execute(f"COPY (SELECT * FROM read_parquet('{source}',union_by_name=true)) TO '{destination}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    for name,source in copies.items():
        if source.exists(): _link_or_copy(source,out/f"{name}.parquet")
    dossiers=list((run_root/"candidates").glob("*/dossier")) if zoom_enabled else []; aggregate={"chronological_diagnostics":"chronology.parquet","resolution_comparison":"resolution_comparison.parquet","tail_ladder":"tail_ladder.parquet","horizon_ladder":"horizon_ladder.parquet","crossfit_diagnostics":"crossfit_diagnostics.parquet","time_of_day":"time_of_day.parquet","coverage":"coverage.parquet","regime_breakdown":"regime_breakdown.parquet","symbol_active_breakdown":"symbol_active_breakdown.parquet","symbol_breakdown":"symbol_breakdown.parquet","interaction":"interaction.parquet","concentration":"concentration.parquet","inference":"inference.parquet"}
    for name,filename in aggregate.items(): _concat_parquet([d/filename for d in dossiers if (d/filename).exists()],out/f"{name}.parquet")
    empty_columns={"chronological_diagnostics":["candidate_id","diagnostic_type","period","active_n","frequency","raw_mean_bps","direction_aligned_mean_bps","independent_opportunities","evidence_role"],"resolution_comparison":["candidate_id","resolution","selected_cell","selection_kind","selected_state_bps","selected_interaction_lift_bps","selected_frequency","selected_n","surface_spread_bps","neighbor_effect_retention","plateau_area","evidence_role"],"tail_ladder":["candidate_id","tail_percent","applicable","active_n","raw_edge_bps","direction_aligned_edge_bps","evidence_role"],"horizon_ladder":["candidate_id","target_id","horizon","n","raw_mean_bps","direction_aligned_mean_bps","evidence_role"],"crossfit_diagnostics":["candidate_id","fold","heldout_n","heldout_state_bps","evidence_role"],"time_of_day":["candidate_id","bucket","eligible_n","active_n","frequency","evidence_role"],"coverage":["candidate_id","eligible_n","eligible_fraction_of_grid","active_fraction_of_eligible","evidence_role"],"regime_breakdown":["candidate_id","regime","status","reason","evidence_role"],"symbol_active_breakdown":["candidate_id","security_id","symbol","active_n","raw_mean_bps","raw_sum_bps","absolute_contribution_bps","absolute_contribution_share","sign","specialist_min_n_eligible","evidence_role"],"symbol_breakdown":["candidate_id","security_id","n","raw_mean_bps","direction_aligned_mean_bps","evidence_role"],"interaction":["candidate_id","evidence_role"],"concentration":["candidate_id","view","remaining_n","raw_mean_bps","direction_aligned_mean_bps","evidence_role"],"inference":["candidate_id","session_n","raw_session_mean_bps","direction_aligned_session_mean_bps","direction_aligned_t_stat","evidence_role"]}
    for name,columns in empty_columns.items():
        path=out/f"{name}.parquet"
        if not path.exists(): pd.DataFrame(columns=columns).to_parquet(path,index=False)
    zoom_empty={"specialist_summary":["state_key","pair_id","feature_a","feature_b","target_id","resolution","selected_cell"],"variant_summary":["pair_id","target_id","resolution"],"edge_registry":["candidate_id","status","direction","edge_family_id"],"candidate_summary":["candidate_id","pair_id","target_id","resolution"]}
    for name,columns in zoom_empty.items():
        path=out/f"{name}.parquet"
        if not zoom_enabled or not path.exists():pd.DataFrame(columns=columns).to_parquet(path,index=False)
    families=[]
    edge=out/"edge_registry.parquet"
    if edge.exists():
        registry=pd.read_parquet(edge)
        for family,part in registry.groupby("edge_family_id",dropna=False): families.append({"edge_family_id":family,"candidate_count":len(part),"positive_count":int((part.direction>0).sum()),"negative_count":int((part.direction<0).sum())})
    pd.DataFrame(families,columns=["edge_family_id","candidate_count","positive_count","negative_count"]).to_parquet(out/"edge_families.parquet",index=False)
    surface_root=out/"surface_cells"; surface_root.mkdir(exist_ok=True); dossier_root=out/"dossiers"; dossier_root.mkdir(exist_ok=True)
    for resolution,tree in ((3,"dual_coarse_results"),(5,"dual_fine_results"),(10,"dual_exact_results")):
        for index,source in enumerate((run_root/tree).rglob("*.parquet")):
            target=surface_root/f"r{resolution}"/f"part-{index:08d}.parquet"; target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():
                try: os.link(source,target)
                except OSError: shutil.copy2(source,target)
    for dossier in dossiers:
        candidate_id=dossier.parent.name; shutil.copytree(dossier,dossier_root/candidate_id,dirs_exist_ok=True)
    db=out/"research.duckdb"; db.unlink(missing_ok=True)
    with duckdb.connect(str(db)) as con:
        for path in out.glob("*.parquet"):
            name=path.stem; escaped=str(path).replace("'","''"); con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{escaped}')")
        surface_files=list(surface_root.rglob("*.parquet"))
        if surface_files: con.execute(f"CREATE VIEW surface_cells AS SELECT * FROM read_parquet('{str(surface_root/'**'/'*.parquet').replace(chr(39),chr(39)*2)}',union_by_name=true)")
        con.execute("CREATE VIEW surface_summary AS SELECT * FROM dual_summary")
        con.execute("""CREATE VIEW cell_evidence AS WITH expanded AS (
          SELECT d.*,cell_index,floor(cell_index/d.v3_resolution)::INTEGER feature_a_cell,(cell_index%d.v3_resolution)::INTEGER feature_b_cell,
            list_extract(d.surface_counts,cell_index+1)::DOUBLE active_n,list_extract(d.surface_sums,cell_index+1)::DOUBLE cell_sum,list_extract(d.surface_sumsq,cell_index+1)::DOUBLE cell_sumsq,
            list_sum(d.surface_counts)::DOUBLE total_n,list_sum(d.surface_sums)::DOUBLE total_sum
          FROM dual_summary d,UNNEST(range(0,d.v3_resolution*d.v3_resolution)) cells(cell_index)
        ), math AS (
          SELECT *,10000.0*cell_sum/nullif(active_n,0) raw_edge_bps,active_n/nullif(total_n,0) frequency,
            (cell_sumsq-cell_sum*cell_sum/nullif(active_n,0))/nullif(active_n-1,0) variance,
            10000.0*(cell_sum/nullif(active_n,0)
              -list_sum(list_transform(range(feature_a_cell*v3_resolution,(feature_a_cell+1)*v3_resolution),i->list_extract(surface_sums,i+1)))/nullif(list_sum(list_transform(range(feature_a_cell*v3_resolution,(feature_a_cell+1)*v3_resolution),i->list_extract(surface_counts,i+1))),0)
              -list_sum(list_transform(range(feature_b_cell,v3_resolution*v3_resolution,v3_resolution),i->list_extract(surface_sums,i+1)))/nullif(list_sum(list_transform(range(feature_b_cell,v3_resolution*v3_resolution,v3_resolution),i->list_extract(surface_counts,i+1))),0)
              +total_sum/nullif(total_n,0)) interaction_lift_bps
          FROM expanded)
          SELECT m.pair_id,m.feature_a,m.feature_b,m.target_id,m.v3_resolution resolution,m.cell_index,m.feature_a_cell,m.feature_b_cell,m.active_n,m.raw_edge_bps,m.frequency,
            sqrt(greatest(m.variance,0)/nullif(m.active_n,0))*10000.0 se_bps,m.interaction_lift_bps,m.raw_edge_bps*m.frequency weighted_contribution_bps,
            list_extract(sp.positive_symbol_fraction,m.cell_index+1) positive_symbol_fraction,list_extract(sp.negative_symbol_fraction,m.cell_index+1) negative_symbol_fraction,
            list_extract(sp.symbol_effect_dispersion_bps,m.cell_index+1) symbol_effect_dispersion_bps,list_extract(sp.cancellation_score,m.cell_index+1) cancellation_score,
            list_extract(tp.fold_positive_fraction,m.cell_index+1) fold_positive_fraction,list_extract(tp.fold_negative_fraction,m.cell_index+1) fold_negative_fraction,
            list_extract(tp.worst_fold_bps,m.cell_index+1) worst_fold_bps,list_extract(tp.best_fold_bps,m.cell_index+1) best_fold_bps,list_extract(tp.minimum_fold_n,m.cell_index+1) minimum_fold_n
          FROM math m JOIN cell_specialist_summary sp ON sp.pair_id=m.pair_id AND sp.target_id=m.target_id AND sp.resolution=m.v3_resolution
          JOIN cell_temporal_summary tp ON tp.pair_id=m.pair_id AND tp.target_id=m.target_id AND tp.resolution=m.v3_resolution""")
        registry_count=int(con.execute("SELECT count(*) FROM edge_registry").fetchone()[0])
    manifest={"run_id":run_root.name,"evidence_complete":True,"zoom_enabled":zoom_enabled,"replication_accessed":False,"final_holdout_accessed":False,"discovery_period":[research["periods"]["discovery"]["start"],research["periods"]["discovery"]["end"]],"resolutions":research["resolutions"],"source_manifest_hash":source_manifest_hash,"trial_coverage":trial_coverage,"candidate_count":registry_count,"dossier_count":len(dossiers),"recommendations_generated":False}; (out/"bundle_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding="utf-8"); (out/"data_dictionary.md").write_text("# V3 production analysis bundle\n\n`cell_evidence` is the exhaustive canonical cell interface. Surface count/sum/sumsq arrays are authoritative. Replication and final holdout remain sealed.\n",encoding="utf-8"); return out
