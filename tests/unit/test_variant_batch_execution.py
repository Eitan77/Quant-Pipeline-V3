from types import SimpleNamespace

import numpy as np
import pandas as pd

from quant_pipeline.production.variant_scan import _scan_missing_batches


def test_two_requests_share_one_feature_load(tmp_path):
    rows=40
    observations=pd.DataFrame({"decision_ts":pd.date_range("2025-05-01 14:30Z",periods=rows,freq="5min"),
                               "session_date":[pd.Timestamp("2025-05-01")]*rows})
    values=np.column_stack([np.arange(rows)%11,np.arange(rows)*3%17]).astype(float)
    loads=[]
    class Run:
        root=tmp_path
        config=SimpleNamespace(stability={"chronological_folds":2},
            compute=SimpleNamespace(gpu_device="cpu",prefer_cuda=False,dynamic_memory_fraction=.5))
        def compile_registry(self):
            return SimpleNamespace(features=[SimpleNamespace(feature_id=key,decision_grid="intraday_5m") for key in ("a","b")])
        def _load_features(self,grid,features):
            loads.append((grid,tuple(features)))
            return observations,values[:,[["a","b"].index(key) for key in features]]
        def _target_ids_and_vector(self,grid,obs,target_id):
            return (np.arange(rows,dtype=float)/10000)*(1 if target_id=="x" else -1)
    requests=[{"feature_a":"a","feature_b":"b","target_id":target} for target in ("x","y")]
    executed=_scan_missing_batches(Run(),requests,[3,5,10],tmp_path/"variants")
    assert executed=={("a","b","x"),("a","b","y")}
    assert loads==[("intraday_5m",("a","b"))]
    assert len(list((tmp_path/"variants").rglob("*.parquet")))==6
