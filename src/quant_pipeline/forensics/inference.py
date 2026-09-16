from __future__ import annotations

import numpy as np
import pandas as pd


def session_clustered_mean_se(returns_bps,session_id):
    frame=pd.DataFrame({"return_bps":np.asarray(returns_bps,float),"session_id":np.asarray(session_id)})
    means=frame[np.isfinite(frame.return_bps)].groupby("session_id",sort=False).return_bps.mean().to_numpy(float)
    return {"session_n":int(len(means)),"session_mean_bps":float(means.mean()) if len(means) else np.nan,
            "session_clustered_se_bps":float(means.std(ddof=1)/np.sqrt(len(means))) if len(means)>1 else np.nan}
