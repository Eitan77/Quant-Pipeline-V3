from pathlib import Path
from copy import deepcopy
import hashlib,re
import duckdb,numpy as np,pandas as pd,pytest
from quant_pipeline.hf_intraday.spec import SPEC,FEATURES,TARGETS,validate_pack
from quant_pipeline.hf_intraday.math import lag,rolling,empirical,baseline,project,fit_models
from quant_pipeline.hf_intraday.engine import HFEngine
from quant_pipeline.hf_intraday.scan import tasks,codes,cell_count,sql_state
from hf_scan_reference import scan_task

ROOT=Path(__file__).resolve().parents[2]

def settings():
    return validate_pack({})

def test_source_exact_coverage():
    path=ROOT/'docs/HF_INTRADAY_SOURCE.md'; raw=path.read_bytes(); source=raw.decode('utf-8')
    assert hashlib.sha256(raw).hexdigest()==SPEC['source_sha256']
    feature_section=source.split('# 1. Features')[1].split('# 2. Targets')[0]
    target_section=source.split('# 2. Targets')[1].split('# 3. Exact')[0]
    parsed_features=[dict(id=fid,definition=definition.strip()) for _,fid,definition in
        re.findall(r'^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|$',feature_section,re.M)]
    parsed_targets=[dict(id=tid,basis=basis.strip(),definition=definition.strip()) for _,tid,basis,definition in
        re.findall(r'^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|\s*([^|]+)\|\s*(.*?)\s*\|$',target_section,re.M)]
    assert parsed_features==SPEC['features']
    assert parsed_targets==SPEC['targets']
    pairs=[(int(n),a,b) for n,a,b in re.findall(r'^(\d+)\. `([^`]+)` × `([^`]+)`',source,re.M)]
    assert pairs==[(p['id'],p['a'],p['b']) for p in SPEC['pairs']]
    assert len(FEATURES)==117 and len(TARGETS)==31
    plan=tasks(settings())
    assert sum(t['kind']=='single' for t in plan)==117*3
    assert sum(t['kind']=='dual' for t in plan)==305*3
    for a in SPEC['tail_features']:
        for fraction in SPEC['tail_fractions']:
            for side in ('lower','upper'):
                tail=[t for t in plan if t['a']==a and t['tail']==fraction and t['side']==side]
                assert sum(t['b'] is None for t in tail)==1
                assert sum(t['b'] is not None for t in tail)==2*sum(p['a']==a for p in SPEC['pairs'])

def fixture(minutes=80,symbols=9,seed=1):
    rng=np.random.default_rng(seed)
    close=100*np.exp(np.cumsum(rng.normal(0,.001,(minutes,symbols)),axis=0))
    bars=dict(close=close,open=close*.9999,high=close*1.001,low=close*.999,volume=rng.uniform(1000,2000,close.shape),
              vwap=close*.99995,trade_count=np.full(close.shape,50),split_factor=np.ones(close.shape))
    market=100*np.exp(np.cumsum(rng.normal(0,.001,minutes)))
    return bars,market,np.ones(symbols,bool)

def test_minute_math_missing_and_tod_prior():
    x=np.arange(10,dtype=float)[:,None]; x[4]=np.nan
    assert np.isnan(lag(x,2)[6])
    assert np.isnan(rolling(x,3)[6])
    h=[np.array([[i]],float) for i in range(60)]
    assert empirical(np.array([[60.]]),h)[0,0]==1
    assert empirical(np.array([[-1.]]),h)[0,0]==0
    assert empirical(np.array([[30.]]),h)[0,0]==30.5/60
    assert np.isnan(empirical(np.array([[30.]]),h[:-1])[0,0])
    assert baseline(np.array([[30.]]),h,'q99')[0,0]==pytest.approx(58.41)

def seeded_engine():
    cfg=settings(); cfg['model_min_rows']=30;cfg['tod_min_sessions']=5
    engine=HFEngine(cfg)
    # Real prior sessions train the same daily frozen model and all baselines.
    for seed in range(1,82): engine.build(*fixture(seed=seed))
    return engine

