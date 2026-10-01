"""Enforce known regular-session close in intraday probe and full VWAP intentions."""
import json
from pathlib import Path
import numpy as np,pandas as pd,duckdb,exchange_calendars as xc
from competition_fresh_search import OUT
from competition_under2d import ROOT

FULL=OUT/'intraday_vwap_full';FULL.mkdir(exist_ok=True)
SHORT=OUT/'intraday_rebound_120_full';SHORT.mkdir(exist_ok=True)
def run():
    probe=OUT/'intraday_limit_probe'
    ledger=pd.read_parquet(OUT/'trades_intraday_5m.parquet')
    inputs={probe:pd.read_parquet(probe/'policy_pool.parquet')}
    for folder,candidate in [(FULL,'intraday_rebound_vwap'),(SHORT,'intraday_rebound_shorter')]:
        f=ledger[ledger.candidate_id==candidate].copy();f['rank_score']=0;inputs[folder]=f
    schedule=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    closemap=dict(zip(schedule.index.strftime('%Y-%m-%d'),pd.to_datetime(schedule['close'],utc=True)-pd.Timedelta(minutes=1)))
    points=[]
    for folder,f in inputs.items():
        if 'original_governed_exit_ts' not in f:f['original_governed_exit_ts']=f.exit_ts
        dates=f.entry_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d');end=pd.to_datetime(dates.map(closemap),utc=True)
        f['known_session_end']=end;f['calendar_capped']=pd.to_datetime(f.original_governed_exit_ts,utc=True)>end;f['exit_ts']=pd.to_datetime(f.exit_ts,utc=True).where(~f.calendar_capped,end)
        f=f[f.entry_ts<f.known_session_end].copy();inputs[folder]=f
        points.append(f.loc[f.calendar_capped,['security_id','exit_ts']].rename(columns={'exit_ts':'stamp'}))
    points=pd.concat(points).drop_duplicates();points['date']=points.stamp.dt.tz_convert('America/New_York').dt.date
    expanded=pd.concat([points.assign(bar_ts=points.stamp-pd.Timedelta(minutes=k)) for k in range(6)])
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    dates=','.join("DATE '"+str(x)+"'" for x in points.date.unique())
    with duckdb.connect(source,read_only=True) as c:
        c.execute("SET memory_limit='4GB'");c.execute('SET threads=4');c.register('needed',expanded)
        b=c.execute(f'''SELECT n.security_id,n.stamp,b.bar_start_ts_utc bar_ts,b.availability_ts_utc,b.open,b.high,b.low,b.close,b.symbol
          FROM bars_1m_raw b JOIN needed n ON b.security_id=n.security_id AND b.bar_start_ts_utc=n.bar_ts
          WHERE b.session_date IN ({dates})''').fetchdf()
    refs=b[(b.bar_ts<b.stamp)&(b.availability_ts_utc<=b.stamp)].sort_values('bar_ts').drop_duplicates(['security_id','stamp'],keep='last')
    endpoint=b[b.bar_ts==b.stamp][['security_id','stamp','symbol','open','high','low','close']]
    basebars=pd.read_parquet(OUT/'endpoint_bars_intraday_5m.parquet')
    for folder,f in inputs.items():
        f=f.drop(columns=['capped_exit_reference'],errors='ignore')
        f=f.merge(refs[['security_id','stamp','close']].rename(columns={'stamp':'exit_ts','close':'capped_exit_reference'}),on=['security_id','exit_ts'],how='left',validate='many_to_one')
        f['exit_price']=f.capped_exit_reference.where(f.calendar_capped,f.exit_price)
        assert f.exit_price.gt(0).all(),'Missing causal early-close reference'
        assert (f.exit_ts<=f.known_session_end).all()
        f.to_parquet(folder/'policy_pool.parquet',index=False)
        pts=pd.concat([f[['security_id','entry_ts']].rename(columns={'entry_ts':'stamp'}),f[['security_id','exit_ts']].rename(columns={'exit_ts':'stamp'})]).drop_duplicates()
        allbars=pd.concat([basebars,endpoint]);allbars['stamp']=pd.to_datetime(allbars.stamp,utc=True).dt.as_unit('ns');pts['stamp']=pd.to_datetime(pts.stamp,utc=True).dt.as_unit('ns')
        bars=allbars.drop_duplicates(['security_id','stamp']).merge(pts,on=['security_id','stamp'],validate='one_to_one')
        bars.to_parquet(folder/'policy_endpoint_bars.parquet',index=False)
        scope=json.loads((folder/'scope.json').read_text()) if (folder/'scope.json').exists() else {}
        scope.update({'known_calendar_capped_exits':int(f.calendar_capped.sum()),'scheduled_signal_intentions':len(f),'fees':0,'full_annual_intention_ledger':folder!=probe,
          'intention_selection':'Original deterministic 10-slot scheduled-hold allocation, before quotes; misses retain their nomination slot until the scheduled exit. No hindsight substitution.',
          'complete_annual_strategy_validation':False,'out_of_sample_accessed':False})
        (folder/'scope.json').write_text(json.dumps(scope,indent=2));print(folder.name,'rows',len(f),'calendar capped',int(f.calendar_capped.sum()),flush=True)

if __name__=='__main__':run()
