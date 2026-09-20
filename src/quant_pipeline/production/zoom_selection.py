from __future__ import annotations
from pathlib import Path
import numpy as np,pandas as pd
from quant_pipeline.production.zoom_requests import state_key

ROLE_METRICS={"canonical_parent":("selected_n",False),"cross_resolution":("resolution_breadth",False),"plateau":("plateau_area",False),"interaction":("abs_interaction",False),"economic_footprint":("abs_weighted",False),"temporal_breadth":("temporal_score",False),"negative_structure":("negative_score",False),"informative_failure":("failure_score",False)}

def _prepare(frame):
    x=frame.copy()
    if x.empty:
        if "state_key" not in x:x["state_key"]=pd.Series(dtype=str)
        if "family" not in x:x["family"]=pd.Series(dtype=str)
        return x
    if "state_key" not in x:x["state_key"]=[state_key(r) for r in x.to_dict("records")]
    if "family" not in x:x["family"]=np.where(x.get("selection_role",pd.Series(index=x.index,dtype=object)).notna(),"variant","canonical_dual")
    x["abs_interaction"]=x.selected_interaction_lift_bps.abs(); x["abs_weighted"]=np.maximum(x.weighted_state_contribution_bps.abs(),x.weighted_interaction_contribution_bps.abs()); x["negative_score"]=(-x.selected_state_bps).clip(lower=0); retention=x["neighbor_effect_retention"] if "neighbor_effect_retention" in x else pd.Series(0.0,index=x.index); x["failure_score"]=(1-retention.fillna(0)).clip(lower=0)*x["abs_interaction"]
    x["resolution_breadth"]=x.groupby(["pair_id","target_id"])["v3_resolution"].transform("nunique"); x["temporal_score"]=x.get("fold_sign_consistency",pd.Series(0.0,index=x.index)).fillna(0).abs(); return x

def build_pre_specialist_contenders(*,candidate_rows:pd.DataFrame,explicit_rows:pd.DataFrame,settings:dict,output_dir:Path|None=None)->pd.DataFrame:
    x=_prepare(candidate_rows); per_family=int(settings.get("pre_specialist_per_family",8)); selected=[]
    for family,part in x.groupby("family",sort=True):
        family_rows=[]
        for role,(metric,ascending) in ROLE_METRICS.items():
            ranked=part.sort_values([metric,"pair_id","target_id","v3_resolution","selected_cell","state_key"],ascending=[ascending,True,True,True,True,True],kind="stable")
            if len(ranked): family_rows.append(ranked.iloc[[0]].assign(dossier_role=role,dynamic_dossier=True))
        if family_rows:
            merged=pd.concat(family_rows,ignore_index=True).sort_values(["dossier_role","state_key"],kind="stable").drop_duplicates("state_key").head(per_family); selected.append(merged)
    result=pd.concat(selected,ignore_index=True,sort=False) if selected else x.head(0).assign(dossier_role=pd.Series(dtype=str),dynamic_dossier=pd.Series(dtype=bool))
    if len(explicit_rows): result=pd.concat([result,explicit_rows.assign(dossier_role=explicit_rows.role,dynamic_dossier=False)],ignore_index=True,sort=False).drop_duplicates("state_key",keep="last")
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
    guaranteed=merged["guaranteed_explicit"].fillna(False).astype(bool) if "guaranteed_explicit" in merged else pd.Series(False,index=merged.index); explicit=merged[guaranteed].copy(); dynamic=merged[~guaranteed].copy(); breadth=(dynamic.sort_values(["family","specialist_breadth","state_key"],ascending=[True,False,True],kind="stable").groupby("family",group_keys=False).head(1).assign(dossier_role="specialist_breadth") if len(dynamic) else dynamic); dynamic=pd.concat([dynamic,breadth],ignore_index=True,sort=False).drop_duplicates("state_key",keep="last"); cap=int(settings.get("max_dynamic_dossiers",len(dynamic)))
    dynamic=dynamic.sort_values(["family","specialist_breadth","dossier_role","state_key"],ascending=[True,False,True,True],kind="stable").head(cap); result=pd.concat([explicit,dynamic],ignore_index=True,sort=False).drop_duplicates("state_key")
    if output_dir is not None: result.to_parquet(Path(output_dir)/"dossier_selection.parquet",index=False)
    return result
