from dataclasses import dataclass
from pathlib import Path
from .contracts import RunMode
@dataclass(frozen=True,slots=True)
class RunPaths: repo_root:Path; data_root:Path; cache_root:Path; run_root:Path; scratch_root:Path; duckdb_temp:Path
@dataclass(slots=True)
class RunContext:
    run_id:str; mode:RunMode; research_config:dict; machine_config:dict; source_snapshot_hash:str; implementation_hash:str; paths:RunPaths; artifacts:object; telemetry:object; registry:object=None; governance:object=None

