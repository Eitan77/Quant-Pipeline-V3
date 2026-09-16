import numpy as np
from quant_pipeline.forensics.opportunities import build_episodes,independent_entries_by_exit,independent_entries_fixed_hold,opportunity_timing_summary

def _episodes(active,security=None,session=None,times=None):
    n=len(active); security=np.zeros(n,int) if security is None else np.asarray(security); session=np.zeros(n,int) if session is None else np.asarray(session); times=np.arange(n,dtype=np.int64) if times is None else np.asarray(times,dtype=np.int64)
    seq=np.concatenate([np.arange(np.sum((security==s)&(session==d))) for s,d in sorted(set(zip(security,session)))]) if False else np.arange(n)
    return build_episodes(obs_id=np.arange(n),security_id=security,session_id=session,security_session_seq=seq,decision_ts_ns=times,active=np.asarray(active,bool))

def test_fixed_hold_and_exact_simultaneous_clusters():
    repeated=_episodes([1,0,1],security=[0,0,0],times=[0,1,5]); assert len(independent_entries_fixed_hold(episodes=repeated,hold_ns=10))==1
    eps=_episodes([1,1],security=[0,1],times=[5,5]); accepted=independent_entries_fixed_hold(episodes=eps,hold_ns=10)
    summary=opportunity_timing_summary(opportunities=accepted,hold_ns=10)
    assert len(accepted)==2 and summary["simultaneous_cluster_count"]==1 and summary["largest_simultaneous_cluster"]==2

def test_overlapping_different_start_times_are_not_simultaneous():
    eps=_episodes([1,1],security=[0,1],times=[0,5]); summary=opportunity_timing_summary(opportunities=eps,hold_ns=10)
    assert summary["peak_concurrency"]==2 and summary["simultaneous_cluster_count"]==0

def test_cross_session_exact_exit_blocks_same_security_reentry():
    eps=_episodes([1,1],security=[0,0],session=[0,1],times=[0,10]); accepted=independent_entries_by_exit(episodes=eps,exit_ts_by_obs={0:20,1:30})
    assert len(accepted)==1
