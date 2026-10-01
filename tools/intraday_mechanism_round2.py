"""Mechanism-oriented consistency screen; fixed selection, allocation and cost comparisons."""
import json
import numpy as np
import pandas as pd
from intraday_strategy_search import ROOT,OUT,COSTS,obs_arrays
from intraday_entry_search import allocate
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
D=OUT/'mechanism_round2';D.mkdir(exist_ok=True)
f=pd.read_parquet(OUT/'global_stable_surfaces.parquet')
seen=set()
for folder in ['stable_broad_replay','high_margin_replay','mechanism_consistency']:
 p=OUT/folder/'rules.parquet'
 if p.exists():seen.update(pd.read_parquet(p).pair_id)
f=f[~f.pair_id.isin(seen)].copy();chosen=[];used=set();counts={}
for family,pattern in [('market_response','market_lead_response|stock_lead_market_response|beta_residual_return|benchmark_excess_return'),('dislocation','price_shock_minus_volume_shock|volume_shock_minus_price_shock|failed_breakdown_strength|failed_breakout_strength'),('volume_confirmation','return_x_rvol|return_x_volume_z|absreturn_volume_corr|return_volume_corr|signed_volume_balance')]:
 g=f[f.feature_a.str.contains(pattern)|f.feature_b.str.contains(pattern)].sort_values('score',ascending=False)
 n=0
 for r in g.itertuples():
  concepts=[r.feature_a.split('__')[0],r.feature_b.split('__')[0]]
  if r.pair_id in used or any(counts.get(x,0)>=3 for x in concepts):continue
  z=r._asdict();z['family']=family;chosen.append(z);used.add(r.pair_id)
  for x in concepts:counts[x]=counts.get(x,0)+1
  n+=1
  if n==6:break
f=pd.DataFrame(chosen).drop(columns='Index');f['time_group']=-1;f['raw_bps']=f.gross
coarse=f.copy();coarse['resolution']=5;coarse['cell']=(coarse.cell//20)*5+(coarse.cell%10)//2
rules=pd.concat([f,coarse],ignore_index=True);rules['mechanism_id']=np.arange(len(rules));rules.to_parquet(D/'rules.parquet',index=False)
obs,t,day,days,sec,securities,closes=obs_arrays();del obs
axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);minute=t-opens[day];prices=np.load(OUT/'opens.npy',mmap_mode='r');reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m');groups=reader.read_groups('time_bucket',0,reader.rows);month=pd.to_datetime(days).strftime('%Y-%m');rows=[];ledgers=[]
for r in rules.itertuples():
 a=decode_packed_bins(reader.read_columns('bins',[r.feature_a],0,reader.rows)[:,0],r.resolution)
 if r.feature_b:
  b=decode_packed_bins(reader.read_columns('bins',[r.feature_b],0,reader.rows)[:,0],r.resolution);state=np.where((a>=0)&(b>=0),a*r.resolution+b,-1)
 else:state=a
 ix=np.flatnonzero((state==r.cell)&((r.time_group==-1)|(groups==r.time_group))&(minute>=5)&(t+1+r.horizon<=closes[day]-5));di=day[ix];si=sec[ix];mi=minute[ix];ep=prices[di,si,mi+1];xp=prices[di,si,mi+1+r.horizon];recent=np.abs(prices[di,si,mi]/prices[di,si,np.maximum(mi-5,0)]-1)
 release=t[ix]+1+r.horizon
 for extra in range(1,391):
  pending=np.flatnonzero(~np.isfinite(xp)&(release+extra<=closes[di]-5))
  if len(pending)==0:break
  value=prices[di[pending],si[pending],minute[ix[pending]]+1+r.horizon+extra];ok=np.isfinite(value);loc=pending[ok];xp[loc]=value[ok];release[loc]+=extra
 good=np.isfinite(ep);release=release[good];ix=ix[good];di=di[good];si=si[good];ep=ep[good];xp=xp[good];recent=recent[good]
 for ranking in ['neutral']:
  for slots in [1,5,10]:
   picked,_=allocate(t[ix]+1,release,si,np.ones(len(ix),bool),slots,priority=np.nan_to_num(recent,nan=-1) if ranking=='recent_move' else None)
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
