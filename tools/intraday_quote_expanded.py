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
frames=[]
for name,file,col,ident in [('core240','topone_trades.parquet','id',1),('fresh15','confirmation_trades.parquet','confirmation_id',840),('fast10','confirmation_trades.parquet','confirmation_id',302)]:
 if full:continue
 f=pd.read_parquet(O/'entry_extension'/file);f=f[(f[col]==ident)&f.day.isin(selected)].copy();f['strategy']=name;f['side']=-1;frames.append(f)
b=pd.read_parquet(O/'breadth_extension/leader_trades.parquet')
for ident in ([115,78] if full else [115,78,338]):
 f=b[(b.rule_id==ident)&(b.slots==1)&b.day.isin(selected)].copy();f['strategy']=f'breadth{ident}';frames.append(f)
m=pd.concat(frames,ignore_index=True);m['symbol']=[syms[a['securities'][int(s)]] for s in m.security_code];m['source_symbol']=m['symbol']
if coverage:
 # Same security_id in local master; SEC March1 2024 8-K confirms DOC effective March4.
 m.loc[(m.symbol=='PEAK')&(m.entry_minute>=28493280),'symbol']='DOC'
m.to_parquet(D/'manifest.parquet',index=False)
(D/'design.json').write_text(json.dumps({'days':selected,'selection':'all discovery sessions' if full else 'two fixed dates per month at one-third and two-thirds positions, no profit selection','offsets':[-1,0,1,2,3,4,5],'wait_seconds':60,'cost_overlay':False,'quote_state':'last reported raw quote at or before order time, no future fallback' if coverage else '5second freshness or next1second','scope':'frozen standalone schedules; skipped signals are not regenerated after missed fills'},indent=2))
v=dotenv_values('D:/AlgoResearch/.env');headers={'APCA-API-KEY-ID':v.get('ALPACA_API_KEY_ID') or v.get('APCA_API_KEY_ID'),'APCA-API-SECRET-KEY':v.get('ALPACA_API_SECRET_KEY') or v.get('APCA_API_SECRET_KEY')}
def fetch(symbol,minute,kind):
 path=D/f'{symbol}_{int(minute)}_{kind}.parquet'
 if path.exists():return pd.read_parquet(path)
 if coverage:
  for folder in ['quote_leaders_full','quote_expanded']:
   prior=O/folder/path.name
   if prior.exists():
    cached=pd.read_parquet(prior)
    if len(cached[cached.ns<=int(minute)*60_000_000_000]):
     cached.to_parquet(path,index=False);return cached
 else:
  prior=O/'quote_expanded'/path.name
  if full and prior.exists():return pd.read_parquet(prior)
 start=pd.Timestamp(minute,unit='m',tz='UTC');end=start+pd.Timedelta(seconds=60 if kind=='entry' else 1);token=None;rows=[]
 while True:
  params={'symbols':symbol,'start':(start-pd.Timedelta(seconds=300 if coverage else 30)).isoformat(),'end':end.isoformat(),'feed':'sip','sort':'asc','limit':10000}
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
 q=pd.DataFrame([{'ns':pd.Timestamp(x['t']).value,'bid':x['bp'],'ask':x['ap'],'bs':x['bs'],'az':x['as']} for x in rows],columns=['ns','bid','ask','bs','az']);q.to_parquet(path,index=False);return q
jobs=sorted(set((r.symbol,int(r.entry_minute),'entry') for r in m.itertuples())|set((r.symbol,int(r.exit_minute),'exit') for r in m.itertuples()))
print('MANIFEST',len(m),'trades',len(jobs),'windows',flush=True);errors=[]
with ThreadPoolExecutor(max_workers=4) as pool:
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
  rows.append({'sample':r.Index,'strategy':r.strategy,'day':int(r.day),'symbol':r.symbol,'method':str(offset),'filled':filled,'bps':pnl,'wait_seconds':wait,'entry_minute':r.entry_minute,'exit_minute':r.exit_minute,'bar_bps':r.gross_bps,'entry_quote_age_seconds':(int(r.entry_minute)*60_000_000_000-entry.ns)/1e9,'exit_quote_age_seconds':(int(r.exit_minute)*60_000_000_000-ex.ns)/1e9})
r=pd.DataFrame(rows);r.to_parquet(D/'replays.parquet',index=False);(D/'missing.json').write_text(json.dumps(missing));reports=[];dailyrows=[]
def evaluate(name,g,method):
 free=-1;profits=[];n=0;fills=0;waits=[]
 for t in g.sort_values(['entry_minute','priority','sample']).itertuples():
  if t.entry_minute<free:continue
  n+=1;waits.append(t.wait_seconds)
  if t.filled:free=t.exit_minute;fills+=1;profits.append((t.day,t.bps))
  else:free=t.entry_minute+1
 daily={d:0. for d in selected}
 for d,p in profits:daily[d]=(1+daily[d])*(1+p/10000)-1
 vals=np.array(list(daily.values()));months={}
 for d,p in daily.items():months.setdefault(days[d].strftime('%Y-%m'),[]).append(p);dailyrows.append({'strategy':name,'method':method,'day':d,'return':p})
 reports.append({'strategy':name,'method':method,'attempts':n,'fills':fills,'missing_candidate_windows':sum(m.loc[missing,'strategy'].isin(g.strategy.unique())),'bps_per_fill':sum(p for _,p in profits)/fills if fills else np.nan,'bps_per_attempt':sum(p for _,p in profits)/n if n else np.nan,'bps_per_sample_day':vals.mean()*10000,'sample_return_pct':(np.prod(1+vals)-1)*100,'positive_months':sum(sum(v)>0 for v in months.values()),'first_half_bps_day':np.mean([v for d,v in daily.items() if d<126])*10000,'second_half_bps_day':np.mean([v for d,v in daily.items() if d>=126])*10000,'wait_seconds':np.mean(waits) if waits else np.nan})
for (name,method),g in r.groupby(['strategy','method']):g=g.copy();g['priority']=0;evaluate(name,g,method)
for method,g in r[r.strategy.isin(['core240','fresh15','fast10'])].groupby('method'):
 for order in [('core240','fresh15','fast10'),('fresh15','fast10','core240')]:
  h=g.copy();h['priority']=h.strategy.map({v:i for i,v in enumerate(order)});evaluate('combined_'+order[0],h,method)
s=pd.DataFrame(reports);s.to_parquet(D/'summary.parquet',index=False);pd.DataFrame(dailyrows).to_parquet(D/'daily.parquet',index=False)
print(s.sort_values('bps_per_sample_day',ascending=False).head(16).to_string(index=False),flush=True)
