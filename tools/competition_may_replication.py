"""Frozen original ten-slot policy; explicitly authorized May 2026 only."""
import argparse,csv,hashlib,json,time
from pathlib import Path
import duckdb,numpy as np,pandas as pd,exchange_calendars as xc
from competition_under2d import ROOT,EvidenceReader,decode_packed_bins
from competition_fresh_search import OUT as DISC

OUT=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_oos_top10_may2026_20260930')
REF=Path('reference')
LAKE=Path('D:/AlgoResearch/data/raw/alpaca')
A='ema_distance__20d__raw__daily_close'
B='return_skip_recent_63d_ex_5d__63d__raw__daily_close'
CAL=xc.get_calendar('XNYS',start='2026-04-30',end='2026-05-31').schedule

def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2,default=str),encoding='utf-8')

def guard():
    assert (OUT/'replication/fresh_close_carry_trend_dislocation_20260930.request.json').exists()
    assert (OUT/'FROZEN_STRATEGY.json').read_bytes()==(DISC/'close_entry_comparison/FROZEN_STRATEGY.json').read_bytes()
    auth=json.loads((OUT/'authorizations/fresh_close_carry_trend_dislocation_20260930.json').read_text())
    print('AUTHORIZATION',auth,flush=True)

def features(frame):
    frame=frame.sort_values(['security_id','decision_ts']).reset_index(drop=True)
    # Security lifecycle workers use float64 source closes.
    p=frame.close.astype(float)
    groups=frame.security_id
    ema=p.groupby(groups,sort=False).transform(lambda s:s.ewm(span=20,adjust=False,min_periods=2).mean())
    frame['A']=(p/ema-1).astype('float32')
    frame['B']=(p.groupby(groups).shift(5)/p.groupby(groups).shift(63)-1).astype('float32')
    for label in ['A','B']:
        ranks=frame[label].groupby(frame.decision_ts).rank(method='average',pct=True).astype('float32')
        for r in [5,10]:frame[label+str(r)]=np.where(ranks.notna(),np.minimum((ranks.fillna(0)*r).astype(int),r-1),-1).astype('int16')
    return frame

def history():
    return pd.read_parquet(ROOT/'cache/calculation_panels/daily_close.parquet',columns=['security_id','symbol','session_date','decision_ts','close','emit','observation_id','in_universe'])

def precheck():
    guard()
    h=features(history());r=EvidenceReader(ROOT,'evidence/reader.json','daily_close')
    z=h[h.emit].sort_values('observation_id')
    checks={}
    for label,fid in [('A',A),('B',B)]:
        original=r.read_columns('bins',[fid],0,r.rows)[:,0]
        for resolution in [5,10]:
            mismatches=int((z[label+str(resolution)].to_numpy()!=decode_packed_bins(original,resolution)).sum())
            checks[label+str(resolution)]=mismatches
    save('feature_parity.json',checks);print('PARITY',checks,flush=True)
    assert not any(checks.values()),'Feature reconstruction does not match discovery'
    snapshots=[]
    src=Path('C:/Users/decla/Desktop/AlgoResearch/Quant Pipeline V2/reference/membership_source/fja_updated.csv')
    with src.open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            day=pd.Timestamp(row['date']).normalize()
            if day>pd.Timestamp('2026-05-31'):break
            symbols=sorted({s.strip().upper().replace('-','.') for s in row['tickers'].split(',') if s.strip()})
            if snapshots and day==snapshots[-1][0]:snapshots[-1]=(day,symbols)
            else:snapshots.append((day,symbols))
    rows=[]
    for day in CAL.index:
        if day<pd.Timestamp('2026-05-01'):continue
        sdate,symbols=next(x for x in reversed(snapshots) if x[0]<=day)
        rows.extend({'session_date':day,'symbol':s,'source_snapshot_date':sdate,'in_universe':True} for s in symbols)
    m=pd.DataFrame(rows);m.to_parquet(OUT/'membership.parquet',index=False)
    sm=pd.read_parquet(REF/'security_master.parquet');missing=sorted(set(m.symbol)-set(sm.symbol))
    print('MEMBERSHIP',len(m),m.source_snapshot_date.unique(),'missing identities',missing,flush=True)
    save('membership_lineage.json',{'source':str(src),'cutoff':'2026-05-31','last_in_scope_snapshot':snapshots[-1][0],'membership_quality':'open_historical_reconstruction_provisional','new_symbols':missing})
    with duckdb.connect() as c:
        for path in [LAKE/'corporate_actions/process_year=2026/*.parquet',LAKE/'market/stocks/bars_1m/feed=sip/year=2026/month=05/**/*.parquet']:
            print('SCHEMA',str(path),c.execute('DESCRIBE SELECT * FROM read_parquet(?,union_by_name=true,hive_partitioning=true)',[str(path)]).fetchall(),flush=True)

