"""Exact seven-price attainability checks; fetch only touched endpoint bars."""
import json,time
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np,pandas as pd
import fresh_overnight_quote_replay as transport
from competition_full_year import OUT
from competition_under2d import portfolio_stats

LEVELS=[-1,0,1,2,3,4,5]
CORE=['positive_return_ma_tail','positive_return_ma_low20']
QOUT=OUT/'quote_replay';QOUT.mkdir(exist_ok=True)

def download():
    f=pd.read_parquet(OUT/'trades_daily_close.parquet');f=f[f.candidate_id.isin(CORE)].copy()
    bars=pd.read_parquet(OUT/'endpoint_bars_daily_close.parquet')
    windows=[]
    for leg in ['entry','exit']:
        e=f[['security_id',f'{leg}_ts',f'{leg}_price']].rename(columns={f'{leg}_ts':'stamp',f'{leg}_price':'reference'}).drop_duplicates()
        e=e.merge(bars,on=['security_id','stamp'],how='left',validate='many_to_one')
        # BUY reach/improve a limit: low <= limit; SELL: high >= limit.
        touched=e.low.le(e.reference*1.0005) if leg=='entry' else e.high.ge(e.reference*.9995)
        for stamp,g in e[touched].groupby('stamp',sort=True):
            windows.append((pd.Timestamp(stamp),sorted(g.symbol.unique())))
    merged={}
    for ts,symbols in windows:merged.setdefault(ts,set()).update(symbols)
    quote_dir=QOUT/'windows';quote_dir.mkdir(exist_ok=True)
    headers=transport.api_headers();transport.WINDOW_SECONDS=59
    def fetch(item):
        ts,symbols=item;path=quote_dir/(ts.tz_convert('UTC').strftime('%Y%m%dT%H%M%SZ')+'.parquet')
        if path.exists():q=pd.read_parquet(path)
        else:
            q=transport.fetch_window(ts+pd.Timedelta(seconds=1),sorted(symbols),headers)
            q.to_parquet(path,index=False)
        return {'stamp':ts.isoformat(),'symbols':len(symbols),'quote_rows':len(q),'path':str(path)}
    rows=[];errors=[];t0=time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending={pool.submit(fetch,item):item[0] for item in sorted(merged.items())}
        for done in as_completed(pending):
            try:rows.append(done.result())
            except Exception as exc:errors.append({'stamp':pending[done].isoformat(),'error_type':type(exc).__name__})
            if (len(rows)+len(errors))%30==0:
                print('TOUCHED QUOTE WINDOWS',len(rows)+len(errors),'/',len(merged),'errors',len(errors),'seconds',round(time.time()-t0),flush=True)
    (QOUT/'download.json').write_text(json.dumps({'windows':rows,'errors':errors,'requested_windows':len(merged),'fetched_rows':sum(x['quote_rows'] for x in rows),'bar_touch_filter':True,'latency_seconds':1,'order_ttl_seconds':59},indent=2))
    if errors:print('QUOTE ERRORS',len(errors),flush=True)

