"""Resolve exact research definitions before numerical work starts."""
from __future__ import annotations

from .evidence_identity import digest


def _items(registry, name):
    return getattr(registry, name) if hasattr(registry, name) else registry[name]


def resolve_research_scope(research, full_registry, core_config=None):
    features=list(_items(full_registry,"features"))
    targets=list(_items(full_registry,"targets"))
    feature_by_id={item.feature_id:item for item in features}
    target_by_id={item.target_id:item for item in targets}
    selection=research.get("feature_selection")
    if selection is None:
        if core_config is None:
            active_features=features
        else:
            from quant_pipeline.alpha_discovery.run import _initial_feature_scope
            active_features=[]
            for grid in core_config.decision_grids:
                if core_config.decision_grids[grid]:
                    active_features.extend(_initial_feature_scope([item for item in features if item.decision_grid==grid],core_config)[0])
        feature_mode="canonical_defaults"
    else:
        ids=set(selection.get("ids",[]))
        unknown=ids-feature_by_id.keys()
        if unknown: raise ValueError(f"Unknown feature IDs: {sorted(unknown)}")
        concepts=set(selection.get("concepts",[]))
        known_concepts={item.concept_id for item in features}
        if concepts-known_concepts: raise ValueError(f"Unknown concepts: {sorted(concepts-known_concepts)}")
        active_features=[item for item in features if item.feature_id in ids or item.concept_id in concepts]
        for field, attribute in (("families","family"),("scales","scale"),("representations","representation"),("grids","decision_grid")):
            if field in selection:
                allowed=set(selection[field])
                active_features=[item for item in active_features if (getattr(item,attribute).label if attribute=="scale" else getattr(item,attribute)) in allowed]
        if not active_features: raise ValueError("Feature selection resolved to no definitions")
        feature_mode="explicit"
    target_selection=research.get("target_selection")
    if target_selection is None:
        active_targets=targets
        target_mode="canonical_defaults"
    else:
        ids=set(target_selection.get("ids",[]))
        unknown=ids-target_by_id.keys()
        if unknown: raise ValueError(f"Unknown target IDs: {sorted(unknown)}")
        active_targets=[item for item in targets if item.target_id in ids]
        if not active_targets: raise ValueError("Target selection resolved to no definitions")
        target_mode="explicit"
    grid_settings=core_config.decision_grids if core_config is not None else research.get("external_smoke",{}).get("decision_grids",{"intraday_5m":True,"daily_close":True,"preclose_1555":True,"intraday_1m":False})
    grids=[grid for grid,enabled in grid_settings.items() if enabled]
    active_features=[item for item in active_features if item.decision_grid in grids]
    active_targets=[item for item in active_targets if item.decision_grid in grids]
    if not active_features or not active_targets: raise ValueError("No active feature/target definitions in enabled grids")
    return {
        "feature_mode":feature_mode,"target_mode":target_mode,
        "features":[{"id":item.feature_id,"definition_hash":item.definition_hash,"grid":item.decision_grid,"concept":item.concept_id} for item in active_features],
        "targets":[{"id":item.target_id,"definition_hash":item.definition_hash,"grid":item.decision_grid} for item in active_targets],
        "grids":grids,"discovery":research["periods"]["discovery"],
        "reference_universe":research.get("external_smoke",{}).get("universe",{}),
        "resolutions":research["resolutions"],
        "exclusions":[],
    }


def scope_id(scope):
    return digest(scope)


def active_target_ids(config, grid, all_ids):
    selected=config.targets.get("active_target_ids")
    return [target_id for target_id in all_ids if selected is None or target_id in selected]
