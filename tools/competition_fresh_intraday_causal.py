"""Signal-only two-hour rebound intentions, clock-based holds, no future target gate."""
import json
import numpy as np,pandas as pd,duckdb,torch,exchange_calendars as xc
from competition_fresh_search import OUT
from competition_under2d import ROOT,EvidenceReader,decode_packed_bins
from competition_fresh_capacity import allocate

DEST=OUT/'intraday_rebound_120_causal';DEST.mkdir(exist_ok=True)
def prepare():
    r=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    fa='distance_from_low__30m__raw__intraday_5m';fb='ema_distance__30m__raw__intraday_5m'
    aa=r.read_columns('bins',[fa],0,r.rows)[:,0];bb=r.read_columns('bins',[fb],0,r.rows)[:,0]
    a=decode_packed_bins(aa,5);b=decode_packed_bins(bb,5)
    device=torch.device('cuda:0');mask=(torch.as_tensor(a,device=device)==4)&(torch.as_tensor(b,device=device)==0)
    ix=torch.nonzero(mask).flatten().cpu().numpy();del mask
    indices=pd.DataFrame({'observation_id':ix});con=duckdb.connect();con.register('selected',indices)
    f=con.execute('''SELECT o.observation_id,o.security_id,o.session_date,o.decision_ts
        FROM read_parquet(?) o JOIN selected s USING(observation_id)''',[str(ROOT/r.grid['observations'])]).fetchdf();con.close()
    active_observations=len(f);f=f.sort_values(['security_id','session_date','decision_ts'],kind='stable')
    prior=f.groupby(['security_id','session_date']).decision_ts.shift()
    f=f[(f.decision_ts-prior)!=pd.Timedelta(minutes=5)].copy()
    f['entry_ts']=pd.to_datetime(f.decision_ts,utc=True)+pd.Timedelta(minutes=1)
    f['exit_ts']=f.entry_ts+pd.Timedelta(minutes=120)
    schedule=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    closemap=dict(zip(schedule.index.strftime('%Y-%m-%d'),pd.to_datetime(schedule['close'],utc=True)-pd.Timedelta(minutes=1)))
    day=f.entry_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d');closes=pd.to_datetime(day.map(closemap),utc=True)
    f=f[(f.exit_ts<=closes)&(f.entry_ts>f.decision_ts)].copy()
    a10=decode_packed_bins(aa,10);b10=decode_packed_bins(bb,10)
    f['rank_score']=a10[f.observation_id.to_numpy()]-b10[f.observation_id.to_numpy()]
    f['candidate_id']='causal_intraday_rebound_120';f['direction']=1;f['target_id']='clock_120m__raw__intraday_5m'
    f.to_parquet(DEST/'eligible_signal_episodes.parquet',index=False)
    ledgers=[]
    for ranked in [False,True]:
        g=allocate(f,10,ranked);g['nomination_ranked']=ranked;ledgers.append(g)
    union=pd.concat(ledgers).drop_duplicates('observation_id').drop(columns='nomination_ranked')
    points=pd.concat([union[['security_id','entry_ts']].rename(columns={'entry_ts':'stamp'}),union[['security_id','exit_ts']].rename(columns={'exit_ts':'stamp'})]).drop_duplicates()
    needed=pd.concat([points.assign(bar_ts=points.stamp-pd.Timedelta(minutes=k)) for k in range(6)])
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    with duckdb.connect(source,read_only=True) as c:
        c.execute("SET memory_limit='5GB'");c.execute('SET threads=4');c.register('needed',needed)
        prices=c.execute('''SELECT n.security_id,n.stamp,b.bar_start_ts_utc bar_ts,b.availability_ts_utc,b.symbol,b.open,b.high,b.low,b.close
          FROM bars_1m_raw b JOIN needed n ON b.security_id=n.security_id AND b.bar_start_ts_utc=n.bar_ts
          WHERE b.session_date BETWEEN DATE '2025-05-01' AND DATE '2026-04-30' ''').fetchdf()
    refs=prices[(prices.bar_ts<prices.stamp)&(prices.availability_ts_utc<=prices.stamp)].sort_values('bar_ts').drop_duplicates(['security_id','stamp'],keep='last')
    bars=prices[prices.bar_ts==prices.stamp][['security_id','stamp','symbol','open','high','low','close']].drop_duplicates(['security_id','stamp'])
    union=union.merge(refs[['security_id','stamp','symbol','close']].rename(columns={'stamp':'entry_ts','close':'entry_price'}),on=['security_id','entry_ts'],how='left',validate='many_to_one')
    union=union.merge(refs[['security_id','stamp','close']].rename(columns={'stamp':'exit_ts','close':'exit_price'}),on=['security_id','exit_ts'],how='left',validate='many_to_one')
    union.to_parquet(DEST/'policy_pool.parquet',index=False);bars.to_parquet(DEST/'policy_endpoint_bars.parquet',index=False)
    pd.concat(ledgers).to_parquet(DEST/'nomination_policies.parquet',index=False)
    stage=[]
    for ranked in [False,True]:
        g=union[union.observation_id.isin(ledgers[int(ranked)].observation_id)].copy();g['gross_bps']=(g.exit_price/g.entry_price-1)*1e4
        monthly=g.groupby(g.entry_ts.dt.strftime('%Y-%m')).gross_bps.mean()
        for bps in [-1,0,1,2,3,4,5]:
            ret=g.exit_price*(1-bps/1e4)/(g.entry_price*(1+bps/1e4))-1
            stage.append({'ranked':ranked,'bps':bps,'nominations':len(g),'priced_pairs':int(ret.notna().sum()),'mean_nomination_bps':ret.mean()*1e4,'fixed_base_pct':ret.sum()/10*100,'positive_gross_months':int((monthly>0).sum())})
    pd.DataFrame(stage).to_parquet(DEST/'nomination_bar_sensitivity.parquet',index=False)
    (DEST/'scope.json').write_text(json.dumps({'features':[fa,fb],'resolution':5,'cells':[20],'feature_only_active_observations':active_observations,
        'causal_episodes':len(f),'target_validity_used_for_selection':False,'holding':'120 elapsed minutes, enter only if the full hold and liquidation window fit the known regular-session calendar.',
        'nomination':'10 scheduled reservation lanes; compare stable hash with the same features ranked on fine bins. No quote-conditioned hindsight nominations.',
        'signal_age':'Entry one minute after the completed five-minute decision.', 'fees':0,'out_of_sample_accessed':False},indent=2))
    print(pd.DataFrame(stage).query('bps==0').to_string(index=False),flush=True)

if __name__=='__main__':prepare()
