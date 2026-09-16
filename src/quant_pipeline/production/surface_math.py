from __future__ import annotations
import numpy as np

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
