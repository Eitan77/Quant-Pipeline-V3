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

