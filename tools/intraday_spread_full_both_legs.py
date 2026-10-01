"""Predetermined 24-session quote diagnostic; frozen candidate schedules, shared capital."""
import json,time,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.request import Request,urlopen
from urllib.parse import urlencode
import pandas as pd
import numpy as np
import duckdb
from dotenv import dotenv_values
O=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/intraday_strategy_20260928');Q=O/'spread_quote_full';D=O/'spread_full_both_legs';D.mkdir(exist_ok=True);coverage=True;full=True
a=json.loads((O/'price_axes.json').read_text());m=pd.read_parquet(Q/'manifest.parquet');base=pd.read_parquet(Q/'replays.parquet');subset=m.loc[base['sample'].unique()]
v=dotenv_values('D:/AlgoResearch/.env');headers={'APCA-API-KEY-ID':v.get('ALPACA_API_KEY_ID') or v.get('APCA_API_KEY_ID'),'APCA-API-SECRET-KEY':v.get('ALPACA_API_SECRET_KEY') or v.get('APCA_API_SECRET_KEY')}
def fetch(symbol,minute,kind):
 path=D/f'{symbol}_{int(minute)}_{kind}{"_asof" if symbol=="PARA" else ""}.parquet'
 if path.exists():return pd.read_parquet(path)
 if coverage:
  for folder in ['stable_quote_sample','high_margin_quote_sample','mechanism_quote_sample','quote_leaders_full','quote_expanded']:
   prior=O/folder/path.name
   if prior.exists():
    cached=pd.read_parquet(prior)
    if len(cached[cached.ns<=int(minute)*60_000_000_000]):
     cached.to_parquet(path,index=False);return cached
 else:
  prior=O/'quote_expanded'/path.name
  if full and prior.exists():return pd.read_parquet(prior)
 start=pd.Timestamp(minute,unit='m',tz='UTC');end=start+pd.Timedelta(seconds=60);token=None;rows=[]
 while True:
  params={'symbols':symbol,'start':(start-pd.Timedelta(seconds=30)).isoformat(),'end':end.isoformat(),'feed':'sip','sort':'asc','limit':10000,'asof':start.strftime('%Y-%m-%d')}
  if token:params['page_token']=token
  for attempt in range(4):
   try:
    with urlopen(Request('https://data.alpaca.markets/v2/stocks/quotes?'+urlencode(params),headers=headers),timeout=30) as response:p=json.load(response)
    break
   except Exception:
    if attempt==3:raise
    time.sleep(2**attempt)
  rows.extend(p.get('quotes',{}).get(symbol,[]));token=p.get('next_page_token')
  if not token:break
 q=pd.DataFrame([{'ns':pd.Timestamp(x['t']).value,'bid':x['bp'],'ask':x['ap'],'bs':x['bs'],'az':x['as']} for x in rows],columns=['ns','bid','ask','bs','az']);
 if not (q.ns<=start.value).any():
  lookup={'symbols':symbol,'start':(start-pd.Timedelta(seconds=300)).isoformat(),'end':start.isoformat(),'feed':'sip','sort':'desc','limit':1,'asof':start.strftime('%Y-%m-%d')}
  with urlopen(Request('https://data.alpaca.markets/v2/stocks/quotes?'+urlencode(lookup),headers=headers),timeout=30) as response:prior=json.load(response).get('quotes',{}).get(symbol,[])
  if prior:
   z=prior[0];one=pd.DataFrame([{'ns':pd.Timestamp(z['t']).value,'bid':z['bp'],'ask':z['ap'],'bs':z['bs'],'az':z['as']}]);q=pd.concat([one,q],ignore_index=True).sort_values('ns',kind='stable')
 q.to_parquet(path,index=False);return q
# Freeze the existing entry sample and test all exit offsets on the same paths.
rows=[];paths={};methods=['market',-1,0,1,2,3,4,5]
valid=lambda z:z.bid>0 and z.ask>=z.bid and z.bs>0 and z.az>0
for sample in base['sample'].unique():
 r=m.loc[sample];ns=int(r.exit_minute)*60_000_000_000
 deadline=min(ns+60_000_000_000,(a['close_minutes'][int(r.day)]-5)*60_000_000_000)
 q=pd.read_parquet(Q/f'{r.symbol}_{int(r.exit_minute)}_exit{"_asof" if r.symbol=="PARA" else ""}.parquet').sort_values('ns',kind='stable')
 e=q[q.ns<=ns].iloc[-1];end=q[q.ns<=deadline].iloc[-1]
 assert valid(e) and valid(end), 'Invalid exit state; do not silently drop attempts'
 old=pd.read_parquet(Q/f'{r.symbol}_{int(r.exit_minute)}_exit{"_asof" if r.symbol=="PARA" else ""}.parquet')
 old=old[old.ns<=ns].sort_values('ns',kind='stable').iloc[-1]
 assert e.bid==old.bid and e.ask==old.ask, 'Baseline exit quote changed'
 paths[sample]=(e,end,q[(q.ns>ns)&(q.ns<=deadline)&(q.bid>0)&(q.ask>=q.bid)&(q.bs>0)&(q.az>0)],ns,deadline)
