from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
import json,os
from pathlib import Path
import duckdb,pandas as pd
from quant_pipeline.data.source_manifest import build_production_source_manifest
from quant_pipeline.production.bundle import build_v3_analysis_bundle
from quant_pipeline.production.cell_specialist import build_cell_specialist_summary
from quant_pipeline.production.cell_temporal import build_cell_temporal_summary
from quant_pipeline.production.dossiers import build_candidate_dossiers
from quant_pipeline.production.legacy_core import LegacyCoreAdapter
from quant_pipeline.production.materialization import materialize_candidates
from quant_pipeline.production.resolution_diagnostics import build_resolution_diagnostics
from quant_pipeline.production.specialist_stage import run_production_specialist_probe
from quant_pipeline.production.trials import build_production_trial_ledger
from quant_pipeline.production.variant_scan import execute_variant_expansion

class V3ProductionRunner:
    def __init__(self,*,research:dict,machine:dict,repo_root:Path,telemetry):
        self.research=research; self.machine=machine; self.repo_root=Path(repo_root); self.telemetry=telemetry; digest=sha256(); package=self.repo_root/"src/quant_pipeline"
        paths=list((package/"production").glob("*.py"))+list((package/"forensics").glob("*.py"))+list((package/"candidates").glob("*.py"))+[path for path in (package/"alpha_discovery/targets/excursions.py",package/"data/source_manifest.py") if path.exists()]
        for path in sorted(paths,key=lambda x:x.relative_to(package).as_posix()): digest.update(path.relative_to(package).as_posix().encode()); digest.update(path.read_bytes())
        self.implementation_hash=digest.hexdigest()
    @staticmethod
    def _write_json(path:Path,payload):
        path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_suffix(".partial"); temporary.write_text(json.dumps(payload,indent=2,sort_keys=True,default=str),encoding="utf-8"); os.replace(temporary,path)
    def _reusable(self,root:Path,name:str,outputs:list[Path],source_hash:str):
        marker=root/"v3_checkpoints"/f"{name}.json"
        if not marker.exists() or not all(path.exists() for path in outputs): return False
        payload=json.loads(marker.read_text()); return payload.get("status")=="complete" and payload.get("source_manifest_hash")==source_hash and payload.get("implementation_hash")==self.implementation_hash
    def _mark(self,root:Path,name:str,source_hash:str,metrics:dict):
        self._write_json(root/"v3_checkpoints"/f"{name}.json",{"stage":name,"status":"complete","completed_at_utc":datetime.now(timezone.utc).isoformat(),"source_manifest_hash":source_hash,"implementation_hash":self.implementation_hash,"metrics":metrics})
        if self.telemetry:self.telemetry.event("v3_stage_complete",stage=f"v3:{name}",metrics=metrics)
    @staticmethod
    def _row_count(path:Path)->int:
        with duckdb.connect() as con:return int(con.execute("SELECT count(*) FROM read_parquet(?)",[str(path)]).fetchone()[0])
    def _zoom_pool(self,path:Path)->pd.DataFrame:
        policy=self.research.get("forensics",{}).get("candidate_policy",{}); minimum_n=int(policy.get("min_active_n",250)); edge=float(policy.get("min_abs_edge_bps",1.0)); top=int(policy.get("keep_top_k_per_target_resolution",250))
        with duckdb.connect() as con:
            return con.execute("""SELECT * FROM read_parquet(?) WHERE selected_n>=? AND (abs(selected_state_bps)>=? OR abs(selected_interaction_lift_bps)>=?) QUALIFY row_number() OVER(PARTITION BY target_id,v3_resolution ORDER BY greatest(abs(selected_state_bps),abs(selected_interaction_lift_bps)) DESC)<=?""",[str(path),minimum_n,edge,edge,top]).fetchdf()
    def _coverage(self,ledger:Path):
        coverage={}
        with duckdb.connect() as con:
            rows=con.execute("SELECT trial_family_id,status,sum(work_units)::BIGINT FROM read_parquet(?) GROUP BY 1,2",[str(ledger)]).fetchall()
        for family,status,count in rows: coverage.setdefault(family,{})[status]=int(count)
        for values in coverage.values():
            for status in ("executed","reused","structurally_excluded","unavailable","failed"): values.setdefault(status,0)
            values["expected"]=sum(values[x] for x in ("executed","reused","structurally_excluded","unavailable","failed"))
        return coverage
    @staticmethod
    def _verify_evidence_counts(root:Path,resolution_path:Path,specialist_count:int,temporal_count:int):
        audit=json.loads((root/"exhaustiveness_manifest.json").read_text(encoding="utf-8")); expected=int(audit["expected_pair_target_tests"]); resolutions=len(audit.get("resolutions",(3,5,10))); expected_surfaces=expected*resolutions
        with duckdb.connect() as con:
            dual_count=int(con.execute("SELECT count(*) FROM read_parquet(?)",[str(resolution_path)]).fetchone()[0])
        if dual_count!=expected_surfaces or specialist_count!=expected_surfaces or temporal_count!=expected_surfaces:
            raise RuntimeError(f"Evidence count mismatch: expected {expected_surfaces}, dual={dual_count}, specialist={specialist_count}, temporal={temporal_count}")
    def run(self):
        if self.research["periods"]["discovery"]["end"]>="2026-05-01": raise PermissionError("Discovery mode cannot request sealed replication rows")
        source_manifest=build_production_source_manifest(data_root=Path(self.machine["data_root"]),repo_root=self.repo_root); source_hash=source_manifest["source_manifest_hash"]; adapter=LegacyCoreAdapter(self.research,self.machine,self.repo_root,source_hash,self.telemetry); legacy_run,core_results=adapter.execute(); root=legacy_run.root; self._write_json(root/"source_manifest.json",source_manifest)
        resolution_path=root/"v3_diagnostics/dual_resolution_summary.parquet"
        if not self._reusable(root,"resolution_diagnostics",[resolution_path],source_hash): build_resolution_diagnostics(run_root=root,research=self.research); self._mark(root,"resolution_diagnostics",source_hash,{"resolutions":self.research["resolutions"]})
        specialist_path=root/"cell_specialist_summary.parquet"
        if not self._reusable(root,"cell_specialist",[specialist_path],source_hash): build_cell_specialist_summary(legacy_run=legacy_run,dual_path=resolution_path,research=self.research); self._mark(root,"cell_specialist",source_hash,{"surfaces":self._row_count(specialist_path)})
        temporal_path=root/"cell_temporal_summary.parquet"
        if not self._reusable(root,"cell_temporal",[temporal_path],source_hash): build_cell_temporal_summary(legacy_run=legacy_run,dual_path=resolution_path,research=self.research); self._mark(root,"cell_temporal",source_hash,{"surfaces":self._row_count(temporal_path)})
        specialist_count=self._row_count(specialist_path); temporal_count=self._row_count(temporal_path); self._verify_evidence_counts(root,resolution_path,specialist_count,temporal_count); ledger=root/"trial_ledger.parquet"
        if not self._reusable(root,"trial_ledger",[ledger],source_hash): build_production_trial_ledger(legacy_run=legacy_run,dual_path=resolution_path,core_results=core_results,specialist_count=specialist_count,temporal_count=temporal_count); self._mark(root,"trial_ledger",source_hash,{"rows":self._row_count(ledger)})
        coverage=self._coverage(ledger); bundle=root/"analysis_bundle"
        if not self._reusable(root,"analysis_bundle",[bundle/"research.duckdb",bundle/"bundle_manifest.json"],source_hash): build_v3_analysis_bundle(run_root=root,research=self.research,source_manifest_hash=source_hash,trial_coverage=coverage); self._mark(root,"analysis_bundle",source_hash,{"evidence_complete":True})
        self._write_json(root/"EVIDENCE_COMPLETE.json",{"status":"complete","completed_at_utc":datetime.now(timezone.utc).isoformat(),"source_manifest_hash":source_hash,"replication_accessed":False,"final_holdout_accessed":False,"zoom_enabled":bool(self.research.get("zoom",{}).get("enabled",False))})
        zoom={"enabled":False,"variants":0,"candidates":0,"dossiers":0}
        if self.research.get("zoom",{}).get("enabled",False):
            duals=self._zoom_pool(resolution_path); selected_specialist=root/"specialist_summary.parquet"; run_production_specialist_probe(legacy_run=legacy_run,duals=duals,research=self.research); specialist=pd.read_parquet(selected_specialist)
            variants,variant_trials,variant_metrics=execute_variant_expansion(legacy_run=legacy_run,duals=duals,research=self.research); materialization_input=pd.concat([duals,variants],ignore_index=True,sort=False) if len(variants) else duals
            candidates,candidate_summary=materialize_candidates(legacy_run=legacy_run,duals=materialization_input,specialist=specialist,research=self.research,source_manifest_hash=source_hash); dossiers=build_candidate_dossiers(legacy_run=legacy_run,candidates=candidates,candidate_summary=candidate_summary,duals=materialization_input,specialist=specialist)
            build_production_trial_ledger(legacy_run=legacy_run,dual_path=resolution_path,core_results=core_results,variant_trials=variant_trials,specialist_count=specialist_count,temporal_count=temporal_count,candidate_count=len(dossiers)); coverage=self._coverage(ledger); build_v3_analysis_bundle(run_root=root,research=self.research,source_manifest_hash=source_hash,trial_coverage=coverage); zoom={"enabled":True,"variants":variant_metrics.get("planned",0),"candidates":len(candidates),"dossiers":len(dossiers)}; self._mark(root,"zoom",source_hash,zoom)
        return {"core_results":core_results,"resolution_diagnostics":str(resolution_path),"cell_specialist":str(specialist_path),"cell_temporal":str(temporal_path),"trial_ledger":str(ledger),"analysis_bundle":str(bundle),"evidence_complete":True,"zoom":zoom}
