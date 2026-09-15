from __future__ import annotations
import numpy as np


def training_feature_selection(x, y, train, limit=16):
    """Select only from training rows; stable index tie-break, no validation labels."""
    scores=[]
    for i in range(x.shape[1]):
        a=x[train,i]; b=y[train]; valid=np.isfinite(a)&np.isfinite(b)
        if valid.sum()<20 or np.std(a[valid])==0 or np.std(b[valid])==0: continue
        scores.append((abs(float(np.corrcoef(a[valid],b[valid])[0,1])),i))
    return np.array([i for _,i in sorted(scores,key=lambda item:(-item[0],item[1]))[:limit]],dtype=int)
