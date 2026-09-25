from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
import json,os
from pathlib import Path
import duckdb,pandas as pd
from quant_pipeline.alpha_discovery.registry import compile_registry
from quant_pipeline.data.source_manifest import build_production_source_manifest
from quant_pipeline.production.bundle import build_v3_analysis_bundle
from quant_pipeline.production.cell_specialist import build_cell_specialist_summary
from quant_pipeline.production.cell_temporal import build_cell_temporal_summary
from quant_pipeline.production.dossiers import build_candidate_dossiers
from quant_pipeline.production.legacy_core import LegacyCoreAdapter
from quant_pipeline.production.materialization import materialization_pool,materialize_candidates
from quant_pipeline.production.resolution_diagnostics import build_resolution_diagnostics
from quant_pipeline.production.specialist_stage import run_production_specialist_probe
from quant_pipeline.production.trials import build_production_trial_ledger
from quant_pipeline.production.variant_scan import execute_variant_expansion
from quant_pipeline.production.zoom_requests import load_resolution_comparison_rows,resolve_explicit_candidate_requests,resolve_explicit_variant_requests,state_key
from quant_pipeline.production.zoom_selection import build_pre_specialist_contenders,finalize_dossier_selection
from quant_pipeline.production.evidence_identity import stage_identity,digest
from quant_pipeline.production.evidence_store import publish_evidence
from quant_pipeline.production.coverage import preflight_comprehensive,plan_storage,plan_coverage,sample_storage,execute_coverage
from quant_pipeline.production.resource_policy import ResourcePolicy
from quant_pipeline.production.research_specs import resolve_research_scope

STAGE_CODE={
    "resolution_diagnostics":("resolution_diagnostics.py","surface_math.py","outputs.py"),
    "cell_specialist":("cell_specialist.py","compatibility_moments.py","outputs.py"),
    "cell_temporal":("cell_temporal.py","compatibility_moments.py","state_helpers.py","outputs.py"),
    "trial_ledger":("trials.py",),
    "analysis_bundle":("bundle.py",),
    "zoom":("variant_scan.py","variant_batches.py","zoom_requests.py","zoom_selection.py","materialization.py","dossiers.py"),
}

