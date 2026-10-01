"""Independent completed-minute reference for every requested feature and label.

This uses scalar/sliced definitions and supplied prior state, not the engine's
rolling, percentile, projection or model-fitting helpers.
"""
from collections import deque
from types import SimpleNamespace
import numpy as np
import pandas as pd
import duckdb
from quant_pipeline.hf_intraday.engine import HFEngine
from quant_pipeline.hf_intraday.spec import FEATURES,TARGETS,validate_pack

def test_all_117_features_and_31_targets_against_independent_reference(monkeypatch):
    import quant_pipeline.hf_intraday.engine as module
    rng=np.random.default_rng(433);M=80;S=9;T=45;eps=1e-12
    c=100*np.exp(np.cumsum(rng.normal(0,.001,(M,S)),axis=0))
    o=c*np.exp(rng.normal(0,.0002,(M,S)));h=np.maximum(o,c)+rng.uniform(.02,.2,(M,S))
    l=np.minimum(o,c)-rng.uniform(.02,.2,(M,S));w=(h+l+c)/3
    v=rng.uniform(1000,3000,(M,S));n=rng.integers(10,100,(M,S)).astype(float)
    market=100*np.exp(np.cumsum(rng.normal(0,.001,M)))
    loads=np.linalg.qr(rng.normal(size=(S,5)))[0];beta=np.linspace(.5,1.5,S)
    model=dict(beta=beta,loadings=loads,peers=[],lead1=[],lead2=[],incoming=np.arange(S)+.1,outgoing=np.arange(S)+.2)
    for i in range(S):
        model['peers'].append(((i+np.arange(1,4))%S,np.array([.2,.3,.5])))
        model['lead1'].append(np.array([.3,-.1,.2]))
        model['lead2'].append(np.array([.1,-.2,.3,.2,.1,-.1]))
    monkeypatch.setattr(module,'fit_models',lambda *args:model)
    engine=HFEngine(validate_pack({}))
    keys=set(FEATURES)|{'e1','e2','e3','e5','r1','abs_e1','range','volume','dollar_volume','trade_count',
        'avg_trade_size','dollar_per_trade','impact','prevol','dispersion','m1','m2','market_vol','u1','u2','session_range','volratio'}
    previous=[{k:rng.normal(0,.002,(M,S)) for k in sorted(keys)} for _ in range(60)]
    engine.history=deque(previous,maxlen=60)
    liquidity=[rng.uniform(10_000,200_000,(M,S)) for _ in range(20)]
    engine.liquidity=deque(liquidity,maxlen=20);engine.prior_close=np.linspace(99,101,S)
    f,y,_,_=engine.build(dict(close=c,open=o,high=h,low=l,vwap=w,volume=v,trade_count=n,split_factor=np.ones_like(c)),market,np.ones(S,bool))
    def percentile(x):
        return np.array([(np.sum(x<value)+.5*np.sum(x==value))/len(x) for value in x])
    def tod(k,value,kind='tail',t=T):
        past=np.stack([day[k][t] for day in previous])
        if kind=='tail': return 2*((past<value).sum(axis=0)+.5*(past==value).sum(axis=0))/60-1
        if kind=='q99': return np.quantile(past,.99,axis=0)
        med=np.median(past,axis=0)
        return (value-med)/(1.4826*np.median(abs(past-med),axis=0)+eps)
    def past_return(prices,horizon):
        result=np.full_like(prices,np.nan)
        for t in range(horizon,M): result[t]=prices[t]/prices[t-horizon]-1
        return result
    r={z:past_return(c,z) for z in (1,2,3,5)};m={z:past_return(market,z) for z in (1,2,3,5)}
    e={z:r[z]-m[z][:,None]*beta for z in r}
    u={z:r[z]-r[z]@loads@loads.T for z in (1,2)}
    dv=w*v;bar_range=(h[T]-l[T])/c[T-1];width=h-l
    out={}
    for z in r: out[f'resid_tod_tail_{z}m']=tod(f'e{z}',e[z][T])
    out['ret_tod_tail_1m']=tod('r1',r[1][T]);out['ret_tod_robz_1m']=tod('r1',r[1][T],'robz')
    out['resid_tod_robz_1m']=tod('e1',e[1][T],'robz')
    prestd=np.std(e[1][T-30:T],axis=0,ddof=1)
    out['resid_prevol_norm_1m']=e[1][T]/(prestd+eps)
    out['resid_prevol_norm_2m']=e[2][T]/(prestd*np.sqrt(2)+eps)
    out['shock_accel_1m']=e[1][T]-e[1][T-1]
    q=tod('abs_e1',abs(e[1][T]),'q99')
    out['shock_excess_1pct']=np.sign(e[1][T])*np.maximum(abs(e[1][T])-q,0)/(q+eps)
    out['idio_share_1m']=abs(e[1][T])/(abs(e[1][T])+abs(beta*m[1][T])+eps)
    out['body_ret_1m']=c[T]/o[T]-1;out['gap_ret_1m']=o[T]/c[T-1]-1
    out['body_share_1m']=abs(c[T]-o[T])/(width[T]+eps)
    clv=2*(c[T]-l[T])/(width[T]+eps)-1;out['clv_signed_1m']=clv
    out['dir_close_extreme_1m']=np.sign(e[1][T])*clv
    for z in (3,5,10):
        window=e[1][T-z+1:T+1];total=abs(window).sum(axis=0)
        out[f'path_eff_{z}m']=abs(window.sum(axis=0))/total
        if z!=10: out[f'last1_abs_share_{z}m']=abs(e[1][T])/total
    streak=np.ones(S)
    for i in range(S):
        for t in range(T-1,-1,-1):
            if np.sign(e[1][t,i])!=np.sign(e[1][T,i]): break
            streak[i]+=1
    out['same_sign_streak_1m']=streak*np.sign(e[1][T])
    out['sign_switch_rate_5m']=np.mean([np.sign(e[1][t])!=np.sign(e[1][t-1]) for t in range(T-4,T+1)],axis=0)
    tail=np.stack([tod('e1',e[1][t],t=t) for t in range(M)]);tail[0]=np.nan
    events=abs(tail)>=.98
    for z in (5,15): out[f'tail_event_count_{z}m']=events[T-z+1:T+1].sum(axis=0)
    out['range_tod_tail_1m']=tod('range',bar_range)
    logs=dict(volume=np.log1p(v[T]),dollar_volume=np.log1p(dv[T]),trade_count=np.log1p(n[T]),
              avg_trade_size=np.log1p(v[T]/np.maximum(n[T],1)),dollar_per_trade=np.log1p(dv[T]/np.maximum(n[T],1)))
    for key,val in logs.items():out[key+'_tod_tail_1m']=tod(key,val)
    impact=abs(e[1][T])/(dv[T]/1e6+eps)
    out['impact_per_dollar_1m']=impact;out['impact_tod_tail_1m']=tod('impact',np.log1p(impact))
    out['range_per_dollar_1m']=bar_range/(dv[T]/1e6+eps)
    dz=tod('dollar_volume',logs['dollar_volume'],'robz');vz=tod('volume',logs['volume'],'robz')
    nz=tod('trade_count',logs['trade_count'],'robz');ez=tod('abs_e1',abs(e[1][T]),'robz')
    out['effort_result_1m']=dz-ez;out['volume_return_mismatch_1m']=vz-ez;out['trade_intensity_mismatch_1m']=nz-ez
    out['prevol_tod_tail_30m']=tod('prevol',np.sqrt((e[1][T-30:T]**2).sum(axis=0)))
    liq=percentile(np.median(np.concatenate(liquidity),axis=0));out['liquidity_rank_20d']=liq
    out['signed_dollar_pressure_1m']=clv*dz;out['signed_volume_pressure_1m']=clv*vz
    vc=(c[T]-w[T])/(width[T]+eps);out['vwap_close_location_1m']=vc;out['vwap_bar_location_1m']=(w[T]-l[T])/(width[T]+eps)
    out['vwap_pressure_1m']=vc*dz
    upper=(h[T]-np.maximum(o[T],c[T]))/(width[T]+eps);lower=(np.minimum(o[T],c[T])-l[T])/(width[T]+eps)
    out['upper_rejection_pressure_1m']=upper*np.maximum(dz,0);out['lower_rejection_pressure_1m']=lower*np.maximum(dz,0)
    out['wick_skew_pressure_1m']=(lower-upper)*np.maximum(dz,0)
    out['pressure_return_divergence_1m']=clv*dz-out['resid_tod_robz_1m']
    out['absorption_score_1m']=clv*np.maximum(dz-abs(out['resid_tod_robz_1m']),0)
    for z in (1,2,5):out[f'resid_cs_rank_{z}m']=percentile(e[z][T])
    out['resid_rank_velocity_1m']=percentile(e[1][T])-percentile(e[1][T-1])
    out['resid_rank_accel_1m']=percentile(e[1][T])-2*percentile(e[1][T-1])+percentile(e[1][T-2])
    disp=np.std(e[1][T],ddof=1);out['resid_dispersion_1m']=np.full(S,disp)
    out['resid_dispersion_tod_tail_1m']=tod('dispersion',np.full(S,disp))
    out['tail_breadth_down_1m']=np.full(S,np.mean(tail[T]<=-.98));out['tail_breadth_up_1m']=np.full(S,np.mean(tail[T]>=.98))
    out['tail_breadth_imbalance_1m']=out['tail_breadth_up_1m']-out['tail_breadth_down_1m']
    centered=e[1][T]-e[1][T].mean();second=np.mean(centered**2)
    out['cs_resid_skew_1m']=np.full(S,np.sqrt(S*(S-1))/(S-2)*np.mean(centered**3)/second**1.5)
    out['cs_resid_kurt_1m']=np.full(S,(S-1)/((S-2)*(S-3))*((S+1)*(np.mean(centered**4)/second**2-3)+6))
    out['median_stock_ret_1m']=np.full(S,np.median(r[1][T]));out['benchmark_minus_median_1m']=m[1][T]-out['median_stock_ret_1m']
    for z in (1,2):out[f'market_tod_tail_{z}m']=tod(f'm{z}',np.full(S,m[z][T]))
    out['market_vol_tod_tail_5m']=tod('market_vol',np.full(S,np.sqrt((m[1][T-4:T+1]**2).sum())))
    out['lagged_market_response_gap_1m']=beta*m[1][T-1]-r[1][T]
    out['breadth_positive_1m']=np.full(S,np.mean(r[1][T]>0))
    out['breadth_change_1m']=out['breadth_positive_1m']-np.mean(r[1][T-1]>0)
    for z in (1,2):out[f'factor_resid_{z}m']=u[z][T];out[f'factor_resid_tod_tail_{z}m']=tod(f'u{z}',u[z][T])
    out['factor_common_share_1m']=np.minimum(abs(r[1][T]-u[1][T])/(abs(r[1][T])+eps),10)
    out['factor_resid_cs_rank_1m']=percentile(u[1][T])
    pkeys=['peer_basket_resid_1m','peer_gap_1m','peer_gap_2m','peer_gap_velocity_1m','peer_lead_pred_1m','peer_lead_pred_2m',
           'peer_breadth_sign_1m','peer_shock_breadth_1m','peer_dispersion_1m','peer_move_concentration_1m','peer_leader_count_1m','leader_liquidity_advantage']
    out.update({key:np.zeros(S) for key in pkeys})
    utail=tod('u1',u[1][T])
    for i,(js,weights) in enumerate(model['peers']):
        pu=u[1][T,js];basket=sum(weights*pu);pred=sum(model['lead1'][i]*pu)
        out['peer_basket_resid_1m'][i]=basket;out['peer_gap_1m'][i]=basket-u[1][T,i]
        out['peer_gap_2m'][i]=sum(weights*u[2][T,js])-u[2][T,i]
        out['peer_gap_velocity_1m'][i]=basket-u[1][T,i]-(sum(weights*u[1][T-1,js])-u[1][T-1,i])
        out['peer_lead_pred_1m'][i]=pred
        out['peer_lead_pred_2m'][i]=sum(model['lead2'][i][:3]*pu)+sum(model['lead2'][i][3:]*u[1][T-1,js])
        out['peer_breadth_sign_1m'][i]=sum(weights*(np.sign(pu)==np.sign(pred)))
        out['peer_shock_breadth_1m'][i]=sum(weights*(utail[js]*np.sign(pred)>=.98))
        out['peer_dispersion_1m'][i]=np.sqrt(sum(weights*(pu-basket)**2))
        absolute=abs(weights*pu);out['peer_move_concentration_1m'][i]=sum((absolute/sum(absolute))**2)
        out['peer_leader_count_1m'][i]=sum(abs(model['lead1'][i]*pu)>=.1*abs(pred))
        out['leader_liquidity_advantage'][i]=sum(weights*liq[js])-liq[i]
    out['network_lead_strength']=model['outgoing'];out['network_follow_strength']=model['incoming']
    svwap=np.cumsum(w*v,axis=0)/np.cumsum(v,axis=0)
    sh=h[:T+1].max(axis=0);sl=l[:T+1].min(axis=0)
    out['dist_session_vwap']=c[T]/svwap[T]-1;out['dist_session_open']=c[T]/o[0]-1
    out['dist_prior_close']=c[T]/np.linspace(99,101,S)-1;out['dist_session_high']=c[T]/sh-1;out['dist_session_low']=c[T]/sl-1
    out['session_range_expansion_tod']=(sh-sl)/(np.median(np.stack([day['session_range'][T] for day in previous]),axis=0)+eps)-1
    out['same_minute_resid_lag1d']=previous[-1]['e1'][T]
    for z in (5,20):out[f'same_minute_resid_mean{z}d']=np.mean([day['e1'][T] for day in previous[-z:]],axis=0)
    out['same_minute_rank_mean20d']=np.mean([day['resid_cs_rank_1m'][T] for day in previous[-20:]],axis=0)
    out['prevol_ratio_5_30']=np.sqrt((e[1][T-4:T+1]**2).sum(axis=0))/(np.sqrt((e[1][T-34:T-4]**2).sum(axis=0))*np.sqrt(5/30)+eps)
    out['range_ratio_5_30']=width[T-4:T+1].sum(axis=0)/(width[T-34:T-4].sum(axis=0)*5/30+eps)
    out['dollar_volume_ratio_5_30']=dv[T-4:T+1].sum(axis=0)/(dv[T-34:T-4].sum(axis=0)*5/30+eps)
    out['squeeze_score_5_30']=-tod('volratio',out['prevol_ratio_5_30'],'robz')
    for z in (5,15):
        out[f'breakout_dist_high_{z}m']=c[T]/c[T-z:T].max(axis=0)-1
        out[f'breakout_dist_low_{z}m']=c[T]/c[T-z:T].min(axis=0)-1
    out['dist_orh_5m']=c[T]/h[:5].max(axis=0)-1;out['dist_orl_5m']=c[T]/l[:5].min(axis=0)-1
    vage=np.zeros(S);bage=np.full(S,np.nan);since=np.full(S,30.);recovery=np.full(S,np.nan)
    for i in range(S):
        sides=np.sign(c[:T+1,i]-svwap[:T+1,i]);cross=np.r_[0,np.flatnonzero(sides[1:]!=sides[:-1])+1][-1]
        vage[i]=sides[-1]*(T-cross)
        for t in range(15,T+1):
            if c[t,i]>max(c[t-15:t,i]):bage[i]=T-t
            elif c[t,i]<min(c[t-15:t,i]):bage[i]=-(T-t)
        shocks=np.flatnonzero(events[1:T,i])+1
        if len(shocks):
            shock=shocks[-1];since[i]=min(T-shock,30)
            if T-shock<=3:recovery[i]=-np.sign(e[1][shock,i])*(c[T,i]/c[shock,i]-1)
    out['vwap_cross_age_signed']=vage;out['breakout_age_signed_15m']=bage;out['minutes_since_tail_event']=since
    out['post_shock_recovery_1m']=np.where(events[T-1],-np.sign(e[1][T-1])*r[1][T],np.nan)
    out['post_shock_recovery_3m']=recovery
    out['shock_cluster_score_15m']=sum(events[T-age]*np.exp(-age/5) for age in range(1,16))
    out['vol_accel_1_5']=abs(e[1][T])/(np.sqrt((e[1][T-4:T+1]**2).sum(axis=0))/np.sqrt(5)+eps)
    assert set(out)==set(FEATURES)
    for key in FEATURES:np.testing.assert_allclose(f[key][T],out[key],atol=1e-7,rtol=1e-9,equal_nan=True,err_msg=key)
    labels={}
    for z in (1,2,3,5,10,15,30):
        raw=c[T+z]/c[T]-1
        labels[f'fwd_raw_{z}m']=raw;labels[f'fwd_beta_resid_{z}m']=raw-beta*(market[T+z]/market[T]-1)
        labels[f'fwd_factor_resid_{z}m']=raw-raw@loads@loads.T
    for z in range(1,6):
        raw=c[T+z]/c[T+z-1]-1;labels[f'step_raw_p{z}']=raw;labels[f'step_factor_resid_p{z}']=raw-raw@loads@loads.T
    assert set(labels)==set(TARGETS)
    for key in TARGETS:np.testing.assert_allclose(y[key][T],labels[key],atol=1e-12,rtol=1e-9,err_msg=key)

