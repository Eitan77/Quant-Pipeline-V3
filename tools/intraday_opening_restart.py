"""Simple opening-auction imbalance hypotheses, all-year discovery only."""
import argparse,json
import duckdb,numpy as np,pandas as pd,exchange_calendars as xc
from competition_under2d import ROOT
from competition_scalp import metrics
from intraday_minute_restart import OUT as MINUTE

OUT=MINUTE.parent/'opening_mechanisms';OUT.mkdir(exist_ok=True)
LEVELS=[-1,0,1,2,3,4,5]

def prepare():
    with duckdb.connect() as c:
        c.execute('SET threads=4')
        f=c.execute('''SELECT p.security_id,p.symbol,p.session_date,p.close,p.split_factor,p.volume
          FROM read_parquet(?) p WHERE p.session_date<=DATE '2026-04-30' AND
          (p.symbol IN ('SPY','QQQ') OR EXISTS (SELECT 1 FROM read_parquet(?) m
            WHERE m.security_id=p.security_id AND m.symbol=p.symbol AND m.session_date=p.session_date AND m.in_universe))''',
          [str(ROOT/'cache/calculation_panels/daily_close.parquet'),'reference/sp500_pit_membership_daily.parquet']).fetchdf()
    f['session_date']=pd.to_datetime(f.session_date)
    assert not f.duplicated(['security_id','session_date']).any()
    f=f.sort_values(['security_id','session_date'],kind='stable')
    axes=json.loads((MINUTE/'axes.json').read_text());cp=np.load(MINUTE/'close.npy',mmap_mode='r');volume=np.load(MINUTE/'volume.npy',mmap_mode='r')
    d=pd.Index(axes['days']).get_indexer(f.session_date.dt.strftime('%Y-%m-%d'));s=pd.Index(axes['security_ids']).get_indexer(f.security_id)
    valid=(d>=0)&(s>=0);dd,ss=d[valid],s[valid]
    # Daily-panel aggregation included some half-day post-close prints. Use the
    # final observed regular-session trade and RTH volume from the verified cube.
    raw=np.array(cp[dd,ss,:]);positions=np.where(np.isfinite(raw),np.arange(390)[None,:],-1).max(axis=1)
    assert (positions>=0).all()
    f.loc[valid,'close']=raw[np.arange(len(raw)),positions]/f.loc[valid,'split_factor'].to_numpy()
    f.loc[valid,'volume']=np.nansum(volume[dd,ss,:],axis=1)
    f['daily_return']=f.groupby('security_id').close.transform(lambda x:np.log(x/x.shift(1)))
    f['prior_sigma']=f.groupby('security_id').daily_return.transform(lambda x:x.rolling(20,min_periods=20).std().shift(1))
    f['prior_close']=f.groupby('security_id').close.shift(1)
    f['prior_date']=f.groupby('security_id').session_date.shift(1)
    # Missing corporate actions make very large price resets ambiguous. Admit
    # only a clean prior 20-session scale, using information already observed.
    f['prior_scale_clean']=f.groupby('security_id').daily_return.transform(lambda x:(x.abs()>=np.log(2)).rolling(20,min_periods=20).max().shift(1)).eq(0)
    f['prior_dollar_volume']=f.groupby('security_id').apply(lambda x:(x.close*x.split_factor*x.volume).rolling(5,min_periods=5).mean().shift(1),include_groups=False).reset_index(level=0,drop=True)
    f.to_parquet(OUT/'daily_inputs.parquet',index=False)
    (OUT/'scope.json').write_text(json.dumps({'discovery':['2025-05-01','2026-04-30'],'holdouts_accessed':False,
      'economic_hypothesis':'Opening gaps relative to market can represent temporary auction imbalance or durable stock-specific repricing. First five completed minutes distinguish initial reversal from continuation.',
      'signal':'First completed minute close versus preceding session close, subtract SPY gap, normalize by preceding 20-session close-return volatility; absolute strength at least 0.5.',
      'mechanisms':['unconditional gap fade','gap fade with initial turn','gap continuation with initial confirmation'],
      'entry':'09:35 ET after first five completed one-minute bars; limit activation +5 seconds.',
      'holds_minutes':[15,30,60,120],'universe_controls':['all PIT stocks','top decile of preceding five-session dollar volume'],
      'ranking':'Largest observable standardized stock-specific gap first; fixed ten slots; one entry per stock/session.',
      'input_integrity':'Actual regular-session closes and volume. Exclude current gap price ratios outside [0.5,2] and prior 20-session histories containing a factor-two price reset; no future-action lookups.',
      'fees':0,'prescribed_bps_per_side':LEVELS,'thresholds_fit_to_outcomes':False,'bar_projection_is_execution_validation':False},indent=2))
    print('OPENING_INPUTS',len(f),'causally shifted daily rows',flush=True)

