from __future__ import annotations
import numpy as np

INFERENCE_FIELDS=("candidate_effect","selection_test_effect","cluster_se","test_statistic","p_value","cluster_count","outlier_cluster_share","fold_effects","fold_sign_consistency","fold_magnitude_ratio")

def reconstruct_surface(*,counts,sums,sumsq,resolution:int)->dict[str,np.ndarray]:
    c=np.asarray(counts,dtype=np.int64); s=np.asarray(sums,dtype=np.float64); ss=np.asarray(sumsq,dtype=np.float64); expected=resolution*resolution
    if not (c.size==s.size==ss.size==expected): raise ValueError(f"Surface payload mismatch for r{resolution}")
    mean=np.divide(s,c,out=np.full(expected,np.nan),where=c>0)
    variance=np.divide(ss-np.divide(np.square(s),c,out=np.zeros_like(s),where=c>0),np.maximum(c-1,1),out=np.full(expected,np.nan),where=c>1)
    se=np.sqrt(np.divide(variance,c,out=np.full(expected,np.nan),where=c>0)); c2=c.reshape(resolution,resolution); s2=s.reshape(resolution,resolution); mean2=mean.reshape(resolution,resolution)
    overall=s.sum()/c.sum() if c.sum()>0 else np.nan
    a_mean=np.divide(s2.sum(axis=1),c2.sum(axis=1),out=np.full(resolution,np.nan),where=c2.sum(axis=1)>0)
    b_mean=np.divide(s2.sum(axis=0),c2.sum(axis=0),out=np.full(resolution,np.nan),where=c2.sum(axis=0)>0)
    interaction=mean2-a_mean[:,None]-b_mean[None,:]+overall; frequency=np.divide(c,max(int(c.sum()),1))
    return {"count":c,"sum":s,"sumsq":ss,"mean":mean,"se":se,"frequency":frequency,"interaction":interaction.reshape(-1)}

def reselect_surface_cell(row,cell_index:int)->dict:
    """Return a surface row with an already-tested cell made effective."""
    result=dict(row); resolution=int(result.get("v3_resolution",result.get("resolution"))); cell=int(cell_index)
    if cell<0 or cell>=resolution*resolution: raise ValueError(f"cell_index {cell} is outside r{resolution}")
    surface=reconstruct_surface(counts=result["surface_counts"],sums=result["surface_sums"],sumsq=result["surface_sumsq"],resolution=resolution)
    selected_fields=("selected_cell","selected_n","selected_frequency","selected_state_return","selected_state_bps","selected_interaction_lift","selected_interaction_lift_bps","weighted_state_contribution","weighted_state_contribution_bps","weighted_interaction_contribution","weighted_interaction_contribution_bps","selected_direction","selected_cell_effect","selected_cell_se","legacy_incremental_cell_effect","neighbor_effect_retention","plateau_area")
    for name in (*selected_fields,*INFERENCE_FIELDS):
        if name in result and f"scanner_{name}" not in result: result[f"scanner_{name}"]=result[name]
    mean=float(surface["mean"][cell]); lift=float(surface["interaction"][cell]); frequency=float(surface["frequency"][cell]); peak=lift; r,c=divmod(cell,resolution)
    neighbors=[(r+dr,c+dc) for dr,dc in ((-1,0),(1,0),(0,-1),(0,1)) if 0<=r+dr<resolution and 0<=c+dc<resolution]
    values=np.asarray([surface["interaction"][rr*resolution+cc] for rr,cc in neighbors],float)
    retention=0.0; plateau=1
    if len(values) and np.isfinite(peak) and peak!=0:
        aligned=values[np.sign(values)==np.sign(peak)]; retention=float(np.nanmedian(np.abs(aligned))/abs(peak)) if len(aligned) else 0.0
        plateau+=int(np.sum((np.sign(values)==np.sign(peak))&(np.abs(values)>=.5*abs(peak))))
    result.update(selected_cell=cell,selected_n=int(surface["count"][cell]),selected_frequency=frequency,selected_state_return=mean,selected_state_bps=mean*10_000.0,selected_interaction_lift=lift,selected_interaction_lift_bps=lift*10_000.0,weighted_state_contribution=mean*frequency,weighted_state_contribution_bps=mean*frequency*10_000.0,weighted_interaction_contribution=lift*frequency,weighted_interaction_contribution_bps=lift*frequency*10_000.0,selected_direction=int(np.sign(mean)) if np.isfinite(mean) else 0,selected_cell_effect=lift,legacy_incremental_cell_effect=lift,selected_cell_se=float(surface["se"][cell]),neighbor_effect_retention=retention,plateau_area=plateau)
    scanner_cell=result.get("scanner_selected_cell",row.get("selected_cell"))
    if int(scanner_cell)!=cell:
        for name in INFERENCE_FIELDS:
            if name in result: result[name]=None
    return result
