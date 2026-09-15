from __future__ import annotations
import numpy as np, pandas as pd

def decision_group_bounds(decision_codes):
    codes=np.asarray(decision_codes)
    if codes.ndim!=1: raise ValueError("decision codes must be one-dimensional")
    if not len(codes): return np.array([],dtype=np.int64),np.array([],dtype=np.int64)
    changes=np.flatnonzero(codes[1:]!=codes[:-1])+1
    return np.r_[0,changes].astype(np.int64),np.r_[changes,len(codes)].astype(np.int64)
def build_percentile_ranks(values,decision_codes):
    array=np.asarray(values)
    if array.ndim!=2 or len(array)!=len(decision_codes): raise ValueError("rank values and decision codes disagree")
    ranked=np.full(array.shape,np.nan,dtype=np.float32); starts,ends=decision_group_bounds(decision_codes); group=0
    while group<len(starts):
        first=int(starts[group]); last=group+1
        while last<len(starts) and int(ends[last])-first<=1_000_000:last+=1
        stop=int(ends[last-1]); frame=pd.DataFrame(array[first:stop]); codes=pd.Series(np.asarray(decision_codes)[first:stop]); ranked[first:stop]=frame.groupby(codes,sort=False).rank(method="average",pct=True).to_numpy(dtype=np.float32); group=last
    return ranked
def bins_from_ranks(ranked,bins):
    if bins<2 or bins>127: raise ValueError("bins must be in [2, 127]")
    valid=np.isfinite(ranked); labels=np.full(ranked.shape,-1,dtype=np.int8); labels[valid]=np.minimum((ranked[valid]*bins).astype(np.int16),bins-1).astype(np.int8); return labels,valid.astype(np.uint8)
def build_multi_bins(values,decision_codes,resolutions=(3,5,10)):
    ranks=build_percentile_ranks(values,decision_codes); return {r:bins_from_ranks(ranks,r)[0] for r in resolutions}
def pack_multi_bins(columns_by_resolution):
    if set(columns_by_resolution)!={3,5,10}: raise ValueError("Packed bins require exactly the 3, 5, and 10 resolutions")
    three,five,ten=(np.asarray(columns_by_resolution[n],dtype=np.int16) for n in (3,5,10)); valid=(three>=0)&(five>=0)&(ten>=0); packed=np.full(three.shape,255,dtype=np.uint8); packed[valid]=(three[valid]+3*five[valid]+15*ten[valid]).astype(np.uint8); return packed
def unpack_bins(packed,bins):
    values=np.asarray(packed,dtype=np.uint8)
    if bins==3:decoded=values%3
    elif bins==5:decoded=(values//3)%5
    elif bins==10:decoded=values//15
    else:raise ValueError("Packed bins support only 3, 5, and 10")
    decoded=decoded.astype(np.int8,copy=False); decoded[values==255]=-1; return decoded

