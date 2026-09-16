from __future__ import annotations
import json,os,shutil
from pathlib import Path
from quant_pipeline.hashing import content_hash

STAGE_IMPLEMENTATION_VERSION={"build-panel":1,"build-features":1,"build-targets":1,"scan-singles":1,"scan-duals-coarse":1}
STAGE_FILES={
 "build-panel":["alpha_discovery/data/source.py","alpha_discovery/data/snapshot.py","alpha_discovery/data/universe.py","alpha_discovery/data/corporate_actions.py","alpha_discovery/data/panel.py","alpha_discovery/eligibility.py"],
 "build-features":["alpha_discovery/registry.py","alpha_discovery/models.py","alpha_discovery/features/*.py","alpha_discovery/cache/feature_store.py"],
 "build-targets":["alpha_discovery/registry.py","alpha_discovery/models.py","alpha_discovery/targets/*.py","alpha_discovery/cache/target_store.py"],
 "scan-singles":["alpha_discovery/scan/singles.py","alpha_discovery/cache/rank_store.py","alpha_discovery/cache/bin_store.py"],
 "scan-duals-coarse":["alpha_discovery/scan/dual_coarse.py","alpha_discovery/scan/pair_plan.py","alpha_discovery/cache/rank_store.py","alpha_discovery/cache/bin_store.py"]}

def stage_implementation_hash(stage:str,repo_root:Path)->str:
    base=Path(repo_root)/"src/quant_pipeline"; files=[]
    for pattern in STAGE_FILES[stage]: files.extend(base.glob(pattern))
    payload=[]
    for path in sorted(set(files),key=lambda x:x.relative_to(base).as_posix()): payload.append({"path":path.relative_to(base).as_posix(),"sha256":__import__('hashlib').sha256(path.read_bytes()).hexdigest()})
    return content_hash({"stage":stage,"version":STAGE_IMPLEMENTATION_VERSION[stage],"files":payload})

def core_stage_key(*,stage:str,source_manifest_hash:str,semantic_config:dict,implementation_hash:str,input_hashes:dict|None=None)->str:
    return content_hash({"stage":stage,"source_manifest_hash":source_manifest_hash,"semantic_config":semantic_config,"implementation_hash":implementation_hash,"input_hashes":input_hashes or {}})

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
