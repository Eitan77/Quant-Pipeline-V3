from __future__ import annotations
from dataclasses import dataclass
import numpy as np
@dataclass(frozen=True,slots=True)
class Episode: security_id:int; session_id:int; start_obs_id:int; end_obs_id:int; start_ts_ns:int; end_ts_ns:int; observation_count:int
def build_episodes(*,obs_id,security_id,session_id,security_session_seq,decision_ts_ns,active):
    arrays=[np.asarray(x) for x in (obs_id,security_id,session_id,security_session_seq,decision_ts_ns)]; active=np.asarray(active,bool); idx=np.flatnonzero(active)
    if not len(idx):return []
    idx=idx[np.lexsort((arrays[4][idx],arrays[2][idx],arrays[1][idx]))]; out=[]; start=prev=idx[0]; count=1
    for cur in idx[1:]:
        if arrays[1][cur]==arrays[1][prev] and arrays[2][cur]==arrays[2][prev] and arrays[3][cur]==arrays[3][prev]+1: prev=cur; count+=1; continue
        out.append(Episode(int(arrays[1][start]),int(arrays[2][start]),int(arrays[0][start]),int(arrays[0][prev]),int(arrays[4][start]),int(arrays[4][prev]),count)); start=prev=cur; count=1
    out.append(Episode(int(arrays[1][start]),int(arrays[2][start]),int(arrays[0][start]),int(arrays[0][prev]),int(arrays[4][start]),int(arrays[4][prev]),count)); return out
def independent_entries_fixed_hold(*,episodes,hold_ns):
    out=[]; next_allowed={}
    for ep in sorted(episodes,key=lambda x:(x.start_ts_ns,x.security_id)):
        key=(ep.security_id,ep.session_id)
        if ep.start_ts_ns < next_allowed.get(key,-1): continue
        out.append(ep); next_allowed[key]=ep.start_ts_ns+hold_ns
    return out

def independent_entries_by_exit(*,episodes,exit_ts_by_obs):
    """Accept starts only after the prior exact reference exit for a security."""
    out=[]; next_allowed={}
    for ep in sorted(episodes,key=lambda x:(x.start_ts_ns,x.security_id)):
        if ep.start_ts_ns < next_allowed.get(ep.security_id,-1): continue
        exit_ns=exit_ts_by_obs.get(ep.start_obs_id)
        if exit_ns is None or not np.isfinite(exit_ns): continue
        out.append(ep); next_allowed[ep.security_id]=int(exit_ns)
    return out

def opportunity_timing_summary(*,opportunities,end_ts_by_obs=None,hold_ns=None):
    starts=np.asarray([x.start_ts_ns for x in opportunities],dtype=np.int64)
    if end_ts_by_obs is not None:
        ends=np.asarray([end_ts_by_obs[x.start_obs_id] for x in opportunities],dtype=np.int64)
    elif hold_ns is not None:
        ends=starts+int(hold_ns)
    elif len(starts):
        raise ValueError("end_ts_by_obs or hold_ns is required")
    else: ends=np.asarray([],dtype=np.int64)
    if not len(starts):
        return {"unique_signal_timestamps":0,"simultaneous_cluster_count":0,"largest_simultaneous_cluster":0,
                "fraction_signals_in_clusters_2plus":0.0,"fraction_signals_in_clusters_5plus":0.0,
                "fraction_signals_in_clusters_10plus":0.0,"average_concurrency":0.0,"peak_concurrency":0}
    _,counts=np.unique(starts,return_counts=True)
    live=ends>starts
    concurrency=(
        np.searchsorted(np.sort(starts[live]),starts,side="right")
        -np.searchsorted(np.sort(ends[live]),starts,side="right")
    ).astype(float)
    return {"unique_signal_timestamps":int(len(counts)),"simultaneous_cluster_count":int(np.sum(counts>=2)),
            "largest_simultaneous_cluster":int(counts.max()),
            "fraction_signals_in_clusters_2plus":float(counts[counts>=2].sum()/len(starts)),
            "fraction_signals_in_clusters_5plus":float(counts[counts>=5].sum()/len(starts)),
            "fraction_signals_in_clusters_10plus":float(counts[counts>=10].sum()/len(starts)),
            "average_concurrency":float(concurrency.mean()),"peak_concurrency":int(concurrency.max())}
