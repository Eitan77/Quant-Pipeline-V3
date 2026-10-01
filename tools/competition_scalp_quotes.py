"""Whole-year balanced quote probe of frequent ETF shock reversal."""
import json,time
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np,pandas as pd
import fresh_overnight_quote_replay as transport
from competition_scalp import OUT,LEVELS,metrics

QOUT=OUT/'quote_probe';QOUT.mkdir(exist_ok=True)
RULE='reversion_1.5_5m__etfs'
SELECTION='all';WAIT_SECONDS=[15,59]

def prepare(n=1200):
    f=pd.read_parquet(OUT/'bar_trades.parquet');f=f[f.candidate_id==RULE].copy();axes=json.loads((OUT/'axes.json').read_text())
    f['symbol']=[axes['symbols'][x] for x in f.symbol_code]
    f['entry_ts']=pd.to_datetime(np.array(axes['open_epoch_ns'])[f.day]+(f.signal_minute.to_numpy()+1)*60_000_000_000,utc=True)
    f['exit_ts']=f.entry_ts+pd.to_timedelta(f.hold_minutes,unit='m')
    f['month']=f.entry_ts.dt.strftime('%Y-%m')
    f['hash']=pd.util.hash_pandas_object(f.symbol+f.entry_ts.astype(str)+'scalp_20260930',index=False).to_numpy()
    if SELECTION=='morning':f=f[f.signal_minute<90]
    if n:f=f.sort_values('hash').groupby('month',group_keys=False).head(n//12)
    f=f.sort_values('entry_ts').reset_index(drop=True)
    cp=np.load(OUT/'close.npy',mmap_mode='r')
    f['entry_price']=cp[f.day,f.symbol_code,f.signal_minute]
    f['exit_price']=cp[f.day,f.symbol_code,f.signal_minute+f.hold_minutes]
    f['trade_id']=np.arange(len(f));f.to_parquet(QOUT/'signals.parquet',index=False)
    (QOUT/'scope.json').write_text(json.dumps({'rule':RULE,'full_discovery_year':True,'balanced_quote_diagnostic_sample':len(f),
         'not_full_strategy_return':bool(n),'selection':SELECTION,'full_selected_ledger':not bool(n),'entry_latency_seconds':1,'post_observation_latency_seconds':1,'wait_seconds':WAIT_SECONDS,'quote_filter':'Entry bars reaching a requested level; forced-exit quotes are retained to price liabilities.',
         'arrival_filters':['all','spread<=1bp','spread<=1bp and signed queue imbalance>=0.6'],'out_of_sample_accessed':False},indent=2))
    print('QUOTE SAMPLE',len(f),'all 12 months',flush=True)

def download():
    f=pd.read_parquet(QOUT/'signals.parquet');axes=json.loads((OUT/'axes.json').read_text())
    hi=np.load(OUT/'high.npy',mmap_mode='r');lo=np.load(OUT/'low.npy',mmap_mode='r');plan={}
    for row in f.itertuples():
        for leg,stamp,price,minute,side in [('entry',row.entry_ts,row.entry_price,row.signal_minute+1,row.side),('exit',row.exit_ts,row.exit_price,row.signal_minute+1+row.hold_minutes,-row.side)]:
            touched=lo[row.day,row.symbol_code,minute]<=price*1.0005 if side==1 else hi[row.day,row.symbol_code,minute]>=price*.9995
            if touched or leg=='exit':plan.setdefault(stamp,set()).add(row.symbol)
    folder=QOUT/'windows';folder.mkdir(exist_ok=True);headers=transport.api_headers();transport.WINDOW_SECONDS=max(WAIT_SECONDS)-1
    def fetch(item):
        ts,symbols=item;path=folder/(ts.strftime('%Y%m%dT%H%M%SZ')+'.parquet')
        if not path.exists():
            original=OUT/'quote_probe/windows'/path.name
            cached=pd.read_parquet(original) if original.exists() else pd.DataFrame()
            present=set(cached.symbol.unique()) if len(cached) else set()
            missing=sorted(set(symbols)-present)
            if missing:
                fetched=transport.fetch_window(ts+pd.Timedelta(seconds=1),missing,headers)
                cached=pd.concat([cached,fetched],ignore_index=True)
            cached.to_parquet(path,index=False)
        return {'stamp':ts.isoformat(),'path':str(path)}
    done=[];errors=[];t0=time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs={pool.submit(fetch,item):item[0] for item in sorted(plan.items())}
        for job in as_completed(jobs):
            try:done.append(job.result())
            except Exception as exc:errors.append({'stamp':jobs[job].isoformat(),'error':type(exc).__name__})
            if (len(done)+len(errors))%500==0:print('QUOTES',len(done)+len(errors),'/',len(plan),'errors',len(errors),'seconds',round(time.time()-t0),flush=True)
    # Bounded retry of failed windows, preserving successful cached pulls.
    retry=[]
    for item in errors:
        stamp=pd.Timestamp(item['stamp'])
        try:done.append(fetch((stamp,plan[stamp])))
        except Exception as exc:retry.append({'stamp':stamp.isoformat(),'error':type(exc).__name__})
    errors=retry
    (QOUT/'download.json').write_text(json.dumps({'windows':done,'errors':errors,'requested':len(plan)},indent=2))

def replay(reference='completed_close'):
    f=pd.read_parquet(QOUT/'signals.parquet');info=json.loads((QOUT/'download.json').read_text());paths={}
    if reference=='completed_close':
        # Order prices are fixed from completed bars, never the upcoming bar's first trade.
        cp=np.load(OUT/'close.npy',mmap_mode='r')
        f['entry_price']=cp[f.day,f.symbol_code,f.signal_minute]
        f['exit_price']=cp[f.day,f.symbol_code,f.signal_minute+f.hold_minutes]
        alltrades=pd.read_parquet(OUT/'bar_trades.parquet');alltrades=alltrades[alltrades.candidate_id==RULE]
        if SELECTION=='morning':alltrades=alltrades[alltrades.signal_minute<90]
        ee=cp[alltrades.day,alltrades.symbol_code,alltrades.signal_minute]
        xx=cp[alltrades.day,alltrades.symbol_code,alltrades.signal_minute+alltrades.hold_minutes]
        axes=json.loads((OUT/'axes.json').read_text())
        stage=[]
        for level in LEVELS:
            direction=alltrades.side.to_numpy();ep=ee*(1+direction*level/10000);xp=xx*(1-direction*level/10000)
            stage.append({'reference':reference,'bps':level,**metrics(direction*(xp-ep)/ep,alltrades.day.to_numpy(),axes['days'],3)})
        pd.DataFrame(stage).to_parquet(QOUT/'causal_bar_sensitivity.parquet',index=False)
    for x in info['windows']:
        q=pd.read_parquet(x['path']);q=q[(q.bid_price>0)&(q.ask_price>=q.bid_price)&(q.bid_size>0)&(q.ask_size>0)].sort_values('quote_ts')
        for symbol,g in q.groupby('symbol',sort=False):paths[(pd.Timestamp(x['stamp']),symbol)]=g
    records=[]
    for row in f.itertuples():
        eq=paths.get((row.entry_ts,row.symbol));xq=paths.get((row.exit_ts,row.symbol))
        if eq is not None and len(eq):
            arrival=eq.iloc[0];mid=(arrival.ask_price+arrival.bid_price)/2
            spread=(arrival.ask_price-arrival.bid_price)/mid*10000
            queue=(arrival.bid_size if row.side==1 else arrival.ask_size)/(arrival.bid_size+arrival.ask_size)
        else:spread=queue=np.nan
        for wait in WAIT_SECONDS:
            # A spread/queue gate becomes known at the first received valid NBBO.
            # Activate every entry one second later so filtering cannot use its fill quote.
            epath=eq[(eq.quote_ts>=arrival.quote_ts+pd.Timedelta(seconds=1))&(eq.quote_ts<=row.entry_ts+pd.Timedelta(seconds=wait))] if eq is not None and len(eq) else None
            xpath=xq[xq.quote_ts<=row.exit_ts+pd.Timedelta(seconds=wait)] if xq is not None else None
            for bps in LEVELS:
                ep=row.entry_price*(1+row.side*bps/10000);xp=row.exit_price*(1-row.side*bps/10000)
                e=epath[(epath.ask_price<=ep) if row.side==1 else (epath.bid_price>=ep)] if epath is not None else None
                filled=e is not None and len(e)>0
                x=xpath[(xpath.bid_price>=xp) if row.side==1 else (xpath.ask_price<=xp)] if xpath is not None else None
                completed=filled and x is not None and len(x)>0
                exitp=np.nan;ret=0.;status='unfilled_entry'
                if eq is None or not len(eq):
                    lo=np.load(OUT/'low.npy',mmap_mode='r');hi=np.load(OUT/'high.npy',mmap_mode='r');minute=row.signal_minute+1
                    reached=lo[row.day,row.symbol_code,minute]<=row.entry_price*1.0005 if row.side==1 else hi[row.day,row.symbol_code,minute]>=row.entry_price*.9995
                    status='missing_entry_window' if reached else 'bar_did_not_reach';ret=np.nan if reached else 0.
                if filled:
                    if completed:exitp=xp;status='limit_exit'
                    elif xpath is not None and len(xpath):exitp=float(xpath.iloc[-1].bid_price if row.side==1 else xpath.iloc[-1].ask_price);status='forced_exit'
                    else:status='missing_exit';ret=np.nan
                    if np.isfinite(exitp):ret=row.side*(exitp-ep)/ep
                records.append({'reference':reference,'trade_id':row.trade_id,'day':row.day,'symbol':row.symbol,'month':row.month,'side':row.side,'wait_seconds':wait,'bps':bps,
                     'entry_attainable':filled,'exit_attainable':completed,'status':status,'return':ret,'spread_bps':spread,'signed_queue':queue})
    d=pd.DataFrame(records);d.to_parquet(QOUT/'details.parquet',index=False);rows=[];axes=json.loads((OUT/'axes.json').read_text())
    filters={'all':np.ones(len(d),bool),'tight_spread':d.spread_bps<=1,'tight_aligned_queue':(d.spread_bps<=1)&(d.signed_queue>=.6)}
    for condition,mask in filters.items():
        for (wait,bps),g in d[mask].groupby(['wait_seconds','bps']):
            for fee in [0,.5,1,2]:
                ret=g['return'].to_numpy()-g.entry_attainable.to_numpy()*fee/10000
                st=metrics(ret,g.day.to_numpy(),axes['days'],3)
                st.update({'condition':condition,'wait_seconds':wait,'bps':bps,'fee_bps_round_trip':fee,'attempts':len(g),
                    'filled_entries':int(g.entry_attainable.sum()),'completed_limits':int(g.exit_attainable.sum()),
                    'forced_exits':int(g.status.eq('forced_exit').sum()),'missing_exits':int(g.status.eq('missing_exit').sum()),
                    'missing_entry_windows':int(g.status.eq('missing_entry_window').sum()),
                    'mean_filled_bps':float(ret[g.entry_attainable].mean()*10000) if g.entry_attainable.any() else None})
                rows.append(st)
    result=pd.DataFrame(rows);result.to_parquet(QOUT/'summary.parquet',index=False)
    view=result[(result.fee_bps_round_trip==.5)&(result.wait_seconds==max(WAIT_SECONDS))]
    print(view[['condition','bps','attempts','filled_entries','mean_filled_bps','return_pct','max_dd_pct','positive_months','positive_week_fraction','missing_exits']].to_string(index=False),flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--rule',default=RULE);parser.add_argument('--sample',type=int,default=1200);parser.add_argument('--resume',action='store_true');parser.add_argument('--selection',default='all',choices=['all','morning']);parser.add_argument('--wait',type=int,choices=[15,59])
    args=parser.parse_args();RULE=args.rule;SELECTION=args.selection
    if args.wait:WAIT_SECONDS=[args.wait]
    if RULE!='reversion_1.5_5m__etfs':QOUT=OUT/('quote_probe_'+RULE);QOUT.mkdir(exist_ok=True)
    if SELECTION!='all':QOUT=OUT/('quote_'+SELECTION+'_'+RULE);QOUT.mkdir(exist_ok=True)
    if not args.resume:prepare(args.sample)
    download();replay()