def audit():
    """Bounded discovery-only audit of EMA/date alignment; no OOS prices."""
    h=history().sort_values(['security_id','decision_ts']).reset_index(drop=True)
    calculated=features(h);emitted=calculated[calculated.emit].sort_values('observation_id')
    reader=EvidenceReader(ROOT,'evidence/reader.json','daily_close')
    stored=np.load(ROOT/'cache/features/daily_close/moving_average__local__000.npy',mmap_mode='r')[:,2]
    rows=[]
    for sid,g in h.groupby('security_id',sort=False):
        ema=g.close.ewm(span=20,adjust=False,min_periods=2).mean().to_numpy()
        valid=np.flatnonzero(np.isfinite(ema));order=valid[np.argsort(ema[valid])];ordered=ema[order]
        z=g[g.emit];ids=z.observation_id.to_numpy(dtype=int);v=stored[ids]
        implied=z.close.to_numpy()/(1+v.astype(float));ix=np.searchsorted(ordered,implied)
        lo=np.maximum(0,ix-1);hi=np.minimum(len(order)-1,ix)
        best=np.where(abs(ordered[lo]-implied)<abs(ordered[hi]-implied),lo,hi)
        selected=order[best];error=abs(ema[selected]-implied)/implied
        dependency=g.session_date.iloc[selected].to_numpy()
        for oid,day,value,dep,err in zip(ids,z.session_date,v,dependency,error):
            rows.append({'observation_id':int(oid),'security_id':sid,'session_date':day,'stored_A':float(value),'inferred_ema_date':dep,'relative_match_error':float(err),'future_dependency':bool(np.isfinite(err) and err<1e-6 and dep>day)})
    deps=pd.DataFrame(rows);deps.to_parquet(OUT/'discovery_ema_alignment_audit.parquet',index=False)
    trades=pd.read_parquet(DISC/'close_entry_comparison/working_trades.parquet')
    print('TRADES',list(trades.columns),len(trades),flush=True)
    audited=trades.merge(deps,on='observation_id',suffixes=('','_audit'),validate='many_to_one')
    audited.to_parquet(OUT/'discovery_filled_alignment_audit.parquet',index=False)
    checks={}
    for label,fid in [('A',A),('B',B)]:
        original=reader.read_columns('bins',[fid],0,reader.rows)[:,0]
        for resolution in [5,10]:checks[label+str(resolution)]=int((emitted[label+str(resolution)].to_numpy()!=decode_packed_bins(original,resolution)).sum())
    membership=(emitted.A5==0)&(emitted.B5==4)
    originalA=decode_packed_bins(reader.read_columns('bins',[A],0,reader.rows)[:,0],5)
    originalB=decode_packed_bins(reader.read_columns('bins',[B],0,reader.rows)[:,0],5)
    summary={'discovery_observations':len(deps),'bin_mismatches':checks,'correct_rule_signals':int(membership.sum()),'original_rule_signals':int(((originalA==0)&(originalB==4)).sum()),'state_membership_disagreements':int((membership.to_numpy()!=((originalA==0)&(originalB==4))).sum()),'stored_values_matching_another_date_ema':int(deps.relative_match_error.lt(1e-6).sum()),'stored_values_using_future_ema':int(deps.future_dependency.sum()),'working_trades':len(audited),'working_trades_using_future_ema':int(audited.future_dependency.sum()),'may_price_data_accessed':False,'cause':'FeatureBuilder sorts by decision timestamp but retains original row index; ema.reset_index(level=0,drop=True) discards that index and Series arithmetic aligns the EMA to different rows.'}
    save('DISCOVERY_ALIGNMENT_FAILURE.json',summary);print('ALIGNMENT',json.dumps(summary),flush=True)
    print('EXAMPLES',audited[audited.future_dependency][['symbol','session_date','inferred_ema_date','relative_match_error']].head(5).to_dict('records'),flush=True)