class V3ProductionRunner:
    def __init__(self,*,research:dict,machine:dict,repo_root:Path,telemetry):
        self.research=research; self.machine=machine; self.repo_root=Path(repo_root); self.telemetry=telemetry
    @staticmethod
    def _write_json(path:Path,payload):
        path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_suffix(".partial"); temporary.write_text(json.dumps(payload,indent=2,sort_keys=True,default=str),encoding="utf-8"); os.replace(temporary,path)
    def _stage_id(self,name,source_hash,upstream,semantics,observation_id):
        root=self.repo_root/"src/quant_pipeline/production"
        implementation={path:sha256((root/path).read_bytes()).hexdigest() for path in STAGE_CODE[name]}
        return stage_identity(stage=name,sources=source_hash,observation_id=observation_id,
                              upstream=upstream,definitions=semantics,semantics=semantics,
                              implementation=implementation,schema=2,numeric={"return_unit":"decimal","bins":[3,5,10]})
    def _reusable(self,root:Path,name:str,outputs:list[Path],source_hash:str,*,stage_id:str):
        marker=root/"v3_checkpoints"/f"{name}.json"
        if not marker.exists() or not all(path.exists() for path in outputs): return False
        payload=json.loads(marker.read_text()); return payload.get("schema_version")==2 and payload.get("status")=="complete" and payload.get("source_manifest_hash")==source_hash and payload.get("stage_id")==stage_id
    def _mark(self,root:Path,name:str,source_hash:str,metrics:dict,*,stage_id:str):
        self._write_json(root/"v3_checkpoints"/f"{name}.json",{"schema_version":2,"stage":name,"stage_id":stage_id,"status":"complete","completed_at_utc":datetime.now(timezone.utc).isoformat(),"source_manifest_hash":source_hash,"metrics":metrics})
        if self.telemetry:self.telemetry.event("v3_stage_complete",stage=f"v3:{name}",metrics=metrics)
    @staticmethod
    def _row_count(path:Path)->int:
        with duckdb.connect() as con:return int(con.execute("SELECT count(*) FROM read_parquet(?)",[str(path)]).fetchone()[0])
    def _zoom_pool(self,path:Path)->pd.DataFrame:
        policy=self.research.get("forensics",{}).get("candidate_policy",{}); minimum_n=int(policy.get("min_active_n",250)); edge=float(policy.get("min_abs_edge_bps",1.0)); top=int(policy.get("keep_top_k_per_target_resolution",250))
        with duckdb.connect() as con:
            return con.execute("""SELECT * FROM read_parquet(?) WHERE selected_n>=? AND (abs(selected_state_bps)>=? OR abs(selected_interaction_lift_bps)>=?) QUALIFY row_number() OVER(PARTITION BY target_id,v3_resolution ORDER BY greatest(abs(selected_state_bps),abs(selected_interaction_lift_bps)) DESC)<=?""",[str(path),minimum_n,edge,edge,top]).fetchdf()
    @staticmethod
    def _explicit_rule_universe(variants:pd.DataFrame)->pd.DataFrame:
        if variants.empty:return variants.head(0).copy()
        if "explicit_request" in variants:return variants[variants.explicit_request.fillna(False).astype(bool)].copy()
        if "request_id" in variants:return variants[variants.request_id.notna()].copy()
        return variants.head(0).copy()
    def _automatic_materialization_states(self,rows:pd.DataFrame)->pd.DataFrame:
        policy=self.research.get("forensics",{}).get("candidate_policy",{}); return materialization_pool(rows,min_active_n=int(policy.get("min_active_n",250)),min_abs_edge_bps=float(policy.get("min_abs_edge_bps",1.0)),top_k=int(policy.get("keep_top_k_per_target_resolution",250)))
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
        if self.research.get("evidence",{}).get("profile","legacy")=="comprehensive":
            preflight_adapter=LegacyCoreAdapter(self.research,self.machine,self.repo_root,"preflight",self.telemetry)
            preflight_run=preflight_adapter.build_run()
            preflight_scope=getattr(preflight_adapter,"resolved_scope",None) or resolve_research_scope(self.research,
                compile_registry(preflight_run.config),preflight_run.config)
            preflight=preflight_comprehensive(self.repo_root,self.machine,preflight_scope,self.research)
            preflight_root=Path(self.machine["run_root"])/self.research["run_name"]
            self._write_json(preflight_root/"evidence"/"preflight_storage.json",preflight)
            self._write_json(preflight_root/"resolved_research_scope.json",preflight_scope)
            if preflight["status"]=="blocked_storage":
                coverage={"core_complete":False,"mandatory_coverage_complete":False,
                          "materialization_complete_for_policy":False,"status":"blocked_storage",
                          "reason":"No space remains for the configured bounded cache after the disk reserve"}
                self._write_json(preflight_root/"evidence"/"coverage_status.json",coverage)
                return {"evidence_complete":False,"mandatory_coverage_complete":False,"coverage":coverage,
                        "storage_preflight":preflight}
        source_manifest=build_production_source_manifest(data_root=Path(self.machine["data_root"]),repo_root=self.repo_root); source_hash=source_manifest["source_manifest_hash"]; adapter=LegacyCoreAdapter(self.research,self.machine,self.repo_root,source_hash,self.telemetry); legacy_run,core_results=adapter.execute(); root=legacy_run.root; self._write_json(root/"source_manifest.json",source_manifest)
        observation_id=digest({"source":source_hash,"scope":getattr(adapter,"resolved_scope",None),"core_config":legacy_run.config.definition_hash})
        core_checkpoint=root/"checkpoints"/"scan-duals-coarse.json"
        core_id=json.loads(core_checkpoint.read_text(encoding="utf-8")).get("shared_cache_key",legacy_run.config.definition_hash)
        mandatory={"core_complete":True,"mandatory_coverage_complete":False,"materialization_complete_for_policy":False}
        moment_derived=False
        if self.research.get("evidence",{}).get("profile","legacy")=="comprehensive":
            scope=resolve_research_scope(self.research,legacy_run.compile_registry(),legacy_run.config)
            if hasattr(adapter,"resolved_scope"):
                scope=adapter.resolved_scope
            self._write_json(root/"resolved_research_scope.json",scope)
            core_inputs={stage:json.loads((root/"checkpoints"/f"{stage}.json").read_text(encoding="utf-8")).get("shared_cache_key")
                         for stage in ("build-panel","build-features","build-targets","scan-singles","scan-duals-coarse")}
            try:
                reader_path=publish_evidence(legacy_run,scope,core_inputs,self.research)
            except ValueError as error:
                if "Unverified packed-bin observation lineage" not in str(error): raise
                mandatory.update(status="blocked_lineage",error=str(error))
                self._write_json(root/"evidence"/"coverage_status.json",mandatory)
            else:
                reader_manifest=json.loads(reader_path.read_text(encoding="utf-8"))
                previous_plan_path=root/"evidence"/"coverage_plan.json"
                previous_storage_path=root/"evidence"/"storage_plan.json"
                previous_plan=json.loads(previous_plan_path.read_text(encoding="utf-8")) if previous_plan_path.exists() else None
                previous_storage=json.loads(previous_storage_path.read_text(encoding="utf-8")) if previous_storage_path.exists() else None
                storage=plan_storage(reader_manifest,root,self.machine,self.research["resolutions"])
                self._write_json(root/"evidence"/"storage_plan.json",storage)
                if storage["status"]=="admitted_streaming":
                    device=self.machine.get("gpu_device","cuda:0")
                    try:
                        import torch
                        if not torch.cuda.is_available(): device="cpu"
                    except ImportError: device="cpu"
                    max_state_bytes=ResourcePolicy(self.machine).state_budget(device)
                    plan=plan_coverage(root,reader_manifest,self.research["resolutions"],max_state_bytes=max_state_bytes)
                    if (previous_plan and previous_plan.get("stage_id")==plan["stage_id"]
                            and previous_storage and previous_storage.get("representative_tiles")):
                        for key in ("representative_tiles","sampled_density","sampled_compression_ratio",
                                    "sampled_input_bytes_per_second","temporary_bytes_required"):
                            storage[key]=previous_storage[key]
                        self._write_json(root/"evidence"/"storage_plan.json",storage)
                    else:
                        storage=sample_storage(root,reader_manifest,plan,storage,device=device,
                            row_chunk=int(self.research.get("cell_evidence",{}).get("observation_chunk",250000)),
                            max_state_bytes=max_state_bytes)
                    mandatory=execute_coverage(root,reader_manifest,plan,device=device,
                                              row_chunk=int(self.research.get("cell_evidence",{}).get("observation_chunk",250000)),
                                              max_state_bytes=max_state_bytes,cache_bytes=storage["cache_bytes"],
                                              compatibility_minimum=int(self.research.get("specialist",{}).get("min_local_n",20)),
                                              expected_folds=int(legacy_run.config.stability["chronological_folds"]),
                                              compatibility_workers=ResourcePolicy(self.machine).compatibility_workers(),
                                              fused_cuda=bool(self.machine.get("evidence_fused_cuda",False)),
                                              resident_inputs=bool(self.machine.get("evidence_resident_inputs",False)))
                    if mandatory["mandatory_coverage_complete"]:
                        moment_derived=True
                else:
                    mandatory.update(status="blocked_storage",storage_plan=storage)
                    self._write_json(root/"evidence"/"coverage_status.json",mandatory)
            if not mandatory.get("mandatory_coverage_complete"):
                self._write_json(root/"EVIDENCE_COMPLETE.json",{
                    "status":"partial","source_manifest_hash":source_hash,
                    "replication_accessed":False,"final_holdout_accessed":False,
                    "coverage":mandatory,"legacy_meaning":"core only; mandatory subgroup coverage incomplete"})
                return {"core_results":core_results,"evidence_complete":False,
                        "mandatory_coverage_complete":False,"coverage":mandatory}
        resolution_path=root/"v3_diagnostics/dual_resolution_summary.parquet"
        resolution_id=self._stage_id("resolution_diagnostics",source_hash,{"core":core_id},{"resolutions":self.research["resolutions"]},observation_id)
        if not self._reusable(root,"resolution_diagnostics",[resolution_path],source_hash,stage_id=resolution_id): build_resolution_diagnostics(run_root=root,research=self.research); self._mark(root,"resolution_diagnostics",source_hash,{"resolutions":self.research["resolutions"]},stage_id=resolution_id)
        specialist_path=root/"cell_specialist_summary.parquet"
        specialist_id=self._stage_id("cell_specialist",source_hash,{"resolution":resolution_id,"core":core_id},{"specialist":self.research.get("specialist",{}),"folds":legacy_run.config.stability.get("chronological_folds")},observation_id)
        if not self._reusable(root,"cell_specialist",[specialist_path],source_hash,stage_id=specialist_id):
            if not moment_derived: build_cell_specialist_summary(legacy_run=legacy_run,dual_path=resolution_path,research=self.research,stage_id=specialist_id)
            self._mark(root,"cell_specialist",source_hash,{"surfaces":self._row_count(specialist_path)},stage_id=specialist_id)
        temporal_path=root/"cell_temporal_summary.parquet"
        temporal_id=self._stage_id("cell_temporal",source_hash,{"resolution":resolution_id,"core":core_id},{"folds":legacy_run.config.stability.get("chronological_folds")},observation_id)
        if not self._reusable(root,"cell_temporal",[temporal_path],source_hash,stage_id=temporal_id):
            if not moment_derived: build_cell_temporal_summary(legacy_run=legacy_run,dual_path=resolution_path,research=self.research,stage_id=temporal_id)
            self._mark(root,"cell_temporal",source_hash,{"surfaces":self._row_count(temporal_path)},stage_id=temporal_id)
        specialist_count=self._row_count(specialist_path); temporal_count=self._row_count(temporal_path); self._verify_evidence_counts(root,resolution_path,specialist_count,temporal_count); ledger=root/"trial_ledger.parquet"
        ledger_id=self._stage_id("trial_ledger",source_hash,{"resolution":resolution_id,"specialist":specialist_id,"temporal":temporal_id},{"schema":2},observation_id)
        if not self._reusable(root,"trial_ledger",[ledger],source_hash,stage_id=ledger_id): build_production_trial_ledger(legacy_run=legacy_run,dual_path=resolution_path,core_results=core_results,specialist_count=specialist_count,temporal_count=temporal_count); self._mark(root,"trial_ledger",source_hash,{"rows":self._row_count(ledger)},stage_id=ledger_id)
        coverage=self._coverage(ledger); bundle=root/"analysis_bundle"
        bundle_id=self._stage_id("analysis_bundle",source_hash,{"ledger":ledger_id},{"coverage":coverage,"research":self.research},observation_id)
        portable=self.research.get("evidence",{}).get("profile")=="comprehensive" and self.research.get("evidence",{}).get("dossier_policy","on_request")=="on_request"
        if not portable and not self._reusable(root,"analysis_bundle",[bundle/"research.duckdb",bundle/"bundle_manifest.json"],source_hash,stage_id=bundle_id):
            build_v3_analysis_bundle(run_root=root,research=self.research,source_manifest_hash=source_hash,trial_coverage=coverage)
            self._mark(root,"analysis_bundle",source_hash,{"evidence_complete":True},stage_id=bundle_id)
        self._write_json(root/"EVIDENCE_COMPLETE.json",{"status":"complete" if mandatory.get("mandatory_coverage_complete") or self.research.get("evidence",{}).get("profile","legacy")=="legacy" else "partial","completed_at_utc":datetime.now(timezone.utc).isoformat(),"source_manifest_hash":source_hash,"replication_accessed":False,"final_holdout_accessed":False,"zoom_enabled":bool(self.research.get("zoom",{}).get("enabled",False)),"coverage":mandatory,"legacy_meaning":"core and selected summaries only"})
        zoom={"enabled":False,"variants":0,"candidates":0,"dossiers":0}
        if self.research.get("zoom",{}).get("enabled",False):
            duals=self._zoom_pool(resolution_path); selected_specialist=root/"specialist_summary.parquet"; variant_mode=self.research.get("variant_expansion",{}).get("mode","automatic"); resolved_variants=resolve_explicit_variant_requests(legacy_run=legacy_run,canonical_path=resolution_path,research=self.research) if variant_mode in {"explicit","automatic_plus_explicit"} else None
            variants,variant_trials,variant_metrics=execute_variant_expansion(legacy_run=legacy_run,duals=duals,research=self.research,canonical_path=resolution_path,resolved_requests=resolved_variants)
            if variant_metrics.get("failed",0):
                raise RuntimeError(f"Zoom failed {variant_metrics['failed']} variant resolution tasks; inspect variant_trial_ledger.parquet")
            materialization_input=pd.concat([duals,variants],ignore_index=True,sort=False) if len(variants) else duals.copy(); materialization_input["state_key"]=[state_key(x) for x in materialization_input.to_dict("records")]; materialization_input=materialization_input.drop_duplicates("state_key",keep="last"); selection_mode=self.research.get("zoom",{}).get("selection_mode","automatic")
            if selection_mode=="automatic":
                exact_rows=self._automatic_materialization_states(materialization_input); run_production_specialist_probe(legacy_run=legacy_run,duals=exact_rows,research=self.research); specialist=pd.read_parquet(selected_specialist)
            else:
                explicit=resolve_explicit_candidate_requests(legacy_run=legacy_run,canonical_path=resolution_path,variant_duals=variants,research=self.research); requested=self._explicit_rule_universe(variants) if selection_mode=="explicit_plus_rules" else materialization_input.head(0); settings=self.research.get("forensics",{}).get("dossier_selection",{}); context=root/"context_expansion"
                contenders=build_pre_specialist_contenders(candidate_rows=requested,explicit_rows=explicit,settings=settings,output_dir=context); run_production_specialist_probe(legacy_run=legacy_run,duals=contenders,research=self.research); specialist=pd.read_parquet(selected_specialist); exact_rows=finalize_dossier_selection(contenders=contenders,specialist=specialist,settings=settings,output_dir=context)
            candidates,candidate_summary=materialize_candidates(legacy_run=legacy_run,duals=materialization_input,specialist=specialist,research=self.research,source_manifest_hash=source_hash,candidate_rows=exact_rows)
            dossiers=[]
            if self.research.get("evidence",{}).get("dossier_policy","legacy")=="legacy":
                comparison_rows=load_resolution_comparison_rows(canonical_path=resolution_path,variant_duals=variants,candidates=candidate_summary)
                dossiers=build_candidate_dossiers(legacy_run=legacy_run,candidates=candidates,candidate_summary=candidate_summary,duals=comparison_rows,specialist=specialist)
            build_production_trial_ledger(legacy_run=legacy_run,dual_path=resolution_path,core_results=core_results,variant_trials=variant_trials,specialist_count=specialist_count,temporal_count=temporal_count,candidate_count=len(dossiers)); coverage=self._coverage(ledger)
            if not portable: build_v3_analysis_bundle(run_root=root,research=self.research,source_manifest_hash=source_hash,trial_coverage=coverage)
            zoom={"enabled":True,"variants":variant_metrics.get("planned",0),"candidates":len(candidates),"dossiers":len(dossiers)}; zoom_id=self._stage_id("zoom",source_hash,{"bundle":bundle_id},{"zoom":self.research.get("zoom",{}),"variants":self.research.get("variant_expansion",{}),"forensics":self.research.get("forensics",{})},observation_id); self._mark(root,"zoom",source_hash,zoom,stage_id=zoom_id)
        return {"core_results":core_results,"resolution_diagnostics":str(resolution_path),"cell_specialist":str(specialist_path),"cell_temporal":str(temporal_path),"trial_ledger":str(ledger),"analysis_bundle":None if portable else str(bundle),"evidence_catalog":str(root/"evidence"/"catalog.json") if portable else None,"evidence_complete":self.research.get("evidence",{}).get("profile","legacy")=="legacy" or mandatory.get("mandatory_coverage_complete",False),"mandatory_coverage_complete":mandatory.get("mandatory_coverage_complete",False) if self.research.get("evidence",{}).get("profile","legacy")=="comprehensive" else None,"coverage":mandatory,"zoom":zoom}