def test_disk_history_exact_parity_and_eviction(tmp_path):
    cfg=settings(); cfg['model_min_rows']=30; cfg['tod_min_sessions']=5
    memory=HFEngine(cfg); disk=HFEngine(cfg,history_root=tmp_path)
    try:
        for seed in range(1,63):
            args=fixture(minutes=40,symbols=8,seed=seed)
            expected=memory.build(*args); actual=disk.build(*args)
            for left,right in zip(expected[:3],actual[:3]):
                for key in left: np.testing.assert_array_equal(left[key],right[key])
            assert len(list(tmp_path.glob('*.npy')))==min(seed,60)
        assert not (tmp_path/'000000.npy').exists()
        for day in disk.history:
            assert all(value.dtype==np.float64 for value in day.values())
    finally:
        disk.close()
    assert not list(tmp_path.glob('*.npy'))

@pytest.fixture(scope='module')
def trained(): return seeded_engine()

def test_all_formulas_and_target_endpoints(trained):
    engine=deepcopy(trained); bars,market,eligible=fixture(seed=300)
    f,y,q,model=engine.build(bars,market,eligible)
    assert set(f)==set(FEATURES) and set(y)==set(TARGETS) and set(q)==set(FEATURES)
    c=bars['close']; e=c/lag(c)-1-model['beta']*(market/lag(market)-1)[:,None]
    np.testing.assert_allclose(f['body_ret_1m'],c/bars['open']-1)
    np.testing.assert_allclose(f['resid_prevol_norm_1m'],e/(rolling(e,30,'std',True)+1e-12),equal_nan=True)
    np.testing.assert_allclose(f['path_eff_3m'],abs(rolling(e,3))/(rolling(abs(e),3)+1e-12),equal_nan=True)
    np.testing.assert_allclose(f['dist_session_open'],c/bars['open'][0]-1)
    for horizon in (1,2,3,5,10,15,30):
        expected=lag(c,-horizon)/c-1
        np.testing.assert_allclose(y[f'fwd_raw_{horizon}m'],expected,equal_nan=True)
        np.testing.assert_allclose(y[f'fwd_beta_resid_{horizon}m'],expected-model['beta']*(lag(market,-horizon)/market-1)[:,None],equal_nan=True)
        np.testing.assert_allclose(y[f'fwd_factor_resid_{horizon}m'],project(expected,model['loadings']),equal_nan=True)
        assert np.isnan(y[f'fwd_raw_{horizon}m'][-horizon:]).all()
    for horizon in range(1,6):
        np.testing.assert_allclose(y[f'step_raw_p{horizon}'],lag(c,-horizon)/lag(c,-(horizon-1))-1,equal_nan=True)
        np.testing.assert_allclose(y[f'step_factor_resid_p{horizon}'],project(lag(c,-horizon)/lag(c,-(horizon-1))-1,model['loadings']),equal_nan=True)
    assert np.isnan(f['dist_orh_5m'][:4]).all()
    assert np.isfinite(model['loadings']).all()
    assert np.isfinite(f['peer_lead_pred_1m'][30:]).all()
    assert np.isfinite(q['factor_resid_1m'][30:]).all()
    assert np.isfinite(q['resid_tod_tail_1m'][30:]).all()
    split_bars=deepcopy(bars);split_bars['split_factor']*=2
    split_f,_,_,_=deepcopy(trained).build(split_bars,market,eligible)
    np.testing.assert_allclose(split_f['impact_per_dollar_1m'][1:],f['impact_per_dollar_1m'][1:]/2,atol=1e-9,rtol=1e-7)
    width=bars['high']-bars['low']
    np.testing.assert_allclose(f['range_ratio_5_30'],rolling(width,5)/(lag(rolling(width,30),5)*5/30+1e-12),equal_nan=True)

def test_pooled_minute_liquidity_median():
    engine=HFEngine(settings()); bars,market,eligible=fixture()
    for day in range(20):
        dv=np.broadcast_to(200+np.arange(9,dtype=float),(80,9)).copy()
        dv[:,1]=50
        if day<11:
            dv[:41,0]=1;dv[41:,0]=1000
        else: dv[:,0]=100
        engine.liquidity.append(dv)
    f,_,_,_=engine.build(bars,market,eligible)
    # Pooled median is 100 for stock0, hence higher than stock1=50.
    # Median of daily medians would be 1 and would reverse this ranking.
    assert f['liquidity_rank_20d'][0,0]>f['liquidity_rank_20d'][0,1]
    expected=(np.arange(9)+.5)/9
    np.testing.assert_allclose(f['liquidity_rank_20d'][0,[1,0,2,3,4,5,6,7,8]],expected)