def corrected_bars():
    """Same stated policy on corrected discovery signals; bar diagnostic only."""
    from competition_slot_comparison import select
    from competition_fresh_risk import funded
    dest=OUT/'corrected_discovery';dest.mkdir(exist_ok=True)
    h=features(history());f=h[h.emit&h.in_universe&(h.A5==0)&(h.B5==4)].copy()
    cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-05-05').schedule
    dates=pd.Index(cal.index.strftime('%Y-%m-%d'));opens=pd.to_datetime(cal['open'],utc=True);closes=pd.to_datetime(cal['close'],utc=True)
    nextopen=dict(zip(dates[:-1],opens.iloc[1:]+pd.Timedelta(minutes=1)))
    nextclose=dict(zip(dates[:-1],closes.iloc[1:]-pd.Timedelta(minutes=1)))
    next2close=dict(zip(dates[:-2],closes.iloc[2:]-pd.Timedelta(minutes=1)))
    sdate=pd.to_datetime(f.session_date).dt.strftime('%Y-%m-%d')
    f['original_open_ts']=pd.to_datetime(sdate.map(nextopen),utc=True)
    f['entry_ts']=pd.to_datetime(sdate.map(nextclose),utc=True)
    f['exit_ts']=pd.to_datetime(sdate.map(next2close),utc=True)
    f=f[((f.exit_ts-f.original_open_ts)<pd.Timedelta(days=2))&(f.exit_ts<pd.Timestamp('2026-05-01',tz='America/New_York'))].copy()
    f['rank_score']=f.B10-f.A10
    f['session_date']=pd.to_datetime(f.session_date)
    pts=pd.concat([f[['security_id',col]].rename(columns={col:'stamp'}) for col in ['original_open_ts','entry_ts','exit_ts']]).drop_duplicates()
    requested=pd.concat([pts.assign(bar_start_ts_utc=pts.stamp-pd.Timedelta(minutes=k)) for k in range(1,6)],ignore_index=True)
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    print('CORRECTED_DISCOVERY_REFERENCE_QUERY',len(f),'signals',len(requested),'exact keys',flush=True)
    with duckdb.connect(source,read_only=True) as c:
        c.execute("SET memory_limit='5GB'");c.execute('SET threads=4');c.register('refs',requested)
        refs=c.execute('''SELECT p.security_id,p.stamp,b.close reference_price,b.bar_start_ts_utc reference_bar_start
             FROM bars_1m_raw b JOIN refs p USING(security_id,bar_start_ts_utc) WHERE b.availability_ts_utc<=p.stamp
             QUALIFY row_number() OVER(PARTITION BY p.security_id,p.stamp ORDER BY b.bar_start_ts_utc DESC)=1''').fetchdf()
    refs.to_parquet(dest/'causal_references.parquet',index=False)
    for column,label in [('original_open_ts','original_open_price'),('entry_ts','entry_price'),('exit_ts','exit_price')]:
        f=f.merge(refs[['security_id','stamp','reference_price']].rename(columns={'stamp':column,'reference_price':label}),on=['security_id',column],how='left',validate='many_to_one')
    missing=f[~f.original_open_price.gt(0)|~f.entry_price.gt(0)]
    f=f[f.original_open_price.gt(0)&f.entry_price.gt(0)].copy();assert f.exit_price.gt(0).all()
    f=f.reset_index(drop=True);f['order_id']=np.arange(len(f));f.to_parquet(dest/'policy_pool.parquet',index=False)
    results=[]
    for bps in [-1,0,1,2,3,4,5]:
        detail=pd.DataFrame({'order_id':f.order_id,'bps':bps,'entry_filled':True,'priced':True,
          'entry_fill_ts':pd.to_datetime(f.entry_ts,utc=True).dt.as_unit('ns')+pd.Timedelta(seconds=5),
          'exit_fill_ts':pd.to_datetime(f.exit_ts,utc=True).dt.as_unit('ns')+pd.Timedelta(seconds=1),
          'return':f.exit_price*(1-bps/1e4)/(f.entry_price*(1+bps/1e4))-1})
        g=select(f,detail,10,4).rename(columns={'return':'return_value'});_,cash,_=funded(g,10,0)
        g.to_parquet(dest/f'bar_assumed_attempts_{bps}.parquet',index=False)
        results.append({'bps':bps,'trades':len(g),'cash_funded_bar_assumed_pct':(cash-1)*100,'mean_trade_bps':g.return_value.mean()*1e4})
    summary={'status':'bar_assumptions_only_not_quote_validated','pool':len(f),'known_reference_skips':len(missing),'results':results,'may_prices_accessed':False}
    save('corrected_discovery_bar_diagnostic.json',summary);print('CORRECTED',json.dumps(summary),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['precheck','audit','corrected_bars']);args=p.parse_args();globals()[args.stage]()