def screen():
    axes=json.loads((MINUTE/'axes.json').read_text());days=axes['days'];S=len(axes['symbols']);D=len(days)
    cp=np.load(MINUTE/'close.npy',mmap_mode='r');f=pd.read_parquet(OUT/'daily_inputs.parquet')
    sid=pd.Index(axes['security_ids']);day=pd.Index(days);d=day.get_indexer(f.session_date.dt.strftime('%Y-%m-%d'));s=sid.get_indexer(f.security_id)
    valid=(d>=0)&(s>=0);f=f[valid].copy();d,s=d[valid],s[valid]
    inputs={name:np.full((D,S),np.nan) for name in ['prior_sigma','prior_close','split_factor','prior_dollar_volume']}
    for name,array in inputs.items():array[d,s]=f[name].to_numpy()
    calendar=xc.get_calendar('XNYS',start='2025-04-01',end='2026-04-30').schedule.index
    previous=dict(zip(calendar.strftime('%Y-%m-%d')[1:],calendar.strftime('%Y-%m-%d')[:-1]))
    history_ok=np.zeros((D,S),bool);history_ok[d,s]=(f.prior_date.dt.strftime('%Y-%m-%d').to_numpy()==np.array([previous[days[i]] for i in d]))&f.prior_scale_clean.to_numpy()
    # Research-price adjustment cancels between dates; raw execution prices stay untouched.
    first=np.array(cp[:,:,0]);entry=np.array(cp[:,:,4]);spy=axes['symbols'].index('SPY')
    gap=np.log(first/inputs['split_factor']/inputs['prior_close'])
    relative_gap=gap-gap[:,spy,None];score=np.abs(relative_gap)/inputs['prior_sigma']
    early=np.log(entry/first);stocks=~np.isin(np.arange(S),[spy,axes['symbols'].index('QQQ')])
    eligible=history_ok&np.isfinite(score)&np.isfinite(entry)&(inputs['prior_sigma']>0)&stocks[None,:]&(np.abs(gap)<np.log(2))
    volume=np.where(eligible,inputs['prior_dollar_volume'],np.nan)
    cutoff=np.nanquantile(volume,.9,axis=1);liquid=volume>=cutoff[:,None]
    conditions={'gap_fade':np.ones((D,S),bool),'gap_fade_turn':early*relative_gap<0,'gap_continuation':early*relative_gap>0}
    records=[];nominations=[];rules=[]
    marks=np.array(cp);last=np.where(np.isfinite(marks),np.arange(390)[None,None,:],0);np.maximum.accumulate(last,axis=2,out=last)
    marks=np.take_along_axis(marks,last,axis=2)
    for mechanism,confirmation in conditions.items():
        direction=np.sign(relative_gap)*(1 if mechanism=='gap_continuation' else -1)
        for universe,mask in [('stocks',np.ones((D,S),bool)),('liquid_decile',liquid)]:
            potential=eligible&mask&confirmation&(score>=.5)
            rank=np.where(potential,score,-np.inf);chosen=np.argsort(-rank,axis=1,kind='stable')[:,:10]
            dd=np.repeat(np.arange(D),10);ss=chosen.ravel();keep=potential[dd,ss];dd,ss=dd[keep],ss[keep]
            for hold in [15,30,60,120]:
                cid=f'{mechanism}_{universe}_{hold}m';side=direction[dd,ss].astype('int8');ee=entry[dd,ss];xx=marks[dd,ss,4+hold]
                assert np.isfinite(xx).all(),'Unpriced exit reference; no result'
                for bps in LEVELS:
                    ret=side*(xx*(1-side*bps/1e4)/(ee*(1+side*bps/1e4))-1)
                    profit=pd.Series(ret).groupby(ss).sum().sort_values(ascending=False);trim=~np.isin(ss,profit.head(5).index)
                    records.append({'candidate_id':cid,'mechanism':mechanism,'universe':universe,'hold_minutes':hold,'bps':bps,'eligible_signals':int(potential.sum()),
                      'symbols':len(profit),'mean_ex_top5_bps':float(ret[trim].mean()*1e4),'stale_exit_references':int((~np.isfinite(cp[dd,ss,4+hold])).sum()),
                      **metrics(ret,dd,days,10)})
                nominations.append(pd.DataFrame({'candidate_id':cid,'day':dd,'symbol_code':ss,'signal_minute':4,'direction':side,
                  'score':score[dd,ss],'entry_price':ee,'exit_price':xx,'hold_minutes':hold}))
                rules.append({'candidate_id':cid,'threshold':.5,'hold_minutes':hold,'ranking':'Largest known market-relative standardized opening gap first','slots':10})
    result=pd.DataFrame(records);result.to_parquet(OUT/'bar_sensitivity.parquet',index=False)
    pd.concat(nominations,ignore_index=True).to_parquet(OUT/'nominations.parquet',index=False)
    pd.DataFrame(rules).to_parquet(OUT/'rules.parquet',index=False)
    for bps in [-1,0,5]:
        print('OPENING_BPS',bps,result[result.bps==bps].sort_values(['positive_months','without_best5_days_pct'],ascending=False)[
          ['candidate_id','trades','symbols','mean_trade_bps','return_pct','positive_months','max_dd_pct','mean_ex_top5_bps']].head(5).to_string(index=False),flush=True)

