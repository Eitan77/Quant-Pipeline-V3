from __future__ import annotations
from pathlib import Path
import numpy as np,pandas as pd
from quant_pipeline.production.zoom_requests import state_key

ROLE_ORDER=("canonical_parent","cross_resolution","plateau","interaction","economic_footprint","temporal_breadth","negative_structure","informative_failure")
SIMPLE_ROLES={"plateau":"plateau_area","interaction":"abs_interaction","economic_footprint":"abs_weighted","temporal_breadth":"temporal_score","negative_structure":"negative_score","informative_failure":"failure_score"}

def _codes(value):
    if isinstance(value,(list,tuple,np.ndarray)):return [str(x) for x in value]
    if value is None or (isinstance(value,float) and np.isnan(value)):return []
    return [str(value)]

def _prepare(frame):
    x=frame.copy()
    if x.empty:
        if "state_key" not in x:x["state_key"]=pd.Series(dtype=str)
        if "family" not in x:x["family"]=pd.Series(dtype=str)
        return x
    if "state_key" not in x:x["state_key"]=[state_key(r) for r in x.to_dict("records")]
    if "family" not in x:x["family"]=np.where(x.get("selection_role",pd.Series(index=x.index,dtype=object)).notna(),"variant","canonical_dual")
    x["abs_interaction"]=x.selected_interaction_lift_bps.abs(); x["abs_weighted"]=np.maximum(x.weighted_state_contribution_bps.abs(),x.weighted_interaction_contribution_bps.abs()); x["negative_score"]=(-x.selected_state_bps).clip(lower=0); retention=x["neighbor_effect_retention"] if "neighbor_effect_retention" in x else pd.Series(0.0,index=x.index); x["failure_score"]=(1-retention.fillna(0)).clip(lower=0)*x["abs_interaction"]; x["temporal_score"]=x.get("fold_sign_consistency",pd.Series(0.0,index=x.index)).fillna(0).abs()
    group=["feature_a","feature_b","target_id"]; x["resolution_breadth"]=x.groupby(group)["v3_resolution"].transform("nunique"); x["cross_resolution_complete"]=x.groupby(group)["v3_resolution"].transform(lambda s:set(s.astype(int))=={3,5,10}); x["cross_resolution_min_abs_edge"]=x.groupby(group)["selected_state_bps"].transform(lambda s:s.abs().min()); x["cross_resolution_min_n"]=x.groupby(group)["selected_n"].transform("min")
    def consistent(series):
        signs=set(np.sign(series).astype(int)) if len(series) and np.isfinite(series).all() and series.ne(0).all() else set(); return len(series)==3 and len(signs)==1
    x["cross_resolution_same_nonzero_sign"]=x.groupby(group)["selected_state_bps"].transform(consistent).astype(bool); return x

def _winner(part,metric,eligible=None):
    scoped=part if eligible is None else part[eligible]
    if scoped.empty:return None
    return scoped.sort_values([metric,"pair_id","target_id","v3_resolution","selected_cell","state_key"],ascending=[False,True,True,True,True,True],kind="stable").iloc[0]

def _family_role_winners(part):
    winners=[]; canonical=_winner(part,"selected_n",part.get("requested_canonical_parent",pd.Series(False,index=part.index)).fillna(False).astype(bool))
    if canonical is not None:winners.append((canonical,"canonical_parent"))
    cross=part[part.cross_resolution_complete].copy()
    if len(cross):
        groups=cross.drop_duplicates(["feature_a","feature_b","target_id"]).sort_values(["cross_resolution_same_nonzero_sign","cross_resolution_min_abs_edge","cross_resolution_min_n","feature_a","feature_b","target_id"],ascending=[False,False,False,True,True,True],kind="stable"); chosen=groups.iloc[0]; same=cross[(cross.feature_a==chosen.feature_a)&(cross.feature_b==chosen.feature_b)&(cross.target_id==chosen.target_id)]; winners.append((_winner(same,"abs_weighted"),"cross_resolution"))
    for role,metric in SIMPLE_ROLES.items():
        winner=_winner(part,metric)
        if winner is not None:winners.append((winner,role))
    return winners