def replay():
    trades=pd.read_parquet(OUT/'capacity_trades.parquet');trades=trades[trades.candidate_id.isin(CORE)].copy()
    refs={};manifest=json.loads((QOUT/'download.json').read_text())
    for item in manifest['windows']:
        q=pd.read_parquet(item['path'])
        q=q[(q.bid_price>0)&(q.ask_price>=q.bid_price)&(q.bid_size>0)&(q.ask_size>0)].sort_values('quote_ts')
        for symbol,part in q.groupby('symbol',sort=False):refs[(pd.Timestamp(item['stamp']),symbol)]=part
    detail=[]
    for row in trades.itertuples():
        eq=refs.get((row.entry_ts,row.symbol));xq=refs.get((row.exit_ts,row.symbol))
        for bps in LEVELS:
            ep=row.entry_price*(1+bps/10000);xp=row.exit_price*(1-bps/10000)
            e=eq[eq.ask_price<=ep] if eq is not None else None
            filled=e is not None and len(e)>0
            x=xq[xq.bid_price>=xp] if xq is not None else None
            attained=filled and x is not None and len(x)>0
            status='unfilled_entry';ret=0.;real_exit=np.nan
            if filled:
                if attained:status='limit_exit';real_exit=xp
                elif xq is not None and len(xq):status='forced_exit_last_bid';real_exit=float(xq.iloc[-1].bid_price)
                else:status='missing_exit_quotes';ret=np.nan
                if np.isfinite(real_exit):ret=real_exit/ep-1
            detail.append({'candidate_id':row.candidate_id,'slots':row.slots,'observation_id':row.observation_id,'symbol':row.symbol,
                'session_date':row.session_date,'entry_ts':row.entry_ts,'exit_ts':row.exit_ts,'bps':bps,
                'entry_reference':row.entry_price,'exit_reference':row.exit_price,'entry_limit':ep,'exit_limit':xp,
                'entry_covered':eq is not None,'exit_covered':xq is not None,'entry_attainable':filled,'exit_attainable':attained,
                'completed':attained,'exit_status':status,'actual_exit_price':real_exit,'strategy_return':ret,
                'entry_first_attainable_ts':e.iloc[0].quote_ts if filled else pd.NaT,
                'exit_first_attainable_ts':x.iloc[0].quote_ts if attained else pd.NaT})
    d=pd.DataFrame(detail);d.to_parquet(QOUT/'attainability_trades.parquet',index=False)
    summary=[]
    for (cid,slots,bps),g in d.groupby(['candidate_id','slots','bps']):
        en=int(g.entry_attainable.sum());closed=int(g.completed.sum());filled=g[g.entry_attainable];completed=g[g.completed]
        daily=g.groupby(pd.to_datetime(g.exit_ts,utc=True).dt.tz_convert('America/New_York').dt.date).strategy_return.sum(min_count=1)/slots
        curve=daily.cumsum().to_numpy();dd=np.maximum.accumulate(np.r_[0.,curve])[1:]-curve
        monthly=daily.groupby(pd.to_datetime(daily.index).strftime('%Y-%m')).sum()
        valid=not g.exit_status.eq('missing_exit_quotes').any()
        summary.append({'candidate_id':cid,'slots':int(slots),'bps':int(bps),'attempted_entries':len(g),'attainable_entries':en,
            'attempted_exits':en,'attainable_exits':closed,'completed_trades':closed,'forced_exits':int(g.exit_status.eq('forced_exit_last_bid').sum()),
            'missing_exit_quotes':int(g.exit_status.eq('missing_exit_quotes').sum()),'entry_attainment_rate':en/len(g),
            'exit_attainment_rate':closed/en if en else None,'both_sides_attainment_rate':closed/len(g),
            'completed_mean_bps':float((completed.exit_limit/completed.entry_limit-1).mean()*10000),
            'completed_additive_pct':float(((completed.exit_limit/completed.entry_limit-1)/slots).sum()*100),
            'all_filled_entries_additive_pct':float(daily.sum()*100) if valid else None,
            'all_filled_entries_mean_bps':float(filled.strategy_return.mean()*10000) if valid else None,
            'close_mark_drawdown_pct':float(dd.max()*100) if valid else None,'positive_months':int((monthly>0).sum()),
            'monthly_pct':json.dumps(monthly.mul(100).to_dict()),'performance_complete':valid})
    result=pd.DataFrame(summary);result.to_parquet(QOUT/'summary.parquet',index=False)
    print(result[(result.bps==5)][['candidate_id','slots','attempted_entries','attainable_entries','completed_trades','forced_exits','missing_exit_quotes','all_filled_entries_additive_pct','close_mark_drawdown_pct','positive_months']].to_string(index=False),flush=True)

if __name__=='__main__':download();replay()
