import numpy as np
def session_clustered_mean_se(*,returns_bps,session_id):
    y=np.asarray(returns_bps,float);sid=np.asarray(session_id);valid=np.isfinite(y);means=np.array([y[valid&(sid==s)].mean() for s in np.unique(sid[valid])])
    if len(means)<2:return {"session_n":len(means),"mean_bps":float(y[valid].mean()) if valid.any() else np.nan,"session_clustered_se":np.nan,"t_stat":np.nan}
    mean=float(means.mean());se=float(means.std(ddof=1)/np.sqrt(len(means)));return {"session_n":len(means),"mean_bps":mean,"session_clustered_se":se,"t_stat":mean/se if se else np.nan}