def build_pre_specialist_contenders(*,candidate_rows:pd.DataFrame,explicit_rows:pd.DataFrame,settings:dict,output_dir:Path|None=None)->pd.DataFrame:
    x=_prepare(candidate_rows); per_family=int(settings.get("pre_specialist_per_family",8)); records=[]
    for _,part in x.groupby("family",sort=True):
        by_state={}
        for row,role in _family_role_winners(part):
            entry=by_state.setdefault(row.state_key,{"row":row.to_dict(),"roles":set()}); entry["roles"].add(role)
        ranked=sorted(by_state.values(),key=lambda e:(min(ROLE_ORDER.index(r) for r in e["roles"]),e["row"]["state_key"]))[:per_family]
        for entry in ranked:
            codes=sorted(entry["roles"],key=ROLE_ORDER.index); records.append({**entry["row"],"dossier_role":"|".join(codes),"dossier_role_codes":codes,"role_reason_codes":codes,"dynamic_dossier":True})
    result=pd.DataFrame(records) if records else x.head(0).assign(dossier_role=pd.Series(dtype=str),dossier_role_codes=pd.Series(dtype=object),role_reason_codes=pd.Series(dtype=object),dynamic_dossier=pd.Series(dtype=bool))
    if len(explicit_rows):
        combined={r["state_key"]:r for r in result.to_dict("records")}
        for row in explicit_rows.to_dict("records"):
            prior=combined.get(row["state_key"],{}); roles=sorted(set(_codes(prior.get("dossier_role_codes"))+_codes(row.get("role")))); combined[row["state_key"]]={**prior,**row,"dossier_role":"|".join(roles),"dossier_role_codes":roles,"role_reason_codes":roles,"dynamic_dossier":False}
        result=pd.DataFrame(combined.values())
    if output_dir is not None: Path(output_dir).mkdir(parents=True,exist_ok=True); result.to_parquet(Path(output_dir)/"pre_specialist_contenders.parquet",index=False)
    return result

def finalize_dossier_selection(*,contenders:pd.DataFrame,specialist:pd.DataFrame,settings:dict,output_dir:Path|None=None)->pd.DataFrame:
    if contenders.empty:
        result=contenders.copy()
        if output_dir is not None: result.to_parquet(Path(output_dir)/"dossier_selection.parquet",index=False)
        return result
    evidence=specialist[[c for c in specialist.columns if c in {"state_key","symbols_eligible","fraction_positive","fraction_negative","effect_dispersion_bps"}]].copy()
    if "state_key" not in evidence:evidence["state_key"]=pd.Series(dtype=str)
    merged=contenders.merge(evidence,on="state_key",how="left",suffixes=("","_specialist")); merged["specialist_breadth"]=merged["symbols_eligible"].fillna(0) if "symbols_eligible" in merged else 0
    guaranteed=merged["guaranteed_explicit"].fillna(False).astype(bool) if "guaranteed_explicit" in merged else pd.Series(False,index=merged.index); explicit=merged[guaranteed].copy(); dynamic=merged[~guaranteed].copy()
    if len(dynamic):
        breadth_indexes=dynamic.sort_values(["family","specialist_breadth","state_key"],ascending=[True,False,True],kind="stable").groupby("family",sort=True).head(1).index
        for index in breadth_indexes:
            codes=sorted(set(_codes(dynamic.at[index,"dossier_role_codes"])+["specialist_breadth"])); dynamic.at[index,"dossier_role_codes"]=codes; dynamic.at[index,"role_reason_codes"]=codes; dynamic.at[index,"dossier_role"]="|".join(codes)
    cap=int(settings.get("max_dynamic_dossiers",len(dynamic))); families=sorted(dynamic.family.dropna().unique())
    if cap<len(families): raise ValueError(f"max_dynamic_dossiers={cap} cannot cover {len(families)} requested families")
    first=dynamic.sort_values(["family","specialist_breadth","state_key"],ascending=[True,False,True],kind="stable").groupby("family",sort=True).head(1); remaining=dynamic[~dynamic.state_key.isin(first.state_key)].sort_values(["specialist_breadth","family","state_key"],ascending=[False,True,True],kind="stable").head(max(0,cap-len(first))); selected=pd.concat([first,remaining],ignore_index=True,sort=False)
    result=pd.concat([explicit,selected],ignore_index=True,sort=False).drop_duplicates("state_key")
    if output_dir is not None: result.to_parquet(Path(output_dir)/"dossier_selection.parquet",index=False)
    return result
