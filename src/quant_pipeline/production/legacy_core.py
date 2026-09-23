from __future__ import annotations
import json,threading
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from quant_pipeline.alpha_discovery.run import AlphaDiscoveryRun
from quant_pipeline.alpha_discovery.resources import configured_feature_worker_cap
from quant_pipeline.ported_pipeline import ported_config
from quant_pipeline.production.cache_keys import SharedStageCache,core_stage_key,stage_implementation_hash
from quant_pipeline.production.research_specs import resolve_research_scope
from quant_pipeline.alpha_discovery.registry import compile_registry
from quant_pipeline.telemetry import ResourcePlan,StallWatchdog,run_with_resource_recovery

LOW_LEVEL_STAGES=("validate-config","snapshot","build-panel","compile-registry","build-features","build-targets","scan-singles","scan-duals-coarse","scan-duals-fine","exact-duals","audit-exhaustiveness")
CACHEABLE=set(("build-panel","build-features","build-targets","scan-singles","scan-duals-coarse"))

@dataclass
class LegacyCoreAdapter:
    research:dict; machine:dict; repo_root:Path; source_manifest_hash:str; telemetry:object|None=None
    def build_run(self):
        cfg=ported_config(self.research,self.machine,self.repo_root); cfg.validate()
        if "feature_selection" in self.research or "target_selection" in self.research:
            scope=resolve_research_scope(self.research,compile_registry(cfg))
            if "feature_selection" in self.research:
                feature_ids=[item["id"] for item in scope["features"]]
                cfg=replace(cfg,feature_search={**cfg.feature_search,"feature_ids":feature_ids,"initial_scope":"all_features"},
                            duals={**cfg.duals,"feature_ids":feature_ids,"search_scope":"all_features"})
            if "target_selection" in self.research:
                cfg=replace(cfg,targets={**cfg.targets,"active_target_ids":[item["id"] for item in scope["targets"]]})
            feature_grids={item["grid"] for item in scope["features"]}
            target_grids={item["grid"] for item in scope["targets"]}
            enabled_grids=feature_grids & target_grids
            cfg=replace(cfg,decision_grids={grid:bool(enabled and grid in enabled_grids) for grid,enabled in cfg.decision_grids.items()})
            scope["grids"]=[grid for grid in scope["grids"] if grid in enabled_grids]
            scope["features"]=[item for item in scope["features"] if item["grid"] in enabled_grids]
            scope["targets"]=[item for item in scope["targets"] if item["grid"] in enabled_grids]
            self.resolved_scope=scope
        return AlphaDiscoveryRun(cfg)
    def _semantic(self,run,stage):
        c=run.config
        common={"periods":{"start":c.research_periods.discovery_start,"end":c.research_periods.discovery_end},"grids":c.decision_grids,"universe":c.universe}
        if stage=="build-panel": common|={"warmup":c.warmup,"snapshot_start":c.warmup.get("snapshot_start"),"auto_derive_transitive_history":c.warmup.get("auto_derive_transitive_history"),"safety_margin_sessions":c.warmup.get("safety_margin_sessions")}
        if stage=="build-features": common|={"feature_windows":c.feature_windows,"feature_search":c.feature_search}
        elif stage=="build-targets": common|={"targets":c.targets}
        elif stage in {"scan-singles","scan-duals-coarse"}: common|={"features":c.feature_windows,"targets":c.targets,"duals":c.duals,"stability_folds":c.stability.get("chronological_folds")}
        return common
    @staticmethod
    def _rebase_restored_stage_metadata(run,stage):
        if stage!="scan-duals-coarse": return
        path=run.root/"cache/fused_dual_scan.json"; manifest=json.loads(path.read_text(encoding="utf-8")); manifest["config_hash"]=run.config.definition_hash; manifest["implementation_hash"]=run.implementation_hash
        run._atomic_json("cache/fused_dual_scan.json",manifest)
    def execute(self):
        run=self.build_run(); run.initialize(); source_marker=run.root/"core_source_manifest.json"
        if hasattr(self,"resolved_scope"):
            run._atomic_json("resolved_research_scope.json",self.resolved_scope)
        if source_marker.exists() and json.loads(source_marker.read_text()).get("source_manifest_hash")!=self.source_manifest_hash:
            raise RuntimeError("Source manifest changed for this run; choose a new run_name to preserve committed evidence")
        source_marker.write_text(json.dumps({"source_manifest_hash":self.source_manifest_hash},sort_keys=True),encoding="utf-8"); results=[]; cache=SharedStageCache(Path(self.machine["cache_root"])); keys={}; abort=threading.Event(); run.abort_requested=abort
        if self.telemetry: run.progress_callback=lambda unit,completed,expected:self.telemetry.progress(f"core:{unit}",completed,expected)
        for index,stage in enumerate(LOW_LEVEL_STAGES):
            if self.telemetry:self.telemetry.progress(f"core:{stage}",index,len(LOW_LEVEL_STAGES))
            reused=False
            if stage in CACHEABLE:
                dependencies={"build-panel":{},"build-features":{"panel":keys.get("build-panel")},"build-targets":{"panel":keys.get("build-panel")},"scan-singles":{"features":keys.get("build-features"),"targets":keys.get("build-targets")},"scan-duals-coarse":{"features":keys.get("build-features"),"targets":keys.get("build-targets")}}[stage]
                key=core_stage_key(stage=stage,source_manifest_hash=self.source_manifest_hash,semantic_config=self._semantic(run,stage),implementation_hash=stage_implementation_hash(stage,self.repo_root),input_hashes=dependencies); keys[stage]=key
                cached_result=cache.restore(stage,key,run.root)
                reused=cached_result is not None
                if reused:
                    self._rebase_restored_stage_metadata(run,stage)
                    payload={**cached_result,"stage":stage,"status":"complete","completed_at":datetime.now(timezone.utc).isoformat(),"config_hash":run.config.definition_hash,"implementation_hash":run.implementation_hash,"shared_cache_reused":True,"shared_cache_key":key}
                    run._atomic_json(f"checkpoints/{stage}.json",payload); result=payload
                else:
                    def attempt(plan):
                        abort.clear(); run.runtime_pair_cap=plan.tile_pairs; run.runtime_worker_cap=plan.workers
                        operation=lambda:run.execute(stage)
                        if self.telemetry:
                            watchdog=StallWatchdog(run.root,int(self.machine.get("stall_seconds",900)))
                            operation=lambda op=operation:watchdog.run(op,abort_event=abort,on_stall=lambda details:self.telemetry.event("stall_detected",stage=f"core:{stage}",details=details),poll_seconds=float(self.machine.get("watchdog_poll_seconds",30)))
                        return operation()
                    initial_plan_workers=configured_feature_worker_cap(run.config.compute)
                    result=run_with_resource_recovery(attempt,ResourcePlan(tile_pairs=int(self.machine.get("pair_cap",8192)),workers=initial_plan_workers),on_retry=lambda exc,plan:self.telemetry.event("resource_retry",stage=f"core:{stage}",error=str(exc),tile_pairs=plan.tile_pairs,workers=plan.workers) if self.telemetry else None)
                    cache.publish(stage,key,run.root,result); result={**result,"shared_cache_reused":False,"shared_cache_key":key}
                    run._atomic_json(f"checkpoints/{stage}.json",result)
            else: result=run.execute(stage)
            results.append(result)
            if self.telemetry:self.telemetry.progress(f"core:{stage}",index+1,len(LOW_LEVEL_STAGES))
        return run,results