def test_peer_hhi_zero_and_normalized_contributions(monkeypatch):
    from quant_pipeline.hf_intraday import engine as module
    loads=np.zeros((9,5));loads[:5]=np.eye(5)
    model=dict(beta=np.zeros(9),loadings=loads,peers=[None]*9,lead1=[None]*9,lead2=[None]*9,
               incoming=np.zeros(9),outgoing=np.zeros(9))
    model['peers'][0]=(np.array([5,6]),np.array([.5,.5]));model['lead1'][0]=np.ones(2)
    monkeypatch.setattr(module,'fit_models',lambda *args:model)
    bars,market,eligible=fixture()
    for key in ('close','open','high','low','vwap'): bars[key][:]=100
    f,_,_,_=HFEngine(settings()).build(bars,market,eligible)
    assert np.isnan(f['peer_move_concentration_1m'][:,0]).all()
    bars['close'][1:,5]=110;bars['close'][1:,6]=130
    f,_,_,_=HFEngine(settings()).build(bars,market,eligible)
    assert f['peer_move_concentration_1m'][1,0]==pytest.approx(.25**2+.75**2)

def test_factor_projection_orthogonality_and_missing_returns():
    rng=np.random.default_rng(91);loads=np.linalg.qr(rng.normal(size=(12,5)))[0]
    values=rng.normal(size=(8,12));values[2,0]=np.nan;values[3,:8]=np.nan
    residual=project(values,loads)
    for minute in (0,1,2,4,5,6,7):
        good=np.isfinite(values[minute])
        np.testing.assert_allclose(loads[good].T@residual[minute,good],0,atol=1e-12)
    assert np.isnan(residual[2,0]) and np.isnan(residual[3]).all()

def test_unknown_shock_minute_does_not_fabricate_event_age_or_recovery(monkeypatch):
    from quant_pipeline.hf_intraday import engine as module
    bars,market,eligible=fixture()
    loads=np.zeros((9,5));loads[:5]=np.eye(5)
    model=dict(beta=np.zeros(9),loadings=loads,peers=[None]*9,lead1=[None]*9,lead2=[None]*9,
               incoming=np.zeros(9),outgoing=np.zeros(9))
    monkeypatch.setattr(module,'fit_models',lambda *args:model)
    tail=np.zeros_like(bars['close']);tail[10]=1;tail[11]=np.nan;tail[15]=1
    monkeypatch.setattr(module,'baseline',lambda x,h,kind,minimum,eps:tail.copy() if kind=='tail' else np.zeros_like(x))
    f,_,_,_=HFEngine(settings()).build(bars,market,eligible)
    assert np.isnan(f['minutes_since_tail_event'][12:15]).all()
    assert np.isnan(f['post_shock_recovery_3m'][12:14]).all()
    assert (f['minutes_since_tail_event'][16]==1).all()
    assert np.isfinite(f['post_shock_recovery_3m'][16]).all()

def test_future_perturbation_does_not_change_features(trained):
    bars,market,eligible=fixture(seed=901); original=deepcopy(trained)
    f,y,q,model=original.build(bars,market,eligible)
    altered=deepcopy(bars); altered_market=market.copy()
    for k in ('close','open','high','low','vwap'): altered[k][41:]*=1.2
    altered['volume'][41:]*=3; altered_market[41:]*=1.1
    f2,y2,q2,model2=deepcopy(trained).build(altered,altered_market,eligible)
    for key in FEATURES:
        np.testing.assert_allclose(f[key][:41],f2[key][:41],equal_nan=True,err_msg=key)
        np.testing.assert_allclose(q[key][:41],q2[key][:41],equal_nan=True,err_msg=key)
    np.testing.assert_array_equal(model['loadings'],model2['loadings'])
    assert not np.allclose(y['fwd_raw_30m'][20],y2['fwd_raw_30m'][20])

