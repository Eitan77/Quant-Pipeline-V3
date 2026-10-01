"""Matched causal timing ablations of the frozen daily dislocation state."""
import argparse,contextlib,io,json,time,threading
from pathlib import Path
import numpy as np,pandas as pd,duckdb,exchange_calendars as xc
import competition_fresh_quotes as engine
import competition_fresh_risk as risk
from competition_fresh_search import OUT
from competition_under2d import ROOT

DEST=OUT/'timing_variants_20260930';DEST.mkdir(exist_ok=True)
NAMES=['close_to_next_open','open_to_same_close','open_to_next_close','next_open_to_next_close',
       'gap_green_open_to_same_close','minute_green_open_to_same_close','gap_green_open_to_next_close','minute_green_open_to_next_close']

def prepare():
    f=pd.read_parquet(OUT/'policy_pool.parquet');f=f[~f.calendar_same_day].copy()
    cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    opens=dict(zip(cal.index.strftime('%Y-%m-%d'),pd.to_datetime(cal['open'],utc=True)+pd.Timedelta(minutes=1)))
    closes=dict(zip(cal.index.strftime('%Y-%m-%d'),pd.to_datetime(cal['close'],utc=True)))
    f['next_open_ts']=pd.to_datetime(f.exit_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d').map(opens),utc=True)
    f['signal_close_ts']=pd.to_datetime(pd.to_datetime(f.session_date).dt.strftime('%Y-%m-%d').map(closes),utc=True)
    points=pd.concat([f[['security_id','next_open_ts']].rename(columns={'next_open_ts':'stamp'}),
                     f[['security_id','signal_close_ts']].rename(columns={'signal_close_ts':'stamp'})]).drop_duplicates()
    refs=pd.concat([points.assign(bar_start_ts_utc=points.stamp-pd.Timedelta(minutes=k)) for k in range(1,6)],ignore_index=True)
    entries=f[['security_id','entry_ts']].rename(columns={'entry_ts':'stamp'}).drop_duplicates()
    opening=entries.assign(bar_start_ts_utc=entries.stamp-pd.Timedelta(minutes=1))
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    with duckdb.connect(source,read_only=True) as c:
        c.execute("SET memory_limit='5GB'");c.execute('SET threads=4');c.execute("SET temp_directory='D:/AlgoResearch/Quant-Pipeline-V3/cache/timing_temp'")
        c.register('refs',refs)
        prices=c.execute('''SELECT p.security_id,p.stamp,b.close reference_price,b.bar_start_ts_utc reference_bar,b.availability_ts_utc
          FROM bars_1m_raw b JOIN refs p USING(security_id,bar_start_ts_utc)
          WHERE b.availability_ts_utc<=p.stamp AND b.session_date BETWEEN DATE '2025-05-01' AND DATE '2026-04-30'
          QUALIFY row_number() OVER(PARTITION BY p.security_id,p.stamp ORDER BY b.bar_start_ts_utc DESC)=1''').fetchdf()
        c.register('opening',opening)
        first=c.execute('''SELECT p.security_id,p.stamp,b.open first_minute_open,b.close first_minute_close
          FROM bars_1m_raw b JOIN opening p USING(security_id,bar_start_ts_utc)
          WHERE b.availability_ts_utc<=p.stamp AND b.session_date BETWEEN DATE '2025-05-01' AND DATE '2026-04-30' ''').fetchdf()
        c.register('points',points)
        endpoints=c.execute('''SELECT b.security_id,b.bar_start_ts_utc stamp,b.symbol,b.open,b.high,b.low,b.close
          FROM bars_1m_raw b JOIN points p ON b.security_id=p.security_id AND b.bar_start_ts_utc=p.stamp
          WHERE b.session_date BETWEEN DATE '2025-05-01' AND DATE '2026-04-30' ''').fetchdf()
    prices.to_parquet(DEST/'extra_references.parquet',index=False)
    f=f.merge(prices[['security_id','stamp','reference_price','reference_bar']].rename(columns={'stamp':'next_open_ts','reference_price':'next_open_price','reference_bar':'next_open_reference_bar'}),on=['security_id','next_open_ts'],how='left',validate='many_to_one')
    f=f.merge(prices[['security_id','stamp','reference_price']].rename(columns={'stamp':'signal_close_ts','reference_price':'signal_close_price'}),on=['security_id','signal_close_ts'],how='left',validate='many_to_one')
    f=f.merge(first.rename(columns={'stamp':'entry_ts'}),on=['security_id','entry_ts'],how='left',validate='many_to_one')
    f['gap_green']=f.first_minute_close.gt(f.signal_close_price)&f.signal_close_price.gt(0)
    f['minute_green']=f.first_minute_close.gt(f.first_minute_open)&f.first_minute_open.gt(0)
    f.to_parquet(DEST/'matched_pool.parquet',index=False)
    endpoints=pd.concat([pd.read_parquet(OUT/'policy_endpoint_bars.parquet'),endpoints],ignore_index=True).drop_duplicates(['security_id','stamp'])
    endpoints.to_parquet(DEST/'endpoint_bars.parquet',index=False)
    build(f,endpoints)

def build(f=None,endpoints=None):
    if f is None:f=pd.read_parquet(DEST/'matched_pool.parquet')
    if endpoints is None:endpoints=pd.read_parquet(DEST/'endpoint_bars.parquet')
    rows=[]
    for name in NAMES:
        sub=DEST/name;sub.mkdir(exist_ok=True);g=variant(f,name)
        # Only entry reference availability can cause abstention. Never drop a filled-exit liability.
        missing=int((~g.entry_price.gt(0)).sum());g=g[g.entry_price.gt(0)].copy()
        g.to_parquet(sub/'policy_pool.parquet',index=False);endpoints.to_parquet(sub/'policy_endpoint_bars.parquet',index=False)
        (sub/'scope.json').write_text(json.dumps({'matched_original_closing_pool':len(f),'eligible_intentions':len(g),'unavailable_entry_references':missing,
          'missing_first_minute_exit_reference_fallback_count':int(g.get('exit_reference_fallback',pd.Series(False,index=g.index)).sum()),
          'exit_reference_fallback':'When the opening reference is unavailable, retain the known previous closing entry reference. Quote exits/forced liquidation remain liabilities, never hindsight exclusions.',
          'green_conditions_known_before_entry':True,'activation_entry_seconds':5,'activation_exit_seconds':1,'selection_delay_seconds':4,
          'limit_expiry_seconds':54,'force_seconds':56,'opening_clock':'09:31 after first completed minute','fees':0,'out_of_sample_accessed':False},indent=2))
        rows.append({'variant':name,'eligible':len(g),'unavailable_entry':missing})
    pd.DataFrame(rows).to_parquet(DEST/'scope.parquet',index=False)
    decomposition(f)
    print(pd.DataFrame(rows).to_string(index=False),flush=True)

def variant(f,name):
    g=f.copy()
    if 'gap_green' in name:g=g[g.gap_green].copy()
    if 'minute_green' in name:g=g[g.minute_green].copy()
    if name=='close_to_next_open':
        g['entry_ts']=g.first_session_exit_ts;g['entry_price']=g.first_session_exit_price
        g['exit_ts']=g.next_open_ts;g['exit_reference_fallback']=~g.next_open_price.gt(0)
        g['exit_price']=g.next_open_price.where(g.next_open_price.gt(0),g.first_session_exit_price)
    elif name=='next_open_to_next_close':g['entry_ts']=g.next_open_ts;g['entry_price']=g.next_open_price
    elif name.endswith('same_close'):g['exit_ts']=g.first_session_exit_ts;g['exit_price']=g.first_session_exit_price
    g['candidate_id']=name;g['target_id']='timing_ablation_'+name
    assert ((g.exit_ts-g.entry_ts)<pd.Timedelta(days=2)).all() and (g.entry_ts>g.decision_ts).all()
    return g.drop(columns=['entry_reference_bar','exit_reference_bar'],errors='ignore')

def decomposition(f):
    w=pd.read_parquet(OUT/'close_entry_comparison/working_trades.parquet')
    w=w.merge(f[['observation_id','next_open_price']],on='observation_id',how='left',validate='one_to_one')
    w['overnight_bps']=(w.next_open_price/w.entry_price-1)*1e4
    w['next_session_bps']=(w.exit_price/w.next_open_price-1)*1e4
    print('Decomposition reference coverage',int(w.next_open_price.gt(0).sum()),'/',len(w),flush=True)
    w.to_parquet(DEST/'original_fills_path_decomposition.parquet',index=False)
    print('Original filled-name reference path: overnight',w.overnight_bps.mean(),'bp; next day',w.next_session_bps.mean(),'bp. Not separate executable portfolios.',flush=True)

def replay(name):
    sub=DEST/name;engine.OUT=sub;engine.Q=OUT/'policy_quotes'
    engine.ACTIVATION_SECONDS=5;engine.EXIT_ACTIVATION_SECONDS=1;engine.SELECTION_DELAY_SECONDS=4;engine.EXIT_LIMIT_TTL_SECONDS=54;engine.FORCE_SECONDS=56
    # Pace only new HTTP pages; cached symbols/windows cost no requests.
    orig=engine.transport.urlopen;lock=threading.Lock();last=[0.]
    def paced(*a,**kw):
        with lock:
            wait=max(0.,last[0]+.4-time.monotonic())
            if wait:time.sleep(wait)
            last[0]=time.monotonic()
        return orig(*a,**kw)
    engine.transport.urlopen=paced
    print('RUNNING',name,flush=True)
    with (sub/'replay.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        engine.run();finish(name)
    z=pd.read_parquet(sub/'policy_risk_summary.parquet')
    print(name,z.loc[z.bps.isin([0,1,5]),['bps','fills','cash_funded_return_pct','minute_mark_relative_drawdown_pct','green_months']].to_string(index=False),flush=True)

def finish(name):
    sub=DEST/name;engine.OUT=sub;engine.SELECTION_DELAY_SECONDS=4
    pool=pd.read_parquet(sub/'policy_quote_pool.parquet');d=pd.read_parquet(sub/'policy_quote_outcomes.parquet')
    for c in ['entry_fill_ts','exit_fill_ts']:d[c]=pd.to_datetime(d[c],utc=True).dt.as_unit('ns')
    needed=pool[pool.order_id.isin(d.loc[~d.priced&d.entry_filled,'order_id'])]
    if len(needed):
        orig=engine.transport.urlopen;gate=threading.Lock();last=[0.]
        def paced(*a,**kw):
            with gate:
                wait=max(0.,last[0]+.4-time.monotonic())
                if wait:time.sleep(wait)
                last[0]=time.monotonic()
            return orig(*a,**kw)
        engine.transport.urlopen=paced
        oldq=engine.Q;engine.Q=DEST/'forced_quotes';engine.Q.mkdir(exist_ok=True)
        engine.HEADERS=engine.transport.api_headers();engine.transport.WINDOW_SECONDS=128
        items=[(pd.Timestamp(t)+pd.Timedelta(seconds=54),sorted(h.symbol.unique())) for t,h in needed.groupby('exit_ts')]
        q=engine.download(items,'liquidation_recovery');q=q[(q.bid_price>0)&(q.ask_price>=q.bid_price)&(q.bid_size>0)&(q.ask_size>0)].sort_values('quote_ts')
        books={(t,s):h for (t,s),h in q.groupby(['window_ts','symbol'])}
        cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
        closes=dict(zip(cal.index.strftime('%Y-%m-%d'),pd.to_datetime(cal['close'],utc=True)))
        for r in needed.itertuples():
            b=books.get((r.exit_ts+pd.Timedelta(seconds=54),r.symbol))
            if b is None:continue
            force=r.exit_ts+pd.Timedelta(seconds=56);close=closes[r.exit_ts.tz_convert('America/New_York').strftime('%Y-%m-%d')]
            b=b[(b.quote_ts<close)&(b.quote_ts<=r.exit_ts+pd.Timedelta(seconds=180))]
            before=b[b.quote_ts<=force].tail(1)
            if len(before) and (force-before.quote_ts.iloc[0]).total_seconds()<=2:
                b=before.copy();b['quote_ts']=force
            else:b=b[b.quote_ts>force].head(1)
            if not len(b):continue
            mask=(d.order_id==r.order_id)&~d.priced&d.entry_filled
            limit=r.exit_price*(1-d.loc[mask,'bps']/1e4)
            d.loc[mask,'executed_exit_price']=limit.clip(upper=float(b.bid_price.iloc[0])).fillna(float(b.bid_price.iloc[0]))
            d.loc[mask,'exit_fill_ts']=b.quote_ts.iloc[0];d.loc[mask,'return']=d.loc[mask,'executed_exit_price']/d.loc[mask,'executed_entry_price']-1;d.loc[mask,'priced']=True
        engine.Q=oldq;d.to_parquet(sub/'policy_quote_outcomes.parquet',index=False)
        scope=json.loads((sub/'scope.json').read_text());scope['forced_liquidation_recovery']='Force at second 56, fresh bid age<=2sec or first valid later quote within 180sec of planned minute, strictly before close. Unresolved liabilities retained.'
        scope['unpriced_liabilities']=int((~d.priced).sum());(sub/'scope.json').write_text(json.dumps(scope,indent=2))
    engine.allocate(pool,d)
    attempts=pd.read_parquet(sub/'policy_quote_attempts.parquet');attempts=attempts[(attempts.slots==10)&attempts.ranked]
    attempts.to_parquet(sub/'policy_quote_attempts.parquet',index=False)
    risk.OUT=sub;risk.PATH_FILE=OUT/'policy_minute_paths.parquet';risk.analyze()

def screen():
    rows=[]
    for name in NAMES:
        sub=DEST/name;pool=pd.read_parquet(sub/'policy_pool.parquet').reset_index(drop=True);pool['order_id']=np.arange(len(pool));records=[]
        for bps in engine.LEVELS:
            records.append(pd.DataFrame({'order_id':pool.order_id,'bps':bps,'entry_filled':True,'limit_exit':True,'forced_exit':False,'priced':pool.exit_price.gt(0),
              'entry_fill_ts':pool.entry_ts+pd.Timedelta(seconds=5),'exit_fill_ts':pool.exit_ts+pd.Timedelta(seconds=1),
              'executed_entry_price':pool.entry_price*(1+bps/1e4),'executed_exit_price':pool.exit_price*(1-bps/1e4),
              'return':pool.exit_price*(1-bps/1e4)/(pool.entry_price*(1+bps/1e4))-1}))
        engine.OUT=sub;engine.SELECTION_DELAY_SECONDS=4
        with contextlib.redirect_stdout(io.StringIO()):engine.allocate(pool,pd.concat(records,ignore_index=True))
        (sub/'policy_quote_summary.parquet').replace(sub/'stage_a_summary.parquet')
        (sub/'policy_quote_attempts.parquet').replace(sub/'stage_a_attempts.parquet')
        d=pd.read_parquet(sub/'stage_a_attempts.parquet');d=d[(d.slots==10)&d.ranked].rename(columns={'return':'return_value'})
        for bps,g in d.groupby('bps'):
            ending=risk.funded(g,10,0)[1] if g.priced.all() else np.nan
            rows.append({'variant':name,'bps':bps,'nominations':len(g),'unpriced_endpoints':int((~g.priced).sum()),'mean_trade_bps':g.return_value.mean()*1e4,'cash_funded_return_pct':(ending-1)*100})
    f=pd.DataFrame(rows);f.to_parquet(DEST/'stage_a_comparison.parquet',index=False)
    print(f[f.bps.isin([0,1,5])].to_string(index=False),flush=True)

def report():
    frames=[]
    for name in ['current_close_to_next_close']+NAMES:
        sub=OUT/'close_entry_comparison' if name=='current_close_to_next_close' else DEST/name
        p=sub/'policy_risk_summary.parquet'
        if not p.exists():continue
        g=pd.read_parquet(p);g=g[(g.slots==10)&g.ranked].copy();g['variant']=name;frames.append(g)
    f=pd.concat(frames,ignore_index=True);f.to_parquet(DEST/'comparison.parquet',index=False)
    print(f.loc[f.bps.isin([0,1,5]),['variant','bps','fills','cash_funded_return_pct','minute_mark_relative_drawdown_pct','green_months','max_actual_hold_hours']].to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','build','screen','replay','finish','report']);p.add_argument('--variant',choices=NAMES);a=p.parse_args()
    if a.stage in ['replay','finish']:globals()[a.stage](a.variant)
    else:globals()[a.stage]()
