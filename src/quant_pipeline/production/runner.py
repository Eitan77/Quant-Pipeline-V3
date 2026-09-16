from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
import json,os
from pathlib import Path
import pandas as pd
from quant_pipeline.data.source_manifest import build_production_source_manifest
from quant_pipeline.production.bundle import build_v3_analysis_bundle
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
        paths=list((package/"production").glob("*.py"))+list((package/"forensics").glob("*.py"))+list((package/"candidates").glob("*.py"))+[package/"alpha_discovery/targets/excursions.py",package/"data/source_manifest.py"]
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
    def run(self):
        if self.research["periods"]["discovery"]["end"]>="2026-05-01": raise PermissionError("Discovery mode cannot request sealed replication rows")
        source_manifest=build_production_source_manifest(data_root=Path(self.machine["data_root"]),repo_root=self.repo_root); source_hash=source_manifest["source_manifest_hash"]; adapter=LegacyCoreAdapter(self.research,self.machine,self.repo_root,source_hash,self.telemetry); legacy_run,core_results=adapter.execute(); root=legacy_run.root; self._write_json(root/"source_manifest.json",source_manifest)
        resolution_path=root/"v3_diagnostics/dual_resolution_summary.parquet"
        if not self._reusable(root,"resolution_diagnostics",[resolution_path],source_hash): build_resolution_diagnostics(run_root=root,research=self.research); self._mark(root,"resolution_diagnostics",source_hash,{"resolutions":self.research["resolutions"]})
        duals=pd.read_parquet(resolution_path); specialist_path=root/"specialist_summary.parquet"
        if not self._reusable(root,"specialist_probe",[specialist_path],source_hash): run_production_specialist_probe(legacy_run=legacy_run,duals=duals,research=self.research); self._mark(root,"specialist_probe",source_hash,{"rows":len(pd.read_parquet(specialist_path))})
        specialist=pd.read_parquet(specialist_path); variant_outputs=[root/"variant_summary.parquet",root/"variant_trial_ledger.parquet",root/"variant_metrics.json"]
        if not self._reusable(root,"variant_expansion",variant_outputs,source_hash): variants,variant_trials,variant_metrics=execute_variant_expansion(legacy_run=legacy_run,duals=duals,research=self.research); self._mark(root,"variant_expansion",source_hash,variant_metrics)
        else: variants=pd.read_parquet(variant_outputs[0]); variant_trials=pd.read_parquet(variant_outputs[1]); variant_metrics=json.loads(variant_outputs[2].read_text())
        materialization_input=pd.concat([duals,variants],ignore_index=True,sort=False) if len(variants) else duals; candidate_outputs=[root/"edge_registry.parquet",root/"candidate_summary.parquet"]
        if not self._reusable(root,"candidate_materialization",candidate_outputs,source_hash): candidates,candidate_summary=materialize_candidates(legacy_run=legacy_run,duals=materialization_input,specialist=specialist,research=self.research,source_manifest_hash=source_hash); self._mark(root,"candidate_materialization",source_hash,{"candidates":len(candidates)})
        else: candidates=pd.read_parquet(candidate_outputs[0]); candidate_summary=pd.read_parquet(candidate_outputs[1])
        dossier_root=root/"candidates"
        if not self._reusable(root,"dossiers",[dossier_root],source_hash): dossiers=build_candidate_dossiers(legacy_run=legacy_run,candidates=candidates,candidate_summary=candidate_summary,duals=materialization_input,specialist=specialist); self._mark(root,"dossiers",source_hash,{"dossiers":len(dossiers)})
        else: dossiers=[path.parent.parent.name for path in dossier_root.glob("*/dossier/dossier.json")]
        ledger=root/"trial_ledger.parquet"
        if not self._reusable(root,"trial_ledger",[ledger],source_hash): build_production_trial_ledger(legacy_run=legacy_run,duals=duals,core_results=core_results,variant_trials=variant_trials,specialist_count=len(specialist),candidate_count=len(dossiers)); self._mark(root,"trial_ledger",source_hash,{"rows":len(pd.read_parquet(ledger))})
        trials=pd.read_parquet(ledger); coverage={}
        for family,part in trials.groupby("trial_family_id"):
            by=part.groupby("status").work_units.sum().to_dict(); coverage[family]={k:int(by.get(k,0)) for k in ("executed","reused","structurally_excluded","unavailable","failed")}; coverage[family]["expected"]=sum(coverage[family].values())
        audit=json.loads((root/"exhaustiveness_manifest.json").read_text()); declared={"canonical_singles":int(audit["expected_single_tests"]),**{f"canonical_dual_r{r}":int(audit["expected_pair_target_tests"]) for r in self.research["resolutions"]},"variant_expansion":len(variant_trials),"specialist_followup":len(specialist),"dossiers":len(dossiers)}; excluded_scope=sum(int(x) for x in audit.get("dual_exclusions_by_reason",{}).values())
        if excluded_scope: declared["canonical_dual_exclusions"]=excluded_scope
        for family,expected in declared.items():
            actual=sum(coverage.get(family,{}).get(k,0) for k in ("executed","reused","structurally_excluded","unavailable","failed"))
            if actual!=expected: raise RuntimeError(f"Trial reconciliation failed for {family}: expected {expected}, got {actual}")
            coverage.setdefault(family,{})["expected"]=expected
        bundle=root/"analysis_bundle"
        if not self._reusable(root,"analysis_bundle",[bundle/"research.duckdb",bundle/"bundle_manifest.json"],source_hash): build_v3_analysis_bundle(run_root=root,research=self.research,source_manifest_hash=source_hash,trial_coverage=coverage); self._mark(root,"analysis_bundle",source_hash,{"candidate_count":len(candidates),"dossier_count":len(dossiers)})
        return {"core_results":core_results,"resolution_diagnostics":str(resolution_path),"trial_ledger":str(ledger),"specialist":str(specialist_path),"variants":variant_metrics,"candidates":len(candidates),"dossiers":len(dossiers),"analysis_bundle":str(bundle)}
