from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
from .errors import ConfigurationError

def _load(path: Path) -> dict:
    value=yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value,dict): raise ConfigurationError(f"Config must be a mapping: {path}")
    return value

def load_research_config(path: Path) -> dict:
    c=_load(path); p=c.get("periods",{})
    if p.get("discovery",{}).get("end") != "2026-04-30": raise ConfigurationError("Initial V3 discovery must end 2026-04-30")
    if c.get("allow_replication_access") or c.get("allow_final_holdout_access"): raise ConfigurationError("Normal discovery config may not authorize sealed access")
    if c.get("resolutions") != [3,5,10]: raise ConfigurationError("V3 requires independent r3/r5/r10")
    if c.get("discovery",{}).get("single_parent_gate",True): raise ConfigurationError("Singles may not gate canonical duals")
    return c

def load_machine_config(path: Path) -> dict:
    c=_load(path)
    for k in ("data_root","source_catalog","cache_root","run_root","scratch_root","duckdb_temp"):
        if k not in c: raise ConfigurationError(f"Missing machine config key: {k}")
    source=Path(c["data_root"]).resolve()
    owned=[Path(c[k]).resolve() for k in ("cache_root","run_root","scratch_root")]
    if any(x==source or source in x.parents for x in owned): raise ConfigurationError("Generated V3 paths may not be inside data_root")
    return c

