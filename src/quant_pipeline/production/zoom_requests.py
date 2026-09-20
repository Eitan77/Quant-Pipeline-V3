from __future__ import annotations
from pathlib import Path
import json
import duckdb,pandas as pd
from quant_pipeline.alpha_discovery.scan.dual_pairs import pair_id
from quant_pipeline.hashing import content_hash
from quant_pipeline.production.surface_math import reselect_surface_cell

def state_key(row:dict)->str:
    payload={key:row[key] for key in ("pair_id","feature_a","feature_b","target_id")}
    payload["resolution"]=int(row.get("v3_resolution",row.get("resolution"))); payload["selected_cell"]=int(row["selected_cell"])
    return "state_"+content_hash(payload)[:24]

def _registries(legacy_run):
    bundle=legacy_run.compile_registry(); return ({x.feature_id:x for x in bundle.features},{x.target_id:x for x in bundle.targets})

def _validate_ids(request,features,targets):
    for name in ("source_feature_a","source_feature_b","feature_a","feature_b"):
        if name in request and request[name] not in features: raise ValueError(f"Unknown feature_id {request[name]!r} in {name}")
    target=request["target_id"]
    if target not in targets: raise ValueError(f"Unknown target_id {target!r}")
    grids={features[request[name]].decision_grid for name in ("source_feature_a","source_feature_b","feature_a","feature_b") if name in request}
    target_grid=targets[target].decision_grid
    if len(grids)!=1 or target_grid not in grids: raise ValueError(f"Incompatible decision grids for {request['feature_a']}, {request['feature_b']}, {target}")

def load_canonical_rows(*,canonical_path:Path|None,requests:pd.DataFrame,all_resolutions:bool=False)->pd.DataFrame:
    """Load only requested canonical pair/target rows, including surfaces."""
    if requests.empty:return pd.DataFrame()
    resolution_column="resolution" if "resolution" in requests else "v3_resolution" if "v3_resolution" in requests else None
    columns=["pair_id","target_id"]+([] if all_resolutions or resolution_column is None else [resolution_column]); keys=requests[columns].drop_duplicates().copy()
    if not all_resolutions and resolution_column is not None: keys=keys.rename(columns={resolution_column:"requested_resolution"})
    if canonical_path is None: raise ValueError("canonical_path is required for canonical evidence lookup")
    with duckdb.connect() as con:
        con.register("requested_keys",keys)
        resolution_join="" if all_resolutions or resolution_column is None else " AND d.v3_resolution=CAST(k.requested_resolution AS INTEGER)"
        return con.execute(f"SELECT d.* FROM read_parquet(?) d INNER JOIN requested_keys k ON d.pair_id=k.pair_id AND d.target_id=k.target_id{resolution_join}",[str(canonical_path)]).fetchdf()

def canonical_existing_keys(*,canonical_path:Path,requests:pd.DataFrame)->set[tuple[str,str]]:
    if requests.empty:return set()
    keys=requests[["pair_id","target_id"]].drop_duplicates()
    with duckdb.connect() as con:
        con.register("requested_keys",keys); rows=con.execute("SELECT DISTINCT d.pair_id,d.target_id FROM read_parquet(?) d INNER JOIN requested_keys k ON d.pair_id=k.pair_id AND d.target_id=k.target_id",[str(canonical_path)]).fetchall()
    return {(str(pair),str(target)) for pair,target in rows}

def resolve_explicit_variant_requests(*,legacy_run,canonical_path:Path,research:dict)->pd.DataFrame:
    requests=research.get("variant_expansion",{}).get("explicit_requests",[]); features,targets=_registries(legacy_run); grouped={}
    for position,raw in enumerate(requests):
        item=dict(raw); _validate_ids(item,features,targets); item["feature_a"],item["feature_b"]=sorted((item["feature_a"],item["feature_b"])); item["source_feature_a"],item["source_feature_b"]=sorted((item["source_feature_a"],item["source_feature_b"]))
        key=(item["feature_a"],item["feature_b"],item["target_id"]); entry=grouped.setdefault(key,{**item,"families":[],"roles":[],"request_positions":[]}); entry["families"].append(item["family"]); entry["roles"].append(item["role"]); entry["request_positions"].append(position)
    rows=[]
    for (a,b,target),item in grouped.items():
        item["families"]=sorted(set(item["families"])); item["roles"]=sorted(set(item["roles"])); item["family"]="|".join(item["families"]); item["role"]="|".join(item["roles"]); item["pair_id"]=pair_id(a,b); item["source_pair_id"]=pair_id(item["source_feature_a"],item["source_feature_b"]); item["request_id"]="variant_request_"+content_hash({"feature_a":a,"feature_b":b,"target_id":target})[:20]
        item["execution_status"]="pending"; rows.append(item)
    existence_keys=pd.DataFrame([{"pair_id":x["pair_id"],"target_id":x["target_id"]} for x in rows]); existing_keys=canonical_existing_keys(canonical_path=canonical_path,requests=existence_keys)
    for item in rows:item["canonical_existing"]=(item["pair_id"],item["target_id"]) in existing_keys
    columns=["request_id","source_pair_id","source_feature_a","source_feature_b","feature_a","feature_b","target_id","family","role","families","roles","request_positions","pair_id","canonical_existing","execution_status"]
    frame=pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns); out=Path(legacy_run.root)/"context_expansion"; out.mkdir(parents=True,exist_ok=True); frame.to_parquet(out/"resolved_variant_requests.parquet",index=False); (out/"resolved_variant_requests.json").write_text(json.dumps(frame.to_dict("records"),indent=2,default=str),encoding="utf-8"); return frame

