import numpy as np
def specialist_probe(*,security_id,active,returns_bps,min_local_n=20):
    sec=np.asarray(security_id); active=np.asarray(active,bool); y=np.asarray(returns_bps,float); mask=active&np.isfinite(y); rows=[]
    for s in np.unique(sec[mask]):
        local=mask&(sec==s); rows.append((int(s),int(local.sum()),float(y[local].mean())))
    eligible=[r for r in rows if r[1]>=min_local_n]
    if not eligible:return {"symbols_active":len(rows),"symbols_eligible":0}
    effects=np.array([r[2] for r in eligible]); contrib=np.array([r[1]*r[2] for r in eligible]); shares=np.sort(np.abs(contrib))[::-1]/max(np.abs(contrib).sum(),1e-30)
    return {"symbols_active":len(rows),"symbols_eligible":len(eligible),"fraction_positive":float(np.mean(effects>0)),"fraction_negative":float(np.mean(effects<0)),"effect_dispersion_bps":float(np.std(effects,ddof=1)) if len(effects)>1 else np.nan,"top_symbol_share":float(shares[0]),"top5_symbol_share":float(shares[:5].sum()),"min_local_active_n":min(r[1] for r in eligible),"median_local_active_n":float(np.median([r[1] for r in eligible])),"max_local_active_n":max(r[1] for r in eligible)}

