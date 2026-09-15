from __future__ import annotations
import numpy as np
from quant_pipeline.contracts import SurfaceStats
INVALID_STATE=255

def scan_surface_cpu(*,state_a,state_b,target_bps,target_valid,resolution:int)->SurfaceStats:
    a=np.asarray(state_a); b=np.asarray(state_b); y=np.asarray(target_bps,dtype=np.float64); v=np.asarray(target_valid,dtype=bool)&np.isfinite(y)&(a!=255)&(b!=255)&(a<resolution)&(b<resolution)
    cell=a[v].astype(np.int64)*resolution+b[v].astype(np.int64); n=resolution**2
    counts=np.bincount(cell,minlength=n); sums=np.bincount(cell,weights=y[v],minlength=n); means=np.full(n,np.nan); np.divide(sums,counts,out=means,where=counts>0)
    shape=(resolution,resolution); return SurfaceStats(resolution,counts.reshape(shape),sums.reshape(shape),means.reshape(shape))

def summarize_surface(*,counts,sums_bps,min_cell_n:int)->dict:
    means=np.full(counts.shape,np.nan,dtype=np.float64); np.divide(sums_bps,counts,out=means,where=counts>0); eligible=counts>=min_cell_n
    if not eligible.any(): return {"best_cell":None,"worst_cell":None,"best_mean_bps":np.nan,"worst_mean_bps":np.nan,"spread_bps":np.nan}
    best=np.unravel_index(int(np.argmax(np.where(eligible,means,-np.inf))),means.shape); worst=np.unravel_index(int(np.argmin(np.where(eligible,means,np.inf))),means.shape)
    return {"best_cell":best,"worst_cell":worst,"best_mean_bps":float(means[best]),"worst_mean_bps":float(means[worst]),"spread_bps":float(means[best]-means[worst])}

