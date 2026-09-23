from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml
from .errors import ConfigurationError
from .production.state_helpers import validate_discovery_subrange

DISCOVERY_ENVELOPE={"start":"2025-05-01","end":"2026-04-30"}

def _load(path: Path) -> dict:
    value=yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value,dict): raise ConfigurationError(f"Config must be a mapping: {path}")
    return value

def load_research_config(path: Path) -> dict:
    c=_load(path); p=c.get("periods",{})
    try: validate_discovery_subrange(p["discovery"],DISCOVERY_ENVELOPE)
    except (KeyError,ValueError,TypeError) as error: raise ConfigurationError(f"Invalid governed discovery range: {error}") from error
    if c.get("allow_replication_access") or c.get("allow_final_holdout_access"): raise ConfigurationError("Normal discovery config may not authorize sealed access")
    if c.get("resolutions") != [3,5,10]: raise ConfigurationError("V3 requires independent r3/r5/r10")
    if c.get("discovery",{}).get("single_parent_gate",True): raise ConfigurationError("Singles may not gate canonical duals")
    for selector_name in ("feature_selection","target_selection"):
        if selector_name in c:
            selector=c[selector_name]
            allowed={"ids","concepts","families","scales","representations","grids"} if selector_name=="feature_selection" else {"ids"}
            if not isinstance(selector,dict) or set(selector)-allowed or any(not isinstance(value,list) or any(not isinstance(item,str) for item in value) for value in selector.values()):
                raise ConfigurationError(f"Invalid {selector_name}")
            if not any(selector.values()): raise ConfigurationError(f"{selector_name} resolves to an empty selection")
    if "evidence" in c:
        evidence=c["evidence"]
        allowed={"profile","mandatory_groupings","condition_definitions","condition_groupings","retention","dossier_policy"}
        if not isinstance(evidence,dict) or set(evidence)-allowed: raise ConfigurationError("Unsupported evidence field")
        if evidence.get("profile","comprehensive") not in {"comprehensive","legacy"}: raise ConfigurationError("Unsupported evidence profile")
        if evidence.get("retention","budgeted") not in {"budgeted","durable"}: raise ConfigurationError("Unsupported evidence retention")
        if evidence.get("dossier_policy","on_request") not in {"on_request","legacy"}: raise ConfigurationError("Unsupported dossier policy")
        conditions=evidence.get("condition_definitions",[])
        if not isinstance(conditions,list): raise ConfigurationError("condition_definitions must be a list")
        names=set()
        for definition in conditions:
            if not isinstance(definition,dict) or set(definition)-{"id","source","feature_id","cutpoints","labels","missing"}:
                raise ConfigurationError("Invalid condition definition")
            name=definition.get("id")
            if not isinstance(name,str) or not name.startswith("condition_") or name in names:
                raise ConfigurationError("Condition IDs must be unique and start with condition_")
            names.add(name)
            if definition.get("source") not in {"decision_minute","feature_decile"}:
                raise ConfigurationError("Conditions require a known-at-decision source")
            if definition["source"]=="feature_decile" and not isinstance(definition.get("feature_id"),str):
                raise ConfigurationError("feature_decile conditions require feature_id")
            cuts=definition.get("cutpoints")
            if not isinstance(cuts,list) or any(not isinstance(x,(int,float)) or isinstance(x,bool) for x in cuts) or cuts!=sorted(set(cuts)):
                raise ConfigurationError("Condition cutpoints must be strictly ordered numbers")
            if not isinstance(definition.get("labels"),list) or len(definition["labels"])!=len(cuts)+1 or any(not isinstance(x,str) for x in definition["labels"]):
                raise ConfigurationError("Condition labels must match the cutpoint intervals")
            if definition.get("missing","unavailable") not in {"unavailable","category"}:
                raise ConfigurationError("Invalid condition missing policy")
        groupings=evidence.get("mandatory_groupings",[])+evidence.get("condition_groupings",[])
        if not isinstance(groupings,list) or any(not isinstance(group,list) or not group or len(set(group))!=len(group) or any(key not in {"security","month","fold","time_bucket"}|names for key in group) for group in groupings):
            raise ConfigurationError("Invalid mandatory_groupings")
    zoom=c.get("zoom",{}); selection_mode=zoom.get("selection_mode","automatic")
    if selection_mode not in {"automatic","explicit","explicit_plus_rules"}: raise ConfigurationError("zoom.selection_mode must be automatic, explicit, or explicit_plus_rules")
    expansion=c.get("variant_expansion",{}); variant_mode=expansion.get("mode","automatic")
    if variant_mode not in {"automatic","explicit","automatic_plus_explicit"}: raise ConfigurationError("variant_expansion.mode must be automatic, explicit, or automatic_plus_explicit")
    explicit_variants=expansion.get("explicit_requests",[])
    if not isinstance(explicit_variants,list): raise ConfigurationError("variant_expansion.explicit_requests must be a list")
    for index,item in enumerate(explicit_variants):
        required={"source_feature_a","source_feature_b","feature_a","feature_b","target_id","family","role"}
        if not isinstance(item,dict) or required-set(item): raise ConfigurationError(f"Explicit variant request {index} is missing required fields")
    forensics=c.get("forensics",{}); explicit_candidates=forensics.get("explicit_candidates",[])
    if not isinstance(explicit_candidates,list): raise ConfigurationError("forensics.explicit_candidates must be a list")
    for index,item in enumerate(explicit_candidates):
        required={"feature_a","feature_b","target_id","resolution","cell_mode","direction_mode","family","role"}
        if not isinstance(item,dict) or required-set(item): raise ConfigurationError(f"Explicit candidate {index} is missing required fields")
        if item["resolution"] not in {3,5,10}: raise ConfigurationError(f"Explicit candidate {index} has invalid resolution")
        if item["cell_mode"] not in {"scanner_selected","explicit"}: raise ConfigurationError(f"Explicit candidate {index} has invalid cell_mode")
        if item["direction_mode"] not in {"auto","descriptive"}: raise ConfigurationError(f"Explicit candidate {index} has invalid direction_mode")
        if item["cell_mode"]=="explicit" and item.get("cell_index") is None: raise ConfigurationError(f"Explicit candidate {index} requires cell_index")
        if item["cell_mode"]=="explicit" and (not isinstance(item["cell_index"],int) or isinstance(item["cell_index"],bool) or not 0<=item["cell_index"]<item["resolution"]**2): raise ConfigurationError(f"Explicit candidate {index} has invalid cell_index")
    dossier=forensics.get("dossier_selection",{})
    if "enabled" in dossier and not isinstance(dossier["enabled"],bool): raise ConfigurationError("forensics.dossier_selection.enabled must be boolean")
    for key in ("max_dynamic_dossiers","pre_specialist_per_family"):
        if key in dossier and (not isinstance(dossier[key],int) or dossier[key]<0): raise ConfigurationError(f"forensics.dossier_selection.{key} must be a nonnegative integer")
    return c

def load_machine_config(path: Path) -> dict:
    c=_load(path)
    for k in ("data_root","source_catalog","cache_root","run_root","scratch_root","duckdb_temp"):
        if k not in c: raise ConfigurationError(f"Missing machine config key: {k}")
    source=Path(c["data_root"]).resolve()
    owned=[Path(c[k]).resolve() for k in ("cache_root","run_root","scratch_root")]
    if any(x==source or source in x.parents for x in owned): raise ConfigurationError("Generated V3 paths may not be inside data_root")
    return c
