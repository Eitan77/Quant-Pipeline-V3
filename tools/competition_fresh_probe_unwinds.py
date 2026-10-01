"""Price every failed intraday exit at the first fresh liquidation book, no fees."""
import json,argparse,time,threading
import pandas as pd,exchange_calendars as xc
import competition_fresh_quotes as engine
import competition_fresh_intraday_probe as report
from competition_fresh_intraday_probe import PROBE,OUT

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--folder');args=parser.parse_args()
    if args.folder:PROBE=OUT/args.folder
    report.PROBE=PROBE
    f=pd.read_parquet(PROBE/'policy_quote_pool.parquet');d=pd.read_parquet(PROBE/'policy_quote_outcomes.parquet')
    d['exit_fill_ts']=pd.to_datetime(d.exit_fill_ts,utc=True).dt.as_unit('ns')
    needed=f[f.order_id.isin(d.loc[d.forced_exit,'order_id'])]
    if needed.empty:print('No unpriced exits',flush=True);report.summarize();raise SystemExit(0)
    engine.OUT=PROBE;engine.Q=OUT/'policy_quotes';engine.HEADERS=engine.transport.api_headers()
    # Pace actual HTTP pages, preserving cached requests and the bounded transport retry.
    original_open=engine.transport.urlopen;gate=threading.Lock();last=[0.]
    def paced_open(*a,**kw):
        with gate:
            wait=max(0.,last[0]+.4-time.monotonic())
            if wait:time.sleep(wait)
            last[0]=time.monotonic()
        return original_open(*a,**kw)
    engine.transport.urlopen=paced_open
    schedule=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    closes=dict(zip(schedule.index.strftime('%Y-%m-%d'),pd.to_datetime(schedule['close'],utc=True)))
    for row in f.itertuples():
        close=closes[row.exit_ts.tz_convert('America/New_York').strftime('%Y-%m-%d')]
        if row.exit_ts+pd.Timedelta(seconds=61)>=close:
            late=(d.order_id==row.order_id)&d.limit_exit&(pd.to_datetime(d.exit_fill_ts,utc=True)>row.exit_ts+pd.Timedelta(seconds=54))
            d.loc[late,'limit_exit']=False;d.loc[late,'forced_exit']=True
    needed=f[f.order_id.isin(d.loc[d.forced_exit,'order_id'])].copy()
    # Older liquidation assumptions are invalid until the revised clock is priced.
    forced=d.forced_exit
    d.loc[forced,'priced']=False
    d.loc[forced,['executed_exit_price','return']]=float('nan')
    d.loc[forced,'exit_fill_ts']=pd.NaT
    needed['last_minute']=needed.exit_ts.map(lambda t:t+pd.Timedelta(seconds=61)>=closes[t.tz_convert('America/New_York').strftime('%Y-%m-%d')])
    books={}
    for last_minute in [False,True]:
        subset=needed[needed.last_minute==last_minute]
        if subset.empty:continue
        anchor=54 if last_minute else 59;engine.transport.WINDOW_SECONDS=8 if last_minute else 123
        items=[(pd.Timestamp(t)+pd.Timedelta(seconds=anchor),sorted(g.symbol.unique())) for t,g in subset.groupby('exit_ts')]
        q=engine.download(items,'forced_exit_closing' if last_minute else 'forced_exit_recovery')
        q=q[(q.bid_price>0)&(q.ask_price>=q.bid_price)&(q.bid_size>0)&(q.ask_size>0)].sort_values('quote_ts')
        books.update({(t,s):h for (t,s),h in q.groupby(['window_ts','symbol'],sort=False)})
    repaired=0
    for r in needed.itertuples():
        anchor=r.exit_ts+pd.Timedelta(seconds=54 if r.last_minute else 59)
        force=r.exit_ts+pd.Timedelta(seconds=56 if r.last_minute else 61);book=books.get((anchor,r.symbol))
        if book is None:continue
        close=closes[r.exit_ts.tz_convert('America/New_York').strftime('%Y-%m-%d')]
        book=book[(book.quote_ts<=r.exit_ts+pd.Timedelta(seconds=180))&(book.quote_ts<close)]
        before=book[book.quote_ts<=force].tail(1)
        if len(before) and (force-before.quote_ts.iloc[0]).total_seconds()<=2:
            book=before.copy();book['quote_ts']=force
        else:book=book[book.quote_ts>force].head(1)
        if not len(book):continue
        mask=(d.order_id==r.order_id)&d.forced_exit;price=float(book.bid_price.iloc[0])
        limits=r.exit_price*(1-d.loc[mask,'bps']/1e4)
        # A missing exit reference prevents a sell limit, not liquidation of the holding.
        d.loc[mask,'executed_exit_price']=limits.clip(upper=price).fillna(price);d.loc[mask,'exit_fill_ts']=book.quote_ts.iloc[0]
        d.loc[mask,'return']=d.loc[mask,'executed_exit_price']/d.loc[mask,'executed_entry_price']-1;d.loc[mask,'priced']=True;repaired+=int(mask.sum())
    d.to_parquet(PROBE/'policy_quote_outcomes.parquet',index=False)
    scope=json.loads((PROBE/'scope.json').read_text());scope['failed_exit_liquidation']='Cancel at 59, acknowledge by 60, force at 61. Last session minute: cancel at 54, force at 56. Fresh bid age <=2sec, or first subsequent valid NBBO within 180sec and before close. Force price capped at exit limit for cancellation conservatism.'
    scope['unpriced_liabilities_remaining']=int((~d.priced).sum());(PROBE/'scope.json').write_text(json.dumps(scope,indent=2))
    print('REPAIRED',repaired,'remaining unpriced',int((~d.priced).sum()),flush=True);report.summarize()
