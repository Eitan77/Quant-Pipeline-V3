from __future__ import annotations

import numpy as np
import pandas as pd


def _surface(a,b,y,resolution,mask):
    valid=mask&(a>=0)&(b>=0)&np.isfinite(y); index=a[valid]*resolution+b[valid]; yy=y[valid]
    counts=np.bincount(index,minlength=resolution**2); sums=np.bincount(index,weights=yy,minlength=resolution**2)
    joint=np.divide(sums,counts,out=np.full(resolution**2,np.nan),where=counts>0)
    unconditional=float(np.mean(yy)) if len(yy) else np.nan
    am=np.asarray([np.mean(yy[a[valid]==i]) if np.any(a[valid]==i) else np.nan for i in range(resolution)])
    bm=np.asarray([np.mean(yy[b[valid]==i]) if np.any(b[valid]==i) else np.nan for i in range(resolution)])
    interaction=joint-np.repeat(am,resolution)-np.tile(bm,resolution)+unconditional
    return counts,joint,interaction


def crossfit_surface_diagnostics(*,state_a,state_b,target,session_date,resolution:int,folds:int):
    a=np.asarray(state_a,int); b=np.asarray(state_b,int); y=np.asarray(target,float)
    sessions=np.sort(pd.unique(pd.to_datetime(session_date))); groups=np.array_split(sessions,folds); rows=[]; cells=[]
    dates=pd.to_datetime(session_date)
    for fold,held_sessions in enumerate(groups):
        held=np.asarray(dates.isin(held_sessions)); train=~held
        tc,tm,ti=_surface(a,b,y,resolution,train); hc,hm,hi=_surface(a,b,y,resolution,held)
        score=np.where(np.isfinite(ti),np.abs(ti),-np.inf); selected=int(np.argmax(score)) if np.any(np.isfinite(ti)) else 0
        valid=(tc>0)&(hc>0)&np.isfinite(tm)&np.isfinite(hm); x=tm[valid]; yy=hm[valid]; w=hc[valid]
        if len(x)>1 and np.sum(w*(x-np.average(x,weights=w))**2)>0:
            xbar=np.average(x,weights=w); ybar=np.average(yy,weights=w); slope=float(np.sum(w*(x-xbar)*(yy-ybar))/np.sum(w*(x-xbar)**2))
            spearman=float(pd.Series(x).corr(pd.Series(yy),method="spearman"))
        else: slope=spearman=np.nan
        rows.append({"fold":fold,"train_selected_cell":selected,"train_selected_state_bps":float(tm[selected]*1e4),
                     "train_selected_interaction_lift_bps":float(ti[selected]*1e4),"heldout_n":int(hc[selected]),
                     "heldout_state_bps":float(hm[selected]*1e4) if np.isfinite(hm[selected]) else np.nan,
                     "heldout_interaction_lift_bps":float(hi[selected]*1e4) if np.isfinite(hi[selected]) else np.nan,
                     "heldout_direction_match":bool(np.sign(tm[selected])==np.sign(hm[selected])) if np.isfinite(hm[selected]) else False,
                     "oof_surface_spread_bps":float((np.nanmax(hm)-np.nanmin(hm))*1e4) if np.isfinite(hm).any() else np.nan,
                     "spearman_rank_relationship":spearman,"weighted_calibration_slope":slope,"evidence_role":"discovery_diagnostic"})
        for cell in np.flatnonzero(valid):
            cells.append({"fold":fold,"cell":int(cell),"training_predicted_state_bps":float(tm[cell]*1e4),
                          "heldout_realized_state_bps":float(hm[cell]*1e4),"heldout_cell_n":int(hc[cell]),
                          "evidence_role":"discovery_diagnostic"})
    return pd.DataFrame(rows),pd.DataFrame(cells)
