from __future__ import annotations
import json,shutil
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from quant_pipeline.alpha_discovery.run import AlphaDiscoveryRun
from quant_pipeline.ported_pipeline import ported_config
from quant_pipeline.production.cache_keys import STAGE_PATHS,SharedStageCache,core_stage_key

LOW_LEVEL_STAGES=("validate-config","snapshot","build-panel","compile-registry","build-features","build-targets","scan-singles","scan-duals-coarse","scan-duals-fine","exact-duals","audit-exhaustiveness")
CACHEABLE=set(("build-panel","build-features","build-targets","scan-singles","scan-duals-coarse"))

@dataclass
class LegacyCoreAdapter:
    research:dict; machine:dict; repo_root:Path; source_manifest_hash:str; telemetry:object|None=None
    def build_run(self):
        cfg=ported_config(self.research,self.machine,self.repo_root); cfg.validate(); return AlphaDiscoveryRun(cfg)
    def _semantic(self,run,stage):
        c=run.config
        common={"periods":{"start":c.research_periods.discovery_start,"end":c.research_periods.discovery_end},"grids":c.decision_grids,"universe":c.universe}
        if stage=="build-features": common|={"feature_windows":c.feature_windows,"feature_search":c.feature_search}
        elif stage=="build-targets": common|={"targets":c.targets}
        elif stage in {"scan-singles","scan-duals-coarse"}: common|={"features":c.feature_windows,"targets":c.targets,"duals":c.duals,"stability_folds":c.stability.get("chronological_folds")}
        return common
    def execute(self):
        run=self.build_run(); run.initialize(); source_marker=run.root/"core_source_manifest.json"
        if source_marker.exists() and json.loads(source_marker.read_text()).get("source_manifest_hash")!=self.source_manifest_hash:
            for paths in STAGE_PATHS.values():
                for relative in paths:
                    target=run.root/relative
                    if target.is_dir():shutil.rmtree(target)
                    elif target.exists():target.unlink()
            for target in (run.root/"checkpoints",run.root/"v3_checkpoints",run.root/"v3_diagnostics",run.root/"candidates",run.root/"analysis_bundle",run.root/"variant_results"):
                if target.is_dir():shutil.rmtree(target)
            for name in ("specialist_summary.parquet","variant_summary.parquet","variant_trial_ledger.parquet","variant_metrics.json","edge_registry.parquet","candidate_summary.parquet","trial_ledger.parquet"):(run.root/name).unlink(missing_ok=True)
        source_marker.write_text(json.dumps({"source_manifest_hash":self.source_manifest_hash},sort_keys=True),encoding="utf-8"); results=[]; cache=SharedStageCache(Path(self.machine["cache_root"])); run_key_hash=run.implementation_hash
        for index,stage in enumerate(LOW_LEVEL_STAGES):
            if self.telemetry:self.telemetry.progress(f"core:{stage}",index,len(LOW_LEVEL_STAGES))
            reused=False
            if stage in CACHEABLE:
                key=core_stage_key(stage=stage,source_manifest_hash=self.source_manifest_hash,semantic_config=self._semantic(run,stage),implementation_hash=run_key_hash)
                cached_result=cache.restore(stage,key,run.root)
                reused=cached_result is not None
                if reused:
                    payload={**cached_result,"stage":stage,"status":"complete","completed_at":datetime.now(timezone.utc).isoformat(),"config_hash":run.config.definition_hash,"implementation_hash":run.implementation_hash,"shared_cache_reused":True,"shared_cache_key":key}
                    run._atomic_json(f"checkpoints/{stage}.json",payload); result=payload
                else:
                    result=run.execute(stage); cache.publish(stage,key,run.root,result); result={**result,"shared_cache_reused":False,"shared_cache_key":key}
            else: result=run.execute(stage)
            results.append(result)
            if self.telemetry:self.telemetry.progress(f"core:{stage}",index+1,len(LOW_LEVEL_STAGES))
        return run,results
