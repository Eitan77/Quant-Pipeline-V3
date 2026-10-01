"""Calendar-safe maximum two-session holds and causal capacity ranking."""
import json
import numpy as np,pandas as pd,duckdb,exchange_calendars as xc
from competition_under2d import ROOT,EvidenceReader,decode_packed_bins,portfolio_stats
from competition_fresh_search import OUT

def allocate(f,slots,ranked):
    w=f.copy();w['tie']=pd.util.hash_pandas_object(w.security_id.astype(str)+w.session_date.astype(str)+'0',index=False).to_numpy()
    keys=['entry_ts']+(['rank_score'] if ranked else [])+['tie','observation_id'];ascending=[True]+([False] if ranked else [])+[True,True]
    w=w.sort_values(keys,ascending=ascending,kind='stable');free=np.full(slots,-1,dtype=np.int64);active={};keep=[]
    en=w.entry_ts.to_numpy(dtype='datetime64[ns]').astype('int64');ex=w.exit_ts.to_numpy(dtype='datetime64[ns]').astype('int64')+60_000_000_000
    for j,(sid,e,x) in enumerate(zip(w.security_id,en,ex)):
        if active.get(sid,-1)>e:continue
        slot=free.argmin()
        if free[slot]>e:continue
        keep.append(j);free[slot]=x;active[sid]=x
    return w.iloc[keep].drop(columns='tie')