def test_daily_eligibility_does_not_depend_on_current_day_bars(tmp_path):
    from quant_pipeline.hf_intraday.runner import load_daily_eligibility
    path=tmp_path/'source.duckdb';dates=pd.date_range('2025-05-01',periods=25)
    bars=pd.DataFrame([dict(security_id=sid,session_date=date.date(),bar_start_ts_utc=date,close=100.,vwap=100.,volume=10.)
        for sid in ('a','b') for date in dates])
    membership=pd.DataFrame([dict(security_id=sid,session_date=date.date(),in_universe=True) for sid in ('a','b') for date in dates])
    master=pd.DataFrame({'security_id':['a','a','b'],'symbol':['AAA','RENAMED','BBB']})
    with duckdb.connect(str(path)) as con:
        for name,frame in [('bars',bars),('membership',membership),('master',master)]:
            con.register('frame',frame);con.execute(f'CREATE TABLE {name} AS SELECT * FROM frame')
    core=SimpleNamespace(config=SimpleNamespace(source=SimpleNamespace(duckdb_path=str(path),bars_1m_raw_table='bars',membership_table='membership',security_master_table='master'),
        universe=dict(minimum_price=3.,minimum_prior_20d_median_dollar_volume=100.)))
    names,before=load_daily_eligibility(core,'2025-05-01','2025-05-25')
    assert names.security_id.tolist()==['a','b']
    assert not names.security_id.duplicated().any()
    with duckdb.connect(str(path)) as con:con.execute("DELETE FROM bars WHERE session_date=DATE '2025-05-25'")
    _,after=load_daily_eligibility(core,'2025-05-01','2025-05-25')
    mask=before.session_date.astype(str).str.startswith('2025-05-25')
    assert before.loc[mask,'eligible'].all()
    pd.testing.assert_frame_equal(before.sort_values(['security_id','session_date']).reset_index(drop=True),after.sort_values(['security_id','session_date']).reset_index(drop=True))

