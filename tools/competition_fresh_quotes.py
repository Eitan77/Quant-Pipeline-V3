"""Full eligible-pool SIP attainability replay; allocation precedes fill outcomes."""
import json, hashlib, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import fresh_overnight_quote_replay as transport
from competition_fresh_search import OUT

Q=OUT/'policy_quotes';Q.mkdir(exist_ok=True)
LEVELS=[-1,0,1,2,3,4,5]
RUN_ALLOCATION=True
ACTIVATION_SECONDS=1
EXIT_ACTIVATION_SECONDS=None
SELECTION_DELAY_SECONDS=0
EXIT_LIMIT_TTL_SECONDS=59
FORCE_SECONDS=59

def windows(pool,leg):
    column='entry_ts' if leg=='entry' else 'exit_ts'
    return [(pd.Timestamp(t),sorted(g.symbol.unique())) for t,g in pool.groupby(column,sort=True)]

def pull(item):
    t,symbols=item
    digest=hashlib.sha256(','.join(symbols).encode()).hexdigest()[:12]
    path=Q/f'{t.strftime("%Y%m%dT%H%M%S")}_{digest}.parquet'
    done=path.with_suffix('.json')
    if not done.exists():
        cached=[];covered=set()
        for candidate in Q.glob(f'{t.strftime("%Y%m%dT%H%M%S")}_*.json'):
            meta=json.loads(candidate.read_text());overlap=set(meta['requested_symbols'])&set(symbols)
            if overlap:
                old=pd.read_parquet(candidate.with_suffix('.parquet'));cached.append(old[old.symbol.isin(overlap)]);covered.update(overlap)
        missing=sorted(set(symbols)-covered)
        if missing:cached.append(transport.fetch_window(t-pd.Timedelta(seconds=2),missing,HEADERS))
        f=pd.concat(cached,ignore_index=True).drop_duplicates(['symbol','quote_ts','bid_price','ask_price','bid_size','ask_size']) if cached else pd.DataFrame(columns=['symbol','quote_ts','bid_price','ask_price','bid_size','ask_size'])
        f.to_parquet(path,index=False)
        done.write_text(json.dumps({'timestamp':t.isoformat(),'requested_symbols':symbols,'rows':len(f)}))
    return t,pd.read_parquet(path)

def download(items,leg):
    frames=[];errors=[]
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks={executor.submit(pull,item):item for item in items}
        for i,future in enumerate(as_completed(tasks),1):
            try:
                t,f=future.result();f['window_ts']=t;frames.append(f)
            except Exception as exc:errors.append({'timestamp':tasks[future][0].isoformat(),'error':type(exc).__name__,'status':getattr(exc,'code',None)})
            if i%25==0 or i==len(items):print('QUOTES',leg,i,'/',len(items),'errors',len(errors),flush=True)
    (OUT/f'policy_quote_errors_{leg}.json').write_text(json.dumps(errors,indent=2))
    if errors:raise RuntimeError('Quote downloads incomplete; cached successes retained')
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()

def paths(quotes,exit_leg=False):
    q=quotes[(quotes.bid_price>0)&(quotes.ask_price>=quotes.bid_price)&(quotes.bid_size>0)&(quotes.ask_size>0)].copy()
    result={}
    for (t,s),g in q.groupby(['window_ts','symbol'],sort=False):
        g=g.sort_values('quote_ts').drop_duplicates('quote_ts',keep='last')
        lag=EXIT_ACTIVATION_SECONDS if exit_leg and EXIT_ACTIVATION_SECONDS is not None else ACTIVATION_SECONDS
        arrival=t+pd.Timedelta(seconds=lag);deadline=t+pd.Timedelta(seconds=60)-pd.Timedelta(nanoseconds=1) if exit_leg else t+pd.Timedelta(seconds=59)
        before=g[g.quote_ts<=arrival].tail(1)
        after=g[(g.quote_ts>arrival)&(g.quote_ts<=deadline)]
        if len(before) and (arrival-before.quote_ts.iloc[0]).total_seconds()<=2:
            before=before.copy();before['quote_ts']=arrival;g=pd.concat([before,after])
        else:g=after
        result[(t,s)]=g
    return result