def run():
    r=EvidenceReader(ROOT,'evidence/reader.json','daily_close');fa='ema_distance__20d__raw__daily_close';fb='return_skip_recent_63d_ex_5d__63d__raw__daily_close'
    ac=r.read_columns('bins',[fa],0,r.rows)[:,0];bc=r.read_columns('bins',[fb],0,r.rows)[:,0]
    mask=(decode_packed_bins(ac,5)==0)&(decode_packed_bins(bc,5)==4)
    obs=pd.read_parquet(ROOT/r.grid['observations'],columns=['observation_id','security_id','session_date','decision_ts'])
    f=obs.loc[mask].copy();f['direction']=1;f['candidate_id']='signal_only_trend_dislocation'
    cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-05-05').schedule;close_col='close' if 'close' in cal else 'market_close'
    closes=pd.to_datetime(cal[close_col],utc=True);dates=pd.Index(cal.index.strftime('%Y-%m-%d'))
    opens=pd.to_datetime(cal['open' if 'open' in cal else 'market_open'],utc=True)
    next_open=dict(zip(dates[:-1],opens.iloc[1:]));next_close=dict(zip(dates[:-1],closes.iloc[1:]));next2_close=dict(zip(dates[:-2],closes.iloc[2:]))
    decision_dates=pd.to_datetime(f.session_date).dt.strftime('%Y-%m-%d')
    f['entry_ts']=pd.to_datetime(decision_dates.map(next_open),utc=True)+pd.Timedelta(minutes=1)
    f['first_session_exit_ts']=pd.to_datetime(decision_dates.map(next_close),utc=True)-pd.Timedelta(minutes=1)
    second=pd.to_datetime(decision_dates.map(next2_close),utc=True)-pd.Timedelta(minutes=1)
    end=pd.Timestamp('2026-05-01',tz='America/New_York')
    carry=((second-f.entry_ts)<pd.Timedelta(days=2))&(second<end)
    f['calendar_same_day']=~carry;f['exit_ts']=second.where(carry,f.first_session_exit_ts)
    f=f[f.entry_ts<end].copy()
    f['target_id']='policy_max48h__raw__daily_close'
    aa=decode_packed_bins(ac,10);bb=decode_packed_bins(bc,10)
    f['rank_score']=bb[f.observation_id.to_numpy()]-aa[f.observation_id.to_numpy()]
    points=pd.concat([f[['security_id','entry_ts']].rename(columns={'entry_ts':'stamp'}),f[['security_id','exit_ts']].rename(columns={'exit_ts':'stamp'}),f[['security_id','first_session_exit_ts']].rename(columns={'first_session_exit_ts':'stamp'})]).drop_duplicates()
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    with duckdb.connect(source,read_only=True) as c:
        c.execute("SET memory_limit='5GB'");c.execute('SET threads=4');c.register('points',points)
        bars=c.execute('''SELECT b.security_id,b.bar_start_ts_utc stamp,b.symbol,b.high,b.low,b.open,b.close
            FROM bars_1m_raw b JOIN points p ON b.security_id=p.security_id AND b.bar_start_ts_utc=p.stamp''').fetchdf()
        refs=pd.concat([points.assign(bar_start_ts_utc=points.stamp-pd.Timedelta(minutes=k)) for k in range(1,6)],ignore_index=True);c.register('refs',refs)
        prices=c.execute('''SELECT p.security_id,p.stamp,b.close reference_price,b.symbol,b.bar_start_ts_utc reference_bar_start
            FROM bars_1m_raw b JOIN refs p USING(security_id,bar_start_ts_utc) WHERE b.availability_ts_utc<=p.stamp
            QUALIFY row_number() OVER(PARTITION BY p.security_id,p.stamp ORDER BY b.bar_start_ts_utc DESC)=1''').fetchdf()
        c.register('signals',f)
        actions=c.execute('''SELECT s.observation_id,a.* FROM signals s JOIN corporate_actions a USING(security_id)
            WHERE a.session_date>CAST(s.entry_ts AT TIME ZONE 'America/New_York' AS DATE)
            AND a.session_date<=CAST(s.exit_ts AT TIME ZONE 'America/New_York' AS DATE)''').fetchdf()
    actions.to_parquet(OUT/'policy_holding_actions.parquet',index=False)
    assert not (actions.split_factor.fillna(1)!=1).any(),'Split accounting required before performance claim'
    bars.to_parquet(OUT/'policy_endpoint_bars.parquet',index=False)
    f=f.merge(prices.rename(columns={'stamp':'entry_ts','reference_price':'entry_price','reference_bar_start':'entry_reference_bar'}),on=['security_id','entry_ts'],how='left',validate='many_to_one')
    f=f.merge(prices.drop(columns='symbol').rename(columns={'stamp':'exit_ts','reference_price':'exit_price','reference_bar_start':'exit_reference_bar'}),on=['security_id','exit_ts'],how='left',validate='many_to_one')
    f=f.merge(prices[['security_id','stamp','reference_price']].rename(columns={'stamp':'first_session_exit_ts','reference_price':'first_session_exit_price'}),on=['security_id','first_session_exit_ts'],how='left',validate='many_to_one')
    f.to_parquet(OUT/'policy_pool_pricing.parquet',index=False)
    missing_entry=~f.entry_price.gt(0)
    (OUT/'policy_reference_integrity.json').write_text(json.dumps({'input_signals':len(f),'no_causal_entry_reference':int(missing_entry.sum()),
        'unpriced_exit_liabilities':int((~missing_entry&~f.exit_price.gt(0)).sum())},indent=2))
    f=f[~missing_entry].copy()
    assert f.exit_price.gt(0).all(),'Unpriced exit liabilities: no claim'
    assert ((f.exit_ts-f.entry_ts)<pd.Timedelta(days=2)).all()
    f.to_parquet(OUT/'policy_pool.parquet',index=False);ledgers=[];rows=[]
    for slots in [1,3,10]:
        for ranked in [False,True]:
            g=allocate(f,slots,ranked);g['candidate_id']='max48h_ranked' if ranked else 'max48h_hash';g['slots']=slots;ledgers.append(g)
            for bps in [-1,0,1,2,3,4,5]:rows.append({'candidate_id':g.candidate_id.iloc[0],'slots':slots,'bps':bps,**portfolio_stats(g,bps,slots)})
    result=pd.DataFrame(rows);result['monthly_pct']=result.monthly_pct.map(json.dumps);result.to_parquet(OUT/'policy_capacity_sensitivity.parquet',index=False)
    pd.concat(ledgers).to_parquet(OUT/'policy_capacity_trades.parquet',index=False)
    (OUT/'policy_scope.json').write_text(json.dumps({'signal':'Bottom quintile 20d EMA distance AND top quintile older 63d momentum excluding latest 5d.',
        'holding':'Next-session entry to following-session close if elapsed hold below 48h; otherwise close entry session.',
        'ranking':'Prefer lower EMA-distance and higher older-momentum fine bins; no outcome ranking.',
        'signal_only_eligibility':True,'future_target_or_action_gates':False,'cash_dividend_income':'Ignored conservatively, no fee credit.',
        'slots':[1,3,10],'calendar_fallback_not_a_price_filter':True,'out_of_sample_accessed':False},indent=2))
    print(result[result.bps==5][['candidate_id','slots','trades','mean_trade_bps','additive_pct','max_dd_pct','positive_months','days','symbols','ex_top5_mean_bps']].to_string(index=False),flush=True)
    print('POOL',len(f),'calendar same-day',int(f.calendar_same_day.sum()),'entry sessions',f.entry_ts.dt.date.nunique(),flush=True)

if __name__=='__main__':run()