def test_sql_gpu_stats_and_episodes(tmp_path):
    rows=12; q=np.array([0,.1,.1,.3,.5,.5,.8,.9,1,np.nan,.3,.1])
    data=dict(symbol=['A']*6+['B']*6,session_date=['2025-05-01']*rows,month=['2025-05']*rows,
              minute=[0,1,3,4,5,6,0,1,2,3,4,5],q_ret_tod_tail_1m=q,q_body_share_1m=q[::-1])
    for j,target in enumerate(TARGETS):
        v=np.arange(rows,dtype=float)/10000;v[(j+1)%rows]=np.nan; data[target]=v
    path=tmp_path/'obs.parquet';pd.DataFrame(data).to_parquet(path,index=False)
    task=dict(key='test',kind='dual',a='ret_tod_tail_1m',b='body_share_1m',resolution=3,tail=None,side=None)
    with duckdb.connect() as con:
        result=scan_task(con,str(path),task,'cpu')
    st=codes(task,q,q[::-1]); target=TARGETS[0]; y=data[target]*10000
    for cell in range(9):
        mask=(st==cell)&np.isfinite(y); row=result[(result.target==target)&(result.grouping=='all')&(result.cell==cell)].iloc[0]
        assert row.observations==mask.sum()
        if mask.any(): assert row.median_bps==np.median(y[mask])
    assert len(result[result.grouping=='all'])==9*31

def test_tail_boundaries_and_ties():
    task=dict(a='a',b='b',resolution=5,tail=.001,side='lower')
    ra=np.array([0,.001,.0011,.999,1,np.nan]);rb=np.array([0,.3,.8,1,1,0])
    np.testing.assert_array_equal(codes(task,ra,rb),[0,1,-1,-1,-1,-1])
    task['side']='upper';np.testing.assert_array_equal(codes(task,ra,rb),[-1,-1,-1,4,4,-1])

def test_every_planned_state_matches_sql():
    rng=np.random.default_rng(9);ra=np.r_[0,.001,.0025,.005,.01,.02,.05,.5,.95,.99,.999,1,np.nan,rng.random(25)]
    with duckdb.connect() as con:
        for task in tasks(settings()):
            rb=ra[::-1].copy()
            frame=pd.DataFrame({f'q_{task["a"]}':ra})
            if task['b']: frame[f'q_{task["b"]}']=rb
            con.register('states',frame)
            actual=con.execute(f'SELECT {sql_state(task)} FROM states').fetchnumpy()
            np.testing.assert_array_equal(next(iter(actual.values())),codes(task,ra,rb),err_msg=task['key'])

def test_request_preflight_does_not_launch():
    from quant_pipeline.config import load_research_config
    from quant_pipeline.hf_intraday.runner import preflight
    request=load_research_config(ROOT/'configs/research/hf_intraday_run_all.yaml')
    report=preflight(request)
    assert report['surface_tasks']==6210 and report['cell_targets']==2467228
    assert report['production_launched'] is False

def test_cuda_moments_parity(tmp_path):
    import torch
    from hf_scan_reference import gpu_moments
    if not torch.cuda.is_available(): pytest.skip('CUDA unavailable')
    rng=np.random.default_rng(99);size=2000
    df=pd.DataFrame({f'q_{FEATURES[0]}':rng.random(size),f'q_{FEATURES[1]}':rng.random(size)})
    for target in TARGETS:
        df[target]=rng.normal(0,.001,size);df.loc[::11,target]=np.nan
    path=tmp_path/'values.parquet';df.to_parquet(path,index=False)
    for task in [dict(a=FEATURES[0],b=FEATURES[1],resolution=10,tail=None,side=None),
                 dict(a=FEATURES[0],b=FEATURES[1],resolution=5,tail=.05,side='upper')]:
        with duckdb.connect() as con:
            cpu=gpu_moments(con,str(path),task,'cpu');gpu=gpu_moments(con,str(path),task,'cuda:0')
        np.testing.assert_array_equal(cpu[0],gpu[0])
        for i in (1,2): np.testing.assert_allclose(cpu[i],gpu[i],atol=1e-12,rtol=1e-10)

