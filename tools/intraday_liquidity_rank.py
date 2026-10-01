"""Mechanism-oriented consistency screen; fixed selection, allocation and cost comparisons."""
import json
import numpy as np
import pandas as pd
from intraday_strategy_search import ROOT,OUT,COSTS,obs_arrays
from intraday_entry_search import allocate
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
D=OUT/'liquidity_rank_replay';D.mkdir(exist_ok=True)
rules=pd.read_parquet(OUT/'stable_broad_replay/rules.parquet');rules=rules[rules.mechanism_id.isin([68,23,66])];rules.to_parquet(D/'rules.parquet',index=False)
liquidity=None
for meta in (ROOT/'cache/features/intraday_5m').glob('*.json'):
 z=json.loads(meta.read_text());columns=z.get('columns',[])
 if 'dollar_volume__30m__raw__intraday_5m' in columns:liquidity=np.load(meta.with_suffix('.npy'),mmap_mode='r')[:,columns.index('dollar_volume__30m__raw__intraday_5m')];break
if liquidity is None:raise RuntimeError('Causal dollar-volume cache unavailable')
obs,t,day,days,sec,securities,closes=obs_arrays();del obs
axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);minute=t-opens[day];prices=np.load(OUT/'opens.npy',mmap_mode='r');reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m');groups=reader.read_groups('time_bucket',0,reader.rows);month=pd.to_datetime(days).strftime('%Y-%m');rows=[];ledgers=[]
for r in rules.itertuples():
 a=decode_packed_bins(reader.read_columns('bins',[r.feature_a],0,reader.rows)[:,0],r.resolution)
 if r.feature_b:
  b=decode_packed_bins(reader.read_columns('bins',[r.feature_b],0,reader.rows)[:,0],r.resolution);state=np.where((a>=0)&(b>=0),a*r.resolution+b,-1)
 else:state=a
 ix=np.flatnonzero((state==r.cell)&((r.time_group==-1)|(groups==r.time_group))&(minute>=5)&(t+1+r.horizon<=closes[day]-5));di=day[ix];si=sec[ix];mi=minute[ix];ep=prices[di,si,mi+1];xp=prices[di,si,mi+1+r.horizon];recent=liquidity[ix]
 release=t[ix]+1+r.horizon
 for extra in range(1,391):
  pending=np.flatnonzero(~np.isfinite(xp)&(release+extra<=closes[di]-5))
  if len(pending)==0:break
  value=prices[di[pending],si[pending],minute[ix[pending]]+1+r.horizon+extra];ok=np.isfinite(value);loc=pending[ok];xp[loc]=value[ok];release[loc]+=extra
 good=np.isfinite(ep);release=release[good];ix=ix[good];di=di[good];si=si[good];ep=ep[good];xp=xp[good];recent=recent[good]
 for ranking in ['liquid']:
  for slots in [1,5,10]:
   picked,_=allocate(t[ix]+1,release,si,np.ones(len(ix),bool),slots,priority=np.nan_to_num(recent,nan=-1) if ranking=='liquid' else None)
   gross=r.direction*(xp[picked]/ep[picked]-1)*10000;dd=di[picked]
   if len(gross)<100 or not np.isfinite(gross).all():continue
   ledger=pd.DataFrame({'mechanism_id':r.mechanism_id,'ranking':ranking,'slots':slots,'observation_id':ix[picked],'day':dd,'security_code':si[picked],'entry_minute':t[ix[picked]]+1,'exit_minute':release[picked],'gross_bps':gross,'side':r.direction});ledgers.append(ledger)
   for capital in [.25,.5,1.]:
    for cost in COSTS:
     # Each slot gets capital/slots of day-start equity, not independently compounded equity.
     daily=np.bincount(dd,weights=(gross-2*cost)*capital/slots/10000,minlength=len(days));eq=np.cumprod(1+daily);monthly=pd.Series(daily).groupby(month).apply(lambda v:np.prod(1+v)-1);peak=np.maximum.accumulate(np.r_[1,eq])[1:]
     rows.append({'mechanism_id':r.mechanism_id,'ranking':ranking,'slots':slots,'capital':capital,'cost':cost,'gross_bps':float(gross.mean()),'trades':len(gross),'trades_day':len(gross)/len(days),'return_pct':(eq[-1]-1)*100,'daily_dd_pct':(1-eq/peak).max()*100,'positive_months':int((monthly>0).sum()),'worst_month_pct':monthly.min()*100,'median_month_pct':monthly.median()*100,'bps_day':daily.mean()*10000,'first_half_bps':daily[:126].mean()*10000,'second_half_bps':daily[126:].mean()*10000,'trim5_bps_day':(daily.sum()-np.sort(daily)[-5:].sum())/len(days)*10000})
 print('MECHANISM',r.mechanism_id+1,len(rules),flush=True)
pd.DataFrame(rows).to_parquet(D/'results.parquet',index=False);pd.concat(ledgers,ignore_index=True).to_parquet(D/'trades.parquet',index=False)
s=pd.DataFrame(rows);print(s[(s.cost==0)&(s.capital==1)].sort_values(['positive_months','worst_month_pct','bps_day'],ascending=False).head(12).to_string(index=False))
