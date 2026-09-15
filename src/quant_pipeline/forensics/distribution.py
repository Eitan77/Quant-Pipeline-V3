import numpy as np
def distribution_stats(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]
    if not len(x):return {"n":0}
    w=x[x>0]; l=x[x<0]
    return {"n":int(len(x)),"mean_bps":float(x.mean()),"median_bps":float(np.median(x)),"std_bps":float(x.std(ddof=1)) if len(x)>1 else np.nan,"win_rate":float(np.mean(x>0)),**{f"p{int(q*100):02d}":float(np.quantile(x,q)) for q in (.01,.05,.25,.75,.95,.99)},"avg_winner_bps":float(w.mean()) if len(w) else np.nan,"avg_loser_bps":float(l.mean()) if len(l) else np.nan}
def contribution_concentration(x):
    x=np.asarray(x,float); x=x[np.isfinite(x)]; total=x.sum()
    if not len(x):return {}
    ranked=np.sort(x)[::-1]
    return {f"top_{p}pct_contribution_share":float(ranked[:max(1,int(np.ceil(len(x)*p/100)))].sum()/total) if total else np.nan for p in (1,5)}