def resolve_explicit_candidate_requests(*,legacy_run,canonical_path:Path,variant_duals:pd.DataFrame,research:dict)->pd.DataFrame:
    requests=research.get("forensics",{}).get("explicit_candidates",[]); features,targets=_registries(legacy_run); validated=[]
    for position,raw in enumerate(requests):
        item=dict(raw); _validate_ids(item,features,targets); item["_position"]=position; item["pair_id"]=pair_id(item["feature_a"],item["feature_b"]); validated.append(item)
    keys=pd.DataFrame([{"pair_id":x["pair_id"],"target_id":x["target_id"],"resolution":int(x["resolution"])} for x in validated]); canonical=load_canonical_rows(canonical_path=canonical_path,requests=keys)
    sources=pd.concat([canonical.assign(surface_source="canonical"),variant_duals.assign(surface_source="variant")],ignore_index=True,sort=False) if len(variant_duals) else canonical.assign(surface_source="canonical"); rows=[]
    for item in validated:
        position=item.pop("_position"); resolution=int(item["resolution"]); matches=sources[(sources.pair_id==item["pair_id"])&(sources.target_id==item["target_id"])&(sources.v3_resolution.astype(int)==resolution)]
        if matches.empty: raise ValueError(f"Requested surface is unavailable: {item['feature_a']} / {item['feature_b']} / {item['target_id']} / r{resolution}")
        stored=matches.sort_values(["surface_source","pair_id"],kind="stable").iloc[0].to_dict()
        if item["cell_mode"]=="explicit" and (stored["feature_a"]!=item["feature_a"] or stored["feature_b"]!=item["feature_b"]): raise ValueError(f"Explicit cell orientation is reversed; authoritative order is {stored['feature_a']}, {stored['feature_b']}")
        row=reselect_surface_cell(stored,int(item["cell_index"])) if item["cell_mode"]=="explicit" else stored
        row.update(request_id="candidate_request_"+content_hash({"position":position,**item})[:20],family=item["family"],role=item["role"],cell_mode=item["cell_mode"],direction_mode=item["direction_mode"],guaranteed_explicit=True)
        row["state_key"]=state_key(row); rows.append(row)
    frame=pd.DataFrame(rows) if rows else pd.DataFrame(columns=["request_id","pair_id","feature_a","feature_b","target_id","v3_resolution","selected_cell","state_key","family","role","cell_mode","direction_mode","guaranteed_explicit"]); out=Path(legacy_run.root)/"context_expansion"; out.mkdir(parents=True,exist_ok=True); frame.to_parquet(out/"resolved_candidate_requests.parquet",index=False); return frame

def load_resolution_comparison_rows(*,canonical_path:Path,variant_duals:pd.DataFrame,candidates:pd.DataFrame)->pd.DataFrame:
    """Fetch authoritative r3/r5/r10 scanner rows only for materialized pairs."""
    if candidates.empty:return pd.DataFrame()
    keys=candidates[["pair_id","target_id"]].drop_duplicates(); canonical=load_canonical_rows(canonical_path=canonical_path,requests=keys,all_resolutions=True)
    requested=set(zip(keys.pair_id,keys.target_id)); variant=variant_duals[[((p,t) in requested) for p,t in zip(variant_duals.pair_id,variant_duals.target_id)]].copy() if len(variant_duals) else pd.DataFrame()
    canonical_keys=set(zip(canonical.pair_id,canonical.target_id)) if len(canonical) else set()
    if len(variant): variant=variant[[((p,t) not in canonical_keys) for p,t in zip(variant.pair_id,variant.target_id)]]
    frames=[x for x in (canonical,variant) if len(x)]; return pd.concat(frames,ignore_index=True,sort=False).drop_duplicates(["pair_id","target_id","v3_resolution"]) if frames else pd.DataFrame()