def test_prior_only_model_fit_and_lead_response_offsets():
    from quant_pipeline.hf_intraday.math import fit_models
    rng=np.random.default_rng(221);D=20;M=40;S=9
    returns=rng.normal(0,.001,(D,M,S));market=rng.normal(0,.001,(D,M));returns[:,:,8]=np.nan
    cfg=validate_pack({'model_min_rows':100,'peer_count':3})
    model=fit_models(list(returns),list(market),np.ones(S,bool),cfg)
    flat=returns[:,:,:8].reshape(-1,8);m=market.ravel()
    for i in range(8):
        slope=np.linalg.lstsq(np.column_stack((np.ones(len(m)),m)),flat[:,i],rcond=None)[0][1]
        np.testing.assert_allclose(model['beta'][i],slope,atol=1e-12)
    assert np.isnan(model['beta'][8]) and np.isnan(model['outgoing'][8])
    loads=model['loadings'][:8];np.testing.assert_allclose(loads.T@loads,np.eye(5),atol=1e-12)
    covariance=np.cov(flat,rowvar=False);eigen=np.diag(loads.T@covariance@loads)
    np.testing.assert_allclose(covariance@loads,loads*eigen,atol=1e-12)
    u=returns.copy();u[:,:,:8]=returns[:,:,:8]-returns[:,:,:8]@loads@loads.T
    corr=np.corrcoef(u[:,:,:8].reshape(-1,8),rowvar=False)
    def reference_fit(x,y):
        x=np.array(x);y=np.array(y);scale=x.std(axis=0);z=x/scale
        augmented=np.vstack((z,np.sqrt(cfg['ridge']*len(z))*np.eye(z.shape[1])))
        response=np.r_[y,np.zeros(z.shape[1])]
        return np.linalg.lstsq(augmented,response,rcond=None)[0]/scale
    for i in range(8):
        js,weights=model['peers'][i]; assert i not in js and 8 not in js
        expected_js=sorted((j for j in range(8) if j!=i),key=lambda j:(-abs(corr[i,j]),j))[:3]
        np.testing.assert_array_equal(js,expected_js)
        np.testing.assert_allclose(weights,abs(corr[i,js])/sum(abs(corr[i,js])),atol=1e-12)
        x=[];y=[];x2=[];y2=[]
        for d in range(D):
            for t in range(M-1):x.append(u[d,t,js]);y.append(u[d,t+1,i])
            for t in range(1,M-2):x2.append(np.r_[u[d,t,js],u[d,t-1,js]]);y2.append(u[d,t+2,i])
        np.testing.assert_allclose(model['lead1'][i],reference_fit(x,y),atol=1e-10,rtol=1e-9)
        np.testing.assert_allclose(model['lead2'][i],reference_fit(x2,y2),atol=1e-10,rtol=1e-9)

def test_calendar_cutoff_and_exact_prior_close():
    from quant_pipeline.hf_intraday.runner import regular_day
    from quant_pipeline.alpha_discovery.data.calendar import schedule
    row=schedule('2025-07-03','2025-07-03').iloc[0]
    starts=[row.market_close-pd.Timedelta(minutes=1),row.market_close+pd.Timedelta(minutes=10)]
    frame=pd.DataFrame({'bar_start_ts_utc':starts,'close':[100.,200.]})
    selected=regular_day(frame,row.market_open,row.market_close)
    assert selected.close.tolist()==[100.]
    M=40;S=9;prices=np.full((M,S),100.)
    bars={k:prices.copy() for k in ('close','open','high','low','vwap')}
    bars.update(volume=np.full_like(prices,1000.),trade_count=np.full_like(prices,50.),session_end_minute=39)
    bars['close'][39,0]=np.nan
    market=np.full(M,100.);market[39]=np.nan
    engine=HFEngine(validate_pack({}));engine.build(bars,market,np.ones(S,bool))
    assert np.isnan(engine.prior_close[0])
    np.testing.assert_array_equal(engine.prior_close[1:],100.)
