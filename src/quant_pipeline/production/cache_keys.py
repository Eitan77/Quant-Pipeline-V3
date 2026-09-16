from __future__ import annotations
import json,os,shutil
from pathlib import Path
from quant_pipeline.hashing import content_hash

def core_stage_key(*,stage:str,source_manifest_hash:str,semantic_config:dict,implementation_hash:str)->str:
    return content_hash({"stage":stage,"source_manifest_hash":source_manifest_hash,"semantic_config":semantic_config,"implementation_hash":implementation_hash})

def _link_tree(source:Path,destination:Path):
    for path in source.rglob("*"):
        relative=path.relative_to(source); target=destination/relative
        if path.is_dir(): target.mkdir(parents=True,exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            try: os.link(path,target)
            except OSError: shutil.copy2(path,target)

STAGE_PATHS={
    "build-panel":("cache/calculation_panels","cache/panels","cache/indexes"),
    "build-features":("cache/features","cache/local_feature_panels","feature_registry.parquet"),
    "build-targets":("cache/targets","cache/target_store","target_registry.parquet"),
    "scan-singles":("single_results","cache/bins"),
    "scan-duals-coarse":("dual_coarse_results","dual_fine_results","dual_exact_results","dual_trial_ledger","cache/pair_plans","cache/fused_dual_scan.json"),
}

class SharedStageCache:
    def __init__(self,root:Path): self.root=Path(root)/"production_core"; self.root.mkdir(parents=True,exist_ok=True)
    def path(self,stage,key): return self.root/stage/key
    def restore(self,stage,key,run_root:Path):
        source=self.path(stage,key); manifest=source/"manifest.json"
        if not manifest.exists(): return None
        for relative in STAGE_PATHS.get(stage,()):
            cached=source/"artifacts"/relative; destination=Path(run_root)/relative
            if cached.is_dir(): _link_tree(cached,destination)
            elif cached.exists() and not destination.exists(): destination.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(cached,destination)
        return json.loads(manifest.read_text(encoding="utf-8")).get("result",{})
    def publish(self,stage,key,run_root:Path,result:dict):
        destination=self.path(stage,key)
        if (destination/"manifest.json").exists(): return
        partial=destination.with_name(destination.name+".partial")
        if partial.exists(): shutil.rmtree(partial)
        for relative in STAGE_PATHS.get(stage,()):
            source=Path(run_root)/relative; target=partial/"artifacts"/relative
            if source.is_dir(): _link_tree(source,target)
            elif source.exists(): target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target)
        partial.mkdir(parents=True,exist_ok=True); (partial/"manifest.json").write_text(json.dumps({"stage":stage,"key":key,"status":"complete","result":result},sort_keys=True,default=str),encoding="utf-8")
        destination.parent.mkdir(parents=True,exist_ok=True); os.replace(partial,destination)
