import numpy as np
def interaction_decomposition(*,target_bps,active_a,active_b):
    y=np.asarray(target_bps,float); valid=np.isfinite(y); a=np.asarray(active_a,bool)&valid; b=np.asarray(active_b,bool)&valid; ab=a&b
    mean=lambda m:float(y[m].mean()) if m.any() else np.nan
    u,am,bm,j=mean(valid),mean(a),mean(b),mean(ab); exp=am+bm-u
    return {"unconditional_bps":u,"a_marginal_bps":am,"b_marginal_bps":bm,"joint_bps":j,"additive_expectation_bps":exp,"interaction_lift_bps":j-exp}