for b in base.itertuples():
 r=m.loc[b.sample];side=int(r.side);e,end,path,ns,deadline=paths[b.sample]
 xp=e.bid if side==1 else e.ask;mid=(e.bid+e.ask)/2
 ep=xp/(1+side*b.bps/10000) if b.filled else np.nan
 for offset in methods:
  fill=np.nan;wait=0.;limit_filled=False;fallback=False
  if b.filled:
   raw=mid*(1+side*offset/10000) if offset!='market' else xp
   limit=(np.ceil((raw-1e-10)*100) if side==1 else np.floor((raw+1e-10)*100))/100
   immediate=offset=='market' or (limit<=e.bid if side==1 else limit>=e.ask)
   hits=path[path.bid>limit] if side==1 else path[path.ask<limit]
   if immediate:fill=xp;limit_filled=offset!='market'
   elif len(hits):fill=limit;wait=(hits.iloc[0].ns-ns)/1e9;limit_filled=True
   else:fill=end.bid if side==1 else end.ask;wait=(deadline-ns)/1e9;fallback=True
  rows.append({'strategy':b.strategy,'sample':b.sample,'day':int(r.day),'symbol':r.symbol,'entry_method':b.method,'exit_method':str(offset),'entry_filled':bool(b.filled),'entry_price':ep,'exit_price':fill,'bps':side*(fill/ep-1)*10000 if b.filled else 0.,'exit_limit_filled':limit_filled,'exit_fallback':fallback,'exit_wait_seconds':wait})
r=pd.DataFrame(rows);assert len(r)==len(base)*8
r.to_parquet(D/'both_legs_replays.parquet',index=False)
summary=r.groupby(['strategy','entry_method','exit_method']).agg(attempts=('sample','count'),entry_fills=('entry_filled','sum'),exit_limit_fills=('exit_limit_filled','sum'),exit_fallbacks=('exit_fallback','sum'),bps_attempt=('bps','mean'),total_bps=('bps','sum')).reset_index()
summary['bps_fill']=summary.total_bps/summary.entry_fills
summary.to_parquet(D/'both_legs_summary.parquet',index=False)
print(summary.sort_values('bps_attempt',ascending=False).groupby('strategy',sort=False).head(3).to_string(index=False))
# Sample stability only, without annualization or inferred portfolio returns.
r['month']=[str(a['days'][d])[:7] for d in r.day]
monthly=r.groupby(['strategy','entry_method','exit_method','month']).agg(attempts=('sample','count'),fills=('entry_filled','sum'),total_bps=('bps','sum')).reset_index()
monthly.to_parquet(D/'both_legs_monthly.parquet',index=False)
for strategy,g in r.groupby('strategy'):
 best=summary[summary.strategy==strategy].sort_values('bps_attempt',ascending=False).iloc[0]
 z=g[(g.entry_method==best.entry_method)&(g.exit_method==best.exit_method)]
 print('STABILITY',strategy,best.entry_method,best.exit_method,'positive_months',int((z.groupby('month').bps.sum()>0).sum()),'trim3',z.bps.nsmallest(len(z)-3).sum()/len(z))

# Same-price identity check against minute-open bars; flags require inspection.
prices=np.load(O/'opens.npy',mmap_mode='r');flags=[]
for b in base[base.method=='market'].itertuples():
 t=m.loc[b.sample];e=paths[b.sample][0];side=int(t.side);xp=e.bid if side==1 else e.ask;ep=xp/(1+side*b.bps/10000)
 k=int(t.entry_minute)-a['open_minutes'][int(t.day)];bar=prices[int(t.day),int(t.security_code),k]
 if abs(ep/bar-1)>.02:flags.append({'sample':b.sample,'symbol':t.symbol,'quote_entry':ep,'bar_entry':float(bar)})
(D/'identity_flags.json').write_text(json.dumps(flags,indent=2));print('IDENTITY FLAGS',flags)
