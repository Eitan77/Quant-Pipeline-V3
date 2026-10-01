import json
import numpy as np,pandas as pd
from intraday_strategy_search import ROOT,OUT,COSTS,obs_arrays
from intraday_entry_search import allocate
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
D=OUT/'spread_replay';D.mkdir(exist_ok=True)
f=pd.read_parquet(OUT/'spread_edge_shortlist.parquet');f['resolution']=5;f['time_group']=-1
z=pd.read_parquet(OUT/'spread_long_shortlist.parquet');z['long_cell']=z.cell;z['short_cell']=-2;z['mechanism_id']=np.arange(len(z))+len(f)
coarse=z.copy();coarse['mechanism_id']+=len(z);coarse['long_cell']=np.where(coarse.feature_b!='',(coarse.long_cell//20)*5+(coarse.long_cell%10)//2,coarse.long_cell//2);coarse['resolution']=5
rules=pd.concat([f,z,coarse],ignore_index=True);rules.to_parquet(D/'rules.parquet',index=False)
obs,t,day,days,sec,securities,closes=obs_arrays();del obs
axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);minute=t-opens[day];prices=np.load(OUT/'opens.npy',mmap_mode='r');month=pd.to_datetime(days).strftime('%Y-%m');reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m');groups=reader.read_groups('time_bucket',0,reader.rows)
for meta in (ROOT/'cache/features/intraday_5m').glob('*.json'):
 info=json.loads(meta.read_text());columns=info.get('columns',[])
 if 'dollar_volume__30m__raw__intraday_5m' in columns:liquidity=np.load(meta.with_suffix('.npy'),mmap_mode='r')[:,columns.index('dollar_volume__30m__raw__intraday_5m')];break
rows=[];ledgers=[];coverage=[]
for r in rules.itertuples():
 a=decode_packed_bins(reader.read_columns('bins',[r.feature_a],0,reader.rows)[:,0],r.resolution)
 if r.feature_b:
  b=decode_packed_bins(reader.read_columns('bins',[r.feature_b],0,reader.rows)[:,0],r.resolution);state=np.where((a>=0)&(b>=0),a*r.resolution+b,-1)
 else:state=a
 eligible=(minute>=5)&(t+1+r.horizon<=closes[day]-5)&((groups==r.time_group)|(r.time_group==-1))
 ix=np.flatnonzero(eligible&((state==r.long_cell)|(state==r.short_cell)));di=day[ix];si=sec[ix];mi=minute[ix];ep=prices[di,si,mi+1];xp=prices[di,si,mi+1+r.horizon].copy();release=t[ix]+1+r.horizon
 for extra in range(1,391):
  pending=np.flatnonzero(~np.isfinite(xp)&(t[ix]+1+r.horizon+extra<=closes[di]-5))
  if not len(pending):break
  val=prices[di[pending],si[pending],mi[pending]+1+r.horizon+extra];ok=np.isfinite(val);loc=pending[ok];xp[loc]=val[ok];release[loc]=t[ix[loc]]+1+r.horizon+extra
 valid=np.isfinite(ep);ix=ix[valid];ep=ep[valid];xp=xp[valid];release=release[valid];side=np.where(state[ix]==r.long_cell,1,-1);priority=np.nan_to_num(liquidity[ix],nan=-1);clock=t[ix]+1
 for mode in ['long','paired']:
  for slots in [1,5]:
   if mode=='long':
    loc=np.flatnonzero(side==1);picked,_=allocate(clock[loc],release[loc],sec[ix[loc]],np.ones(len(loc),bool),slots,priority=priority[loc]);picked=loc[picked];pair_ids=np.arange(len(picked));denom=slots
   else:
    order=np.lexsort((sec[ix],-priority,clock));cl=clock[order];starts=np.r_[0,np.flatnonzero(np.diff(cl))+1,len(cl)];free=np.full(slots,-1);active=np.full(len(securities),-1);chosen=[];pair_ids=[];counter=0
    for start,end in zip(starts[:-1],starts[1:]):
     now=cl[start];available=np.flatnonzero(free<=now)
     if not len(available):continue
     loc=order[start:end];loc=loc[active[sec[ix[loc]]]<=now];longs=loc[side[loc]==1];shorts=loc[side[loc]==-1]
     for slot,lo,sh in zip(available,longs,shorts):
      chosen.extend([lo,sh]);pair_ids.extend([counter,counter]);counter+=1;release_pair=max(release[lo],release[sh]);free[slot]=release_pair;active[sec[ix[[lo,sh]]]]=release_pair
    picked=np.asarray(chosen,dtype=int);pair_ids=np.asarray(pair_ids);denom=2*slots
   coverage.append({'mechanism_id':r.mechanism_id,'mode':mode,'slots':slots,'legs':len(picked),'missing_exit_legs':int((~np.isfinite(xp[picked])).sum())})
   if len(picked)<100 or not np.isfinite(xp[picked]).all():continue
   gross=side[picked]*(xp[picked]/ep[picked]-1)*10000;dd=day[ix[picked]]
   ledgers.append(pd.DataFrame({'mechanism_id':r.mechanism_id,'ranking':mode,'slots':slots,'pair_index':pair_ids,'observation_id':ix[picked],'day':dd,'security_code':sec[ix[picked]],'entry_minute':clock[picked],'exit_minute':release[picked],'gross_bps':gross,'side':side[picked],'weight':1/denom}))
   for cost in COSTS:
    daily=np.bincount(dd,weights=(gross-2*cost)/denom/10000,minlength=len(days));eq=np.cumprod(1+daily);monthly=pd.Series(daily).groupby(month).apply(lambda v:np.prod(1+v)-1);peak=np.maximum.accumulate(np.r_[1,eq])[1:]
    rows.append({'mechanism_id':r.mechanism_id,'mode':mode,'slots':slots,'cost':cost,'gross_bps':gross.mean(),'legs':len(gross),'trades_day':len(gross)/len(days)/(2 if mode=='paired' else 1),'return_pct':(eq[-1]-1)*100,'daily_dd_pct':(1-eq/peak).max()*100,'positive_months':int((monthly>0).sum()),'first_half_bps':daily[:126].mean()*10000,'second_half_bps':daily[126:].mean()*10000,'trim5_bps_day':(daily.sum()-np.sort(daily)[-5:].sum())/len(days)*10000})
 print('EDGE',r.mechanism_id,'DONE',flush=True)
pd.DataFrame(rows).to_parquet(D/'results.parquet',index=False);pd.concat(ledgers,ignore_index=True).to_parquet(D/'trades.parquet',index=False);pd.DataFrame(coverage).to_parquet(D/'coverage.parquet',index=False)
s=pd.DataFrame(rows);print(s[s.cost==0].sort_values(['positive_months','trim5_bps_day'],ascending=False).head(12).to_string(index=False))