def run():
    global HEADERS
    HEADERS=transport.api_headers();transport.WINDOW_SECONDS=62
    pool=pd.read_parquet(OUT/'policy_pool.parquet').reset_index(drop=True);pool['order_id']=np.arange(len(pool))
    bars=pd.read_parquet(OUT/'policy_endpoint_bars.parquet')
    touch=pool[['security_id','entry_ts','entry_price']].merge(bars[['security_id','stamp','low']],left_on=['security_id','entry_ts'],right_on=['security_id','stamp'],how='left')
    # The bar is only a retrospective download router; never a selection input.
    pool['entry_bar_touch']=touch.low.le(touch.entry_price*1.0005).to_numpy()
    pool['entry_bar_missing']=touch.low.isna().to_numpy()
    # A missing trade bar cannot establish a miss: check the quote coverage explicitly.
    (OUT/'quote_routing_integrity.json').write_text(json.dumps({'entry_bar_touches':int(pool.entry_bar_touch.sum()),'missing_bar_coverage_exceptions':int(pool.entry_bar_missing.sum()),'fees':0},indent=2))
    ep=paths(download(windows(pool[pool.entry_price.gt(0)&(pool.entry_bar_touch|pool.entry_bar_missing)],'entry'),'entry'))
    possible=[]
    for r in pool.itertuples():
        g=ep.get((r.entry_ts,r.symbol))
        if g is not None and len(g) and g.ask_price.min()<=r.entry_price*1.0005:possible.append(r.order_id)
    xp=paths(download(windows(pool[pool.order_id.isin(possible)],'exit'),'exit'),exit_leg=True)
    records=[]
    for r in pool.itertuples():
        e=ep.get((r.entry_ts,r.symbol));x=xp.get((r.exit_ts,r.symbol))
        deadline=r.exit_ts+pd.Timedelta(seconds=EXIT_LIMIT_TTL_SECONDS)
        force_time=r.exit_ts+pd.Timedelta(seconds=FORCE_SECONDS)
        for bps in LEVELS:
            el=r.entry_price*(1+bps/1e4);xl=r.exit_price*(1-bps/1e4)
            ef=e[e.ask_price<=el].head(1) if e is not None else pd.DataFrame()
            filled=bool(len(ef));xf=x[(x.bid_price>=xl)&(x.quote_ts<=deadline)].head(1) if x is not None else pd.DataFrame()
            limit_exit=filled and bool(len(xf));force=filled and not limit_exit
            forced_book=pd.DataFrame()
            if force and x is not None:
                before=x[x.quote_ts<=force_time].tail(1)
                if len(before) and (force_time-before.quote_ts.iloc[0]).total_seconds()<=2:
                    forced_book=before.copy();forced_book['quote_ts']=force_time
                else:forced_book=x[x.quote_ts>force_time].head(1)
            priced=not filled or limit_exit or bool(len(forced_book))
            price=xl if limit_exit else (float(forced_book.bid_price.iloc[0]) if force and priced else np.nan)
            if force and priced and EXIT_LIMIT_TTL_SECONDS<FORCE_SECONDS:price=min(price,xl)
            records.append({'order_id':r.order_id,'bps':bps,'entry_filled':filled,'limit_exit':limit_exit,'forced_exit':force,'priced':priced,
                'entry_fill_ts':ef.quote_ts.iloc[0] if filled else pd.NaT,'exit_fill_ts':xf.quote_ts.iloc[0] if limit_exit else (forced_book.quote_ts.iloc[0] if force and priced else deadline if filled else pd.NaT),
                'executed_entry_price':el if filled else np.nan,'executed_exit_price':price,
                'return':price/el-1 if filled and priced else (0 if not filled else np.nan)})
    detail=pd.DataFrame(records);detail.to_parquet(OUT/'policy_quote_outcomes.parquet',index=False)
    pool.to_parquet(OUT/'policy_quote_pool.parquet',index=False)
    print('OUTCOMES',len(detail),'possible entries',len(possible),'unpriced',int((~detail.priced).sum()),flush=True)
    if RUN_ALLOCATION:allocate(pool,detail)

def allocate(pool,detail):
    detail=detail.copy()
    for column in ['entry_fill_ts','exit_fill_ts']:detail[column]=pd.to_datetime(detail[column],utc=True)
    pool=pool.copy();pool['tie']=pd.util.hash_pandas_object(pool.security_id.astype(str)+pool.session_date.astype(str)+'0',index=False).to_numpy()
    output=[];summaries=[]
    for slots,ranked in [(10,True),(10,False),(3,True)]:
        for bps in LEVELS:
            z=pool.merge(detail[detail.bps==bps],on='order_id',validate='one_to_one')
            z=z.sort_values(['entry_ts']+(['rank_score'] if ranked else [])+['tie','observation_id'],ascending=[True]+([False] if ranked else [])+[True,True],kind='stable')
            free=np.full(slots,-1,dtype=np.int64);active={};attempts=[]
            for r in z.itertuples():
                t=r.entry_ts.value+SELECTION_DELAY_SECONDS*1_000_000_000
                if active.get(r.security_id,-1)>t:continue
                slot=int(free.argmin())
                if free[slot]>t:continue
                # Select the attempt before looking at attainability; a miss consumes this window.
                release=(r.exit_fill_ts.value if r.entry_filled else t+59_000_000_000)+1
                free[slot]=release;active[r.security_id]=release;attempts.append(r.order_id)
            g=z[z.order_id.isin(attempts)].copy();g['slots']=slots;g['ranked']=ranked
            g['selection_ts']=g.entry_ts+pd.Timedelta(seconds=SELECTION_DELAY_SECONDS);output.append(g)
            if (~g.priced).any():
                summaries.append({'slots':slots,'ranked':ranked,'bps':bps,'status':'unpriced_liability','unpriced':int((~g.priced).sum())});continue
            fills=g[g.entry_filled];daily=g.groupby(g.entry_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d'))['return'].sum()/slots
            sym=fills.groupby('security_id')['return'].sum().sort_values(ascending=False);trim=fills[~fills.security_id.isin(sym.head(5).index)]
            summaries.append({'slots':slots,'ranked':ranked,'bps':bps,'status':'complete','attempts':len(g),'fills':len(fills),'misses':len(g)-len(fills),
                'forced_exits':int(g.forced_exit.sum()),'entry_days':g.entry_ts.dt.date.nunique(),'symbols':fills.security_id.nunique(),
                'gross_fixed_base_pct':g['return'].sum()/slots*100,'mean_fill_bps':fills['return'].mean()*1e4,
                'ex_top5_mean_bps':trim['return'].mean()*1e4,'max_hold_hours':(fills.exit_fill_ts-fills.entry_fill_ts).dt.total_seconds().max()/3600})
    pd.concat(output).to_parquet(OUT/'policy_quote_attempts.parquet',index=False)
    result=pd.DataFrame(summaries);result.to_parquet(OUT/'policy_quote_summary.parquet',index=False)
    print(result.to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--allocate-only',action='store_true');a=p.parse_args()
    if a.allocate_only:allocate(pd.read_parquet(OUT/'policy_quote_pool.parquet'),pd.read_parquet(OUT/'policy_quote_outcomes.parquet'))
    else:run()