def audit():
    axes=json.loads((MINUTE/'axes.json').read_text());cp=np.load(MINUTE/'close.npy',mmap_mode='r')
    f=pd.read_parquet(OUT/'daily_inputs.parquet');groups={sid:g.sort_values('session_date') for sid,g in f.groupby('security_id',sort=False)}
    n=pd.read_parquet(OUT/'nominations.parquet');n=n[n.candidate_id=='gap_continuation_liquid_decile_60m'].copy()
    spy=axes['symbols'].index('SPY');max_error=0.
    for r in n.sample(min(100,len(n)),random_state=20260930).itertuples():
        date=pd.Timestamp(axes['days'][r.day]);g=groups[axes['security_ids'][r.symbol_code]];current=g[g.session_date==date].iloc[0];past=g[g.session_date<date]
        prices=past.close.to_numpy();returns=np.log(prices[1:]/prices[:-1]);sigma=returns[-20:].std(ddof=1)
        assert np.isclose(sigma,current.prior_sigma,rtol=1e-12)
        assert current.prior_close==prices[-1]
        assert np.isclose((past.close*past.split_factor*past.volume).tail(5).mean(),current.prior_dollar_volume)
        sg=groups[axes['security_ids'][spy]];sp=sg[sg.session_date==date].iloc[0]
        gap=np.log(cp[r.day,r.symbol_code,0]/current.split_factor/prices[-1]);market=np.log(cp[r.day,spy,0]/sp.split_factor/sp.prior_close)
        score=abs(gap-market)/sigma;max_error=max(max_error,abs(score-r.score))
        assert r.direction==np.sign(gap-market) and np.log(cp[r.day,r.symbol_code,4]/cp[r.day,r.symbol_code,0])*r.direction>0
        assert r.entry_price==cp[r.day,r.symbol_code,4]
    assert max_error<1e-10
    (OUT/'input_audit.json').write_text(json.dumps({'candidate':'gap_continuation_liquid_decile_60m','sampled_nominations':min(100,len(n)),
      'maximum_independent_signal_error':max_error,'independent_prefix_prior_volatility_and_liquidity_checks':True,
      'exact_raw_entry_prices_and_correct_sides':True,'input_lookbacks_use_only_completed_previous_sessions':True},indent=2))
    d=n.day.to_numpy();s=n.symbol_code.to_numpy();side=n.direction.to_numpy();paths=np.array(cp[d,s,4:125])
    ret=side[:,None]*(paths/n.entry_price.to_numpy()[:,None]-1)*1e4
    profile=pd.DataFrame({'minutes_after_entry':np.arange(121),'mean_bps':np.nanmean(ret,axis=0),'covered_trades':np.isfinite(ret).sum(axis=0)})
    profile.to_parquet(OUT/'primary_close_path_profile.parquet',index=False)
    print('OPENING_AUDIT',min(100,len(n)),'independent prior-history checks; max signal error',max_error,flush=True)
    print(profile.iloc[[0,5,15,30,60,120]].to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','screen','audit']);a=p.parse_args();globals()[a.stage]()
