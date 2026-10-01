from copy import deepcopy
from collections import deque
import numpy as np,pandas as pd
from quant_pipeline.hf_intraday.engine import HFEngine,FACTOR_FEATURES,EVENT_FEATURES,FACTOR_TARGETS
from quant_pipeline.hf_intraday.spec import FEATURES,TARGETS,validate_pack
from quant_pipeline.hf_intraday.repair import merge_repair,REPAIR_KEYS


def test_targeted_block_matches_full_build_and_preserves_unaffected_columns():
    rng=np.random.default_rng(83);shape=(40,9);cfg=validate_pack({'model_min_rows':100,'peer_count':3})
    full=HFEngine(cfg)
    keys=set(FEATURES)|{'e1','e2','e3','e5','r1','abs_e1','range','volume','dollar_volume','trade_count','avg_trade_size','dollar_per_trade','impact','prevol','dispersion','m1','m2','market_vol','u1','u2','session_range','volratio'}
    full.history=deque([{key:rng.normal(0,.001,shape) for key in keys} for _ in range(60)],maxlen=60)
    full.returns=deque([rng.normal(0,.001,shape) for _ in range(20)],maxlen=20)
    full.markets=deque([rng.normal(0,.001,shape[0]) for _ in range(20)],maxlen=20)
    full.liquidity=deque([rng.uniform(1e4,1e5,shape) for _ in range(20)],maxlen=20)
    partial=deepcopy(full);partial.history=deque([{key:day[key] for key in REPAIR_KEYS} for day in partial.history],maxlen=60)
    close=100*np.exp(np.cumsum(rng.normal(0,.001,shape),axis=0));bars=dict(close=close,open=close,high=close*1.01,low=close*.99,vwap=close,volume=np.full(shape,1000.),trade_count=np.full(shape,50.),split_factor=np.ones(shape))
    market=100*np.exp(np.cumsum(rng.normal(0,.001,shape[0])));eligible=np.ones(shape[1],bool)
    f,y,q,_=full.build(bars,market,eligible);pf,py,pq,_=partial.repair(bars,market,eligible)
    assert set(pf)==set(FACTOR_FEATURES+EVENT_FEATURES) and set(py)==set(FACTOR_TARGETS) and set(pq)==set(pf)
    for key in pf:np.testing.assert_allclose(pf[key],f[key],atol=1e-12,rtol=1e-10,equal_nan=True,err_msg=key)
    for key in pq:np.testing.assert_allclose(pq[key],q[key],atol=1e-12,rtol=1e-10,equal_nan=True,err_msg=key)
    for key in py:np.testing.assert_allclose(py[key],y[key],atol=1e-12,rtol=1e-10,equal_nan=True,err_msg=key)
    ii=np.repeat(np.arange(shape[0]),shape[1]);jj=np.tile(np.arange(shape[1]),shape[0])
    obs=pd.DataFrame({'security_id':jj,'minute':ii,**{key:np.full(len(ii),index+.25) for index,key in enumerate(TARGETS)},**{'q_'+key:np.full(len(ii),index+.5) for index,key in enumerate(FEATURES)}})
    values=pd.DataFrame({'security_id':jj,'minute':ii,**{key:np.full(len(ii),index+.75) for index,key in enumerate(FEATURES)}})
    repaired_obs,repaired_values=merge_repair(obs,values,pf,py,pq,ii,jj)
    keep=[key for key in obs if key not in FACTOR_TARGETS and key not in {'q_'+k for k in FACTOR_FEATURES+EVENT_FEATURES}]
    pd.testing.assert_frame_equal(repaired_obs[keep],obs[keep],check_exact=True)
    keep=[key for key in values if key not in FACTOR_FEATURES]
    pd.testing.assert_frame_equal(repaired_values[keep],values[keep],check_exact=True)
