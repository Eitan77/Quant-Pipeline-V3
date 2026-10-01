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
O=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/intraday_strategy_20260928'); coverage='--full-coverage' in sys.argv;full='--leaders-full' in sys.argv or coverage;D=O/('quote_leaders_coverage' if coverage else 'quote_leaders_full' if full else 'quote_expanded');D.mkdir(exist_ok=True)
a=json.loads((O/'price_axes.json').read_text()); days=pd.to_datetime(a['days']); selected=[]
for month in sorted(set(days.strftime('%Y-%m'))):
 ix=np.flatnonzero(days.strftime('%Y-%m')==month);selected.extend([int(ix[len(ix)//3]),int(ix[2*len(ix)//3])])
if full:selected=list(range(len(days)))
syms=dict(duckdb.connect('D:/AlgoResearch/Quant-Pipeline-V3/cache/source/20240401_20260430/catalog.duckdb',read_only=True).execute('select security_id,symbol from security_master').fetchall())
coverage=True;full=True;mechanism_full='--mechanism-full' in sys.argv;D=O/('direct_lag_quote_full' if mechanism_full else 'direct_lag_quote_sample');D.mkdir(exist_ok=True)
f=pd.read_parquet(O/'direct_market_lag/trades.parquet');frames=[]
for ident,ranking,slots in ([(68,'neutral',5)] if mechanism_full else [(9,'neutral',5),(23,'neutral',5),(24,'neutral',1)]):
 g=f[(f.mechanism_id==ident)&(f.ranking==ranking)&(f.slots==slots)].sort_values(['entry_minute','observation_id']).copy();g['month']=[days[int(i)].strftime('%Y-%m') for i in g.day]
 for _,monthframe in g.groupby('month'):
  z=monthframe.copy() if mechanism_full else monthframe.sample(n=min(6,len(monthframe)),random_state=20260928).copy();z['strategy']=f'mechanism{ident}';frames.append(z)
m=pd.concat(frames,ignore_index=True);m['symbol']=[syms[a['securities'][int(i)]] for i in m.security_code];m['source_symbol']=m.symbol;m.loc[m.symbol=='PEAK','symbol']='DOC';m['symbol']=m.symbol.replace({'JEC':'J','UTX':'RTX','WRK':'SW'});m.loc[(m.symbol=='VIAC')&(m.entry_minute<pd.Timestamp('2025-08-07',tz='UTC').value//60_000_000_000),'symbol']='PARA';m.to_parquet(D/'manifest.parquet',index=False)
v=dotenv_values('D:/AlgoResearch/.env');headers={'APCA-API-KEY-ID':v.get('ALPACA_API_KEY_ID') or v.get('APCA_API_KEY_ID'),'APCA-API-SECRET-KEY':v.get('ALPACA_API_SECRET_KEY') or v.get('APCA_API_SECRET_KEY')}
def fetch(symbol,minute,kind):
 path=D/f'{symbol}_{int(minute)}_{kind}{"_asof" if symbol=="PARA" else ""}.parquet'
 if path.exists():return pd.read_parquet(path)
 if coverage:
  for folder in ['stable_quote_sample','high_margin_quote_sample','mechanism_quote_sample','quote_leaders_full','quote_expanded']:
   prior=O/folder/path.name
   if kind=='entry' and prior.exists():
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
jobs=sorted(set((r.symbol,int(r.entry_minute),'entry') for r in m.itertuples())|set((r.symbol,int(r.exit_minute),'exit') for r in m.itertuples()))
print('MANIFEST',len(m),'trades',len(jobs),'windows',flush=True);errors=[]
with ThreadPoolExecutor(max_workers=1) as pool:
 fs={pool.submit(fetch,*j):j for j in jobs}
 for i,f in enumerate(as_completed(fs)):
  try:f.result()
  except Exception as e:errors.append({'window':fs[f],'error_type':type(e).__name__})
  if (i+1)%100==0:print('FETCH',i+1,len(jobs),flush=True)
(D/'download_errors.json').write_text(json.dumps(errors))
def arrival(q,minute):
 ns=int(minute)*60_000_000_000;q=q.sort_values('ns',kind='stable')
 if coverage:
  before=q[q.ns<=ns].tail(1)
  if len(before):
   v=before.iloc[0]
   if v.bid>0 and v.ask>=v.bid and v.bs>0 and v.az>0:return v,q[(q.bid>0)&(q.ask>=q.bid)&(q.bs>0)&(q.az>0)]
  return None,q
 q=q[(q.bid>0)&(q.ask>=q.bid)&(q.bs>0)&(q.az>0)];before=q[q.ns<=ns].tail(1)
 if len(before) and ns-before.iloc[0].ns<=5e9:return before.iloc[0],q
 after=q[(q.ns>=ns)&(q.ns<=ns+1e9)]
 return (after.iloc[0],q) if len(after) else (None,q)
rows=[];missing=[]
for r in m.itertuples():
 try:entry,q=arrival(fetch(r.symbol,r.entry_minute,'entry'),r.entry_minute);ex,x=arrival(fetch(r.symbol,r.exit_minute,'exit'),r.exit_minute)
 except Exception:missing.append(r.Index);continue
 if entry is None or ex is None:missing.append(r.Index);continue
 side=int(r.side);mid=(entry.bid+entry.ask)/2;take=entry.ask if side==1 else entry.bid;xp=ex.bid if side==1 else ex.ask
 for offset in ['market',-1,0,1,2,3,4,5]:
  raw=mid*(1-side*offset/10000) if offset!='market' else take
  limit=(np.floor((raw+1e-10)*100) if side==1 else np.ceil((raw-1e-10)*100))/100 if offset!='market' else take
  immediate=offset=='market' or (limit>=entry.ask if side==1 else limit<=entry.bid)
  later=q[q.ns>max(entry.ns,int(r.entry_minute)*60_000_000_000)];hits=later[later.ask<limit] if side==1 else later[later.bid>limit]
  filled=immediate or len(hits)>0;ep=take if immediate else limit;wait=0 if immediate else (hits.iloc[0].ns-int(r.entry_minute)*60_000_000_000)/1e9 if filled else 60
  pnl=side*(xp/ep-1)*10000 if filled else 0
  rows.append({'sample':r.Index,'strategy':r.strategy,'day':int(r.day),'symbol':r.symbol,'method':str(offset),'filled':filled,'bps':pnl,'wait_seconds':wait,'entry_minute':r.entry_minute,'exit_minute':r.exit_minute,'bar_bps':r.gross_bps,'arrival_spread_bps':(entry.ask-entry.bid)/mid*10000,'entry_quote_age_seconds':(int(r.entry_minute)*60_000_000_000-entry.ns)/1e9,'exit_quote_age_seconds':(int(r.exit_minute)*60_000_000_000-ex.ns)/1e9})
r=pd.DataFrame(rows);r.to_parquet(D/'replays.parquet',index=False);(D/'missing.json').write_text(json.dumps(missing));reports=[];dailyrows=[]
summary=r.groupby(['strategy','method']).agg(attempts=('sample','count'),fills=('filled','sum'),bps_attempt=('bps','mean'),total_bps=('bps','sum')).reset_index();summary['bps_fill']=summary.total_bps/summary.fills;summary.to_parquet(D/'summary.parquet',index=False);print(summary.to_string(index=False))
