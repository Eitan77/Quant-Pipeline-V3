import numpy as np
def signal_jaccard(a,b):
    a=np.asarray(a,bool);b=np.asarray(b,bool);u=(a|b).sum();return float((a&b).sum()/u) if u else np.nan