def test_runner_output_resume_and_missing_artifact_repair(tmp_path,monkeypatch):
    from quant_pipeline.hf_intraday import runner,scan
    from quant_pipeline.config import load_research_config
    research=load_research_config(ROOT/'configs/research/hf_intraday_run_all.yaml')
    research['periods']['discovery']={'start':'2025-05-01','end':'2025-05-02'}
    root=tmp_path/research['run_name'];panel=root/'cache/calculation_panels/intraday_1m.parquet'
    panel.parent.mkdir(parents=True)
    records=[]
    for date in ('2025-04-30','2025-05-01','2025-05-02'):
        for i,symbol in enumerate(['SPY','QQQ','A','B']):
            for minute in range(40):
                record=dict(security_id=str(i),symbol='RENAMED_A' if symbol=='A' and date=='2025-05-02' else symbol,session_date=date,
                    bar_start_ts_utc=pd.Timestamp(date+' 13:30',tz='UTC')+pd.Timedelta(minutes=minute),
                    in_universe=symbol not in ('SPY','QQQ'))
                record.update(dict(open=100.,high=101.,low=99.,close=100+minute*.01,volume=1000.,vwap=100.,trade_count=50.,split_factor=1.))
                records.append(record)
    pd.DataFrame(records).to_parquet(panel,index=False)
    class Core:
        def initialize(self): pass
        def execute(self,stage): return {}
    class Adapter:
        def __init__(self,*args): pass
        def build_run(self): return Core()
    class Engine:
        def __init__(self,*args,**kwargs): pass
        def close(self): pass
        def build(self,bars,market,eligible):
            shape=bars['close'].shape
            f={key:bars['close']*.001 for key in FEATURES}
            y={key:bars['close']*.000001 for key in TARGETS}
            rank=np.broadcast_to(np.linspace(0,1,shape[0])[:,None],shape).copy()
            q={key:rank.copy() for key in FEATURES}
            models=dict(beta=np.ones(shape[1]),loadings=np.ones((shape[1],5)),peers=[None]*shape[1],lead1=[None]*shape[1])
            return f,y,q,models
    class Telemetry:
        def event(self,*args,**kwargs): pass
        def progress(self,*args,**kwargs): pass
    chosen=[tasks(settings())[0],next(t for t in tasks(settings()) if t['kind']=='dual'),next(t for t in tasks(settings()) if t['kind']=='tail')]
    monkeypatch.setattr(runner,'LegacyCoreAdapter',Adapter);monkeypatch.setattr(runner,'HFEngine',Engine)
    names=pd.DataFrame({'security_id':['2','3'],'symbol':['A','B']})
    known=pd.DataFrame([dict(security_id=sid,session_date=date,eligible=True)
        for sid in ('2','3') for date in ('2025-04-30','2025-05-01','2025-05-02')])
    monkeypatch.setattr(runner,'load_daily_eligibility',lambda *args:(names,known))
    monkeypatch.setattr(runner,'build_production_source_manifest',lambda **kwargs:{'source_manifest_hash':'fixture'})
    monkeypatch.setattr(scan,'tasks',lambda cfg:chosen)
    machine=dict(run_root=str(tmp_path),duckdb_temp=str(tmp_path/'temp'),duckdb_threads=2,
                 data_root=str(tmp_path/'source'),gpu_device='cuda:0')
    result=runner.run_hf(research,machine,ROOT,Telemetry())
    assert result['mandatory_coverage_complete']
    first=pd.read_parquet(root/'observations/2025-05-01.parquet')
    second=pd.read_parquet(root/'observations/2025-05-02.parquet')
    assert set(first.loc[first.security_id=='2','symbol'])=={'A'}
    assert set(second.loc[second.security_id=='2','symbol'])=={'RENAMED_A'}
    for name in ('feature_registry.parquet','target_registry.parquet','single_results.parquet','dual_results.parquet',
                 'tail_results.parquet','candidate_summary.parquet','candidate_event_paths.parquet','EVIDENCE_COMPLETE.json'):
        assert (root/name).exists()
    path=root/'candidate_event_paths.parquet'/f"{chosen[0]['key']}.parquet"
    path.unlink()
    def no_rebuild(*args): raise AssertionError('Completed feature builds must be reused')
    monkeypatch.setattr(Engine,'build',no_rebuild)
    again=runner.run_hf(research,machine,ROOT,Telemetry())
    assert path.exists() and again==result
    import os
    stat=(root/'feature_values/2025-05-01.parquet').stat()
    os.utime(root/'feature_values/2025-05-01.parquet',ns=(stat.st_atime_ns,stat.st_mtime_ns+1_000_000))
    with pytest.raises(RuntimeError,match='artifacts changed'):
        runner.run_hf(research,machine,ROOT,Telemetry())
