from collections import deque
import numpy as np,pandas as pd,pytest,torch
from quant_pipeline.hf_intraday.math import pairwise_statistics,fit_models
from quant_pipeline.hf_intraday.engine import HFEngine
from quant_pipeline.hf_intraday.spec import FEATURES,validate_pack

@pytest.mark.parametrize('device',['cpu','cuda:0'])
def test_pairwise_moments_match_observed_pair_reference(device):
    if device!='cpu' and not torch.cuda.is_available(): pytest.skip('CUDA unavailable')
    rng=np.random.default_rng(9);x=rng.normal(0,.001,(200,9))
    x[np.arange(len(x)),np.arange(len(x))%9]=np.nan
    assert not np.isfinite(x).all(1).any()
    cov,n,corr=pairwise_statistics(x,device);cov=cov.cpu().numpy()
    for i in range(9):
        for j in range(9):
            mask=np.isfinite(x[:,i])&np.isfinite(x[:,j]);a=x[mask,i];b=x[mask,j]
            assert n[i,j]==mask.sum()
            assert cov[i,j]==pytest.approx(np.cov(a,b,ddof=1)[0,1],abs=1e-15)
            assert corr[i,j]==pytest.approx(np.corrcoef(a,b)[0,1],abs=1e-12)

def test_missing_minutes_do_not_suppress_entire_pca_or_peer_model():
    rng=np.random.default_rng(3);h=rng.normal(0,.001,(20,40,9));m=rng.normal(0,.001,(20,40))
    flat=h.reshape(-1,9);flat[np.arange(len(flat)),np.arange(len(flat))%9]=np.nan
    cfg=validate_pack({'model_min_rows':100,'peer_count':3})
    model=fit_models(list(h),list(m),np.ones(9,bool),cfg)
    assert not np.isfinite(flat).all(1).any()
    assert np.isfinite(model['loadings']).all()
    assert all(value is not None for value in model['lead1'])
    assert all(value is not None for value in model['lead2'])
    cov=pairwise_statistics(flat)[0].cpu().numpy();loads=model['loadings']
    np.testing.assert_allclose(loads.T@loads,np.eye(5),atol=1e-12)
    eigen=np.diag(loads.T@cov@loads)
    np.testing.assert_allclose(cov@loads,loads*eigen,atol=1e-12)

def test_sparse_recovery_gets_prior_event_bins_without_filling_non_events(monkeypatch):
    from quant_pipeline.hf_intraday import engine as module
    rng=np.random.default_rng(5);shape=(40,9);c=100*np.exp(np.cumsum(rng.normal(0,.001,shape),axis=0))
    bars=dict(close=c,open=c,high=c*1.01,low=c*.99,vwap=c,volume=np.full(shape,1000.),trade_count=np.full(shape,50.))
    loads=np.linalg.qr(rng.normal(size=(9,5)))[0]
    model=dict(beta=np.zeros(9),loadings=loads,peers=[None]*9,lead1=[None]*9,lead2=[None]*9,incoming=np.zeros(9),outgoing=np.zeros(9))
    monkeypatch.setattr(module,'fit_models',lambda *args:model)
    tail=np.zeros(shape);tail[14]=1
    monkeypatch.setattr(module,'baseline',lambda x,h,kind,minimum,eps:tail.copy() if kind=='tail' else np.zeros(shape))
    history=[{k:np.zeros(shape) for k in FEATURES} for _ in range(60)]
    for day in history:
        for key in ('post_shock_recovery_1m','post_shock_recovery_3m'): day[key][:]=np.nan
    for key in ('post_shock_recovery_1m','post_shock_recovery_3m'): history[10][key][15]=-.01
    engine=HFEngine(validate_pack({}));engine.history=deque(history,maxlen=60)
    f,_,q,_=engine.build(bars,np.full(40,100.),np.ones(9,bool))
    for key in ('post_shock_recovery_1m','post_shock_recovery_3m'):
        assert np.isfinite(f[key][15]).all() and np.isfinite(q[key][15]).all()
        assert np.isnan(f[key][5]).all() and np.isnan(q[key][5]).all()
        assert np.isnan(q[key][16]).all() # No prior event at this clock minute.
