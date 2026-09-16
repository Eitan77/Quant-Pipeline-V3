from __future__ import annotations
import json,os,shutil
from pathlib import Path
import duckdb,pandas as pd

def _concat(files,destination):
    frames=[pd.read_parquet(x) for x in files]
    if frames: pd.concat(frames,ignore_index=True,sort=False).to_parquet(destination,index=False)

def build_v3_analysis_bundle(*,run_root:Path,research:dict,source_manifest_hash:str,trial_coverage:dict)->Path:
    run_root=Path(run_root); out=run_root/"analysis_bundle"; out.mkdir(exist_ok=True); copies={"feature_registry":run_root/"feature_registry.parquet","target_registry":run_root/"target_registry.parquet","single_summary":run_root/"single_summary.parquet","dual_summary":run_root/"v3_diagnostics/dual_resolution_summary.parquet","trial_ledger":run_root/"trial_ledger.parquet","specialist_summary":run_root/"specialist_summary.parquet","variant_summary":run_root/"variant_summary.parquet","edge_registry":run_root/"edge_registry.parquet","candidate_summary":run_root/"candidate_summary.parquet"}
    if not copies["single_summary"].exists() and list((run_root/"single_results").rglob("*.parquet")):
        source=str(run_root/"single_results"/"**"/"*.parquet").replace("'","''"); destination=str(copies["single_summary"]).replace("'","''")
        with duckdb.connect() as con: con.execute(f"COPY (SELECT * FROM read_parquet('{source}',union_by_name=true)) TO '{destination}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    for name,source in copies.items():
        if source.exists(): shutil.copy2(source,out/f"{name}.parquet")
    dossiers=list((run_root/"candidates").glob("*/dossier")); aggregate={"chronological_diagnostics":"chronology.parquet","resolution_comparison":"resolution_comparison.parquet","tail_ladder":"tail_ladder.parquet","horizon_ladder":"horizon_ladder.parquet","crossfit_diagnostics":"crossfit_diagnostics.parquet","time_of_day":"time_of_day.parquet","coverage":"coverage.parquet","regime_breakdown":"regime_breakdown.parquet"}
    for name,filename in aggregate.items(): _concat([d/filename for d in dossiers if (d/filename).exists()],out/f"{name}.parquet")
    empty_columns={"chronological_diagnostics":["candidate_id","diagnostic_type","period","active_n","frequency","raw_mean_bps","direction_aligned_mean_bps","independent_opportunities","evidence_role"],"resolution_comparison":["candidate_id","resolution","selected_cell","selected_state_bps","selected_interaction_lift_bps","selected_frequency","selected_n","surface_spread_bps","neighbor_effect_retention","plateau_area","evidence_role"],"tail_ladder":["candidate_id","tail_percent","applicable","active_n","raw_edge_bps","direction_aligned_edge_bps","evidence_role"],"horizon_ladder":["candidate_id","target_id","horizon","n","raw_mean_bps","direction_aligned_mean_bps","evidence_role"],"crossfit_diagnostics":["candidate_id","fold","heldout_n","heldout_state_bps","evidence_role"],"time_of_day":["candidate_id","bucket","eligible_n","active_n","frequency","evidence_role"],"coverage":["candidate_id","eligible_n","eligible_fraction_of_grid","active_fraction_of_eligible","evidence_role"],"regime_breakdown":["candidate_id","regime","status","reason","evidence_role"]}
    for name,columns in empty_columns.items():
        path=out/f"{name}.parquet"
        if not path.exists(): pd.DataFrame(columns=columns).to_parquet(path,index=False)
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
    registry_count=len(pd.read_parquet(edge)) if edge.exists() else 0; manifest={"run_id":run_root.name,"replication_accessed":False,"final_holdout_accessed":False,"discovery_period":[research["periods"]["discovery"]["start"],research["periods"]["discovery"]["end"]],"resolutions":research["resolutions"],"source_manifest_hash":source_manifest_hash,"trial_coverage":trial_coverage,"candidate_count":registry_count,"dossier_count":len(dossiers),"recommendations_generated":False}; (out/"bundle_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding="utf-8"); (out/"data_dictionary.md").write_text("# V3 production analysis bundle\n\nAll chronology is discovery diagnostic. Economic state returns, interaction lift, frequency, N, and weighted contribution are separate fields. No replication or final holdout rows were accessed.\n",encoding="utf-8"); return out
