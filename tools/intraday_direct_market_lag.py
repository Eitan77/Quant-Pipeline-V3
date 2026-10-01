"""Direct beta-adjusted market lag/overshoot; trailing beta and fixed thresholds."""
import json
import numpy as np,pandas as pd,torch
from intraday_strategy_search import ROOT,OUT,COSTS,obs_arrays
from intraday_entry_search import allocate
D=OUT/'direct_market_lag';D.mkdir(exist_ok=True);torch.set_num_threads(4)
obs,t,day,days,sec,securities,closes=obs_arrays();del obs
axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);minute=t-opens[day];prices=np.load(OUT/'opens.npy',mmap_mode='r');month=pd.to_datetime(days).strftime('%Y-%m')
spy=list(securities).index('b28f4066-5c6d-479b-a2af-85dc1a8f16fb');qqq=list(securities).index('2d9e926c-e17c-47c3-ad8c-26c7a594e48f')
p=torch.tensor(np.asarray(prices),device='cuda',dtype=torch.float64)
v=p[:,:,5::5]/p[:,:,:-5:5]-1;market=v[:,spy:spy+1,:];good=torch.isfinite(v)&torch.isfinite(market)
x=torch.where(good,market,0);y=torch.where(good,v,0)
stats=torch.stack([good.sum(2),x.sum(2),y.sum(2),(x*x).sum(2),(x*y).sum(2)])
cs=torch.cat([torch.zeros_like(stats[:,:1,:]),stats.cumsum(1)],dim=1)
end=torch.arange(len(days),device='cuda');begin=(end-20).clamp(min=0);n,sx,sy,sxx,sxy=(cs[:,end,:]-cs[:,begin,:])
beta=((sxy-sx*sy/n)/(sxx-sx*sx/n)).clamp(0,3);beta[(n<100)|(end[:,None]<20)]=torch.nan
np.save(D/'trailing_beta.npy',beta.cpu().numpy())
di=torch.tensor(day,device='cuda',dtype=torch.long);si=torch.tensor(sec,device='cuda',dtype=torch.long);mi=torch.tensor(np.clip(minute,0,389),device='cuda',dtype=torch.long)
rows=[];ledgers=[];rules=[];ident=0
for lookback in [5,15]:
 stock=(p[di,si,mi]/p[di,si,(mi-lookback).clamp(min=0)]-1)*10000
 market_move=(p[di,spy,mi]/p[di,spy,(mi-lookback).clamp(min=0)]-1)*10000
 residual=stock-beta[di,si]*market_move
 direction=torch.sign(market_move);signed=residual*direction
 for mechanism in ['lag','overshoot']:
  for threshold in [5,10]:
   mask=(market_move.abs()>=threshold)&(signed<-5 if mechanism=='lag' else signed>5)&(mi>=lookback)&(si!=spy)&(si!=qqq)&torch.isfinite(residual)
   candidates=torch.nonzero(mask).flatten().cpu().numpy();sides=(direction if mechanism=='lag' else -direction).cpu().numpy()
   for hold in [2,5,15]:
    ident+=1;rules.append({'mechanism_id':ident,'mechanism':mechanism,'lookback':lookback,'market_threshold_bps':threshold,'residual_threshold_bps':5,'horizon':hold})
    ix=candidates[t[candidates]+1+hold<=closes[day[candidates]]-5];dd=day[ix];ss=sec[ix];mm=minute[ix]
    ep=prices[dd,ss,mm+1];release=t[ix]+1+hold;xp=prices[dd,ss,mm+1+hold].copy()
    for extra in range(1,391):
     pending=np.flatnonzero(~np.isfinite(xp)&(t[ix]+1+hold+extra<=closes[dd]-5))
     if not len(pending):break
     value=prices[dd[pending],ss[pending],mm[pending]+1+hold+extra];ok=np.isfinite(value);loc=pending[ok];xp[loc]=value[ok];release[loc]=t[ix[loc]]+1+hold+extra
    valid=np.isfinite(ep);ix=ix[valid];ep=ep[valid];xp=xp[valid];release=release[valid]
    for slots in [1,5,10]:
     ranking='neutral';picked,_=allocate(t[ix]+1,release,sec[ix],np.ones(len(ix),bool),slots)
     gross=sides[ix[picked]]*(xp[picked]/ep[picked]-1)*10000;dd=day[ix[picked]]
     if len(gross)<100 or not np.isfinite(gross).all():continue
     ledgers.append(pd.DataFrame({'mechanism_id':ident,'ranking':ranking,'slots':slots,'observation_id':ix[picked],'day':dd,'security_code':sec[ix[picked]],'entry_minute':t[ix[picked]]+1,'exit_minute':release[picked],'gross_bps':gross,'side':sides[ix[picked]]}))
     for capital in [.25,.5,1.]:
      for cost in COSTS:
       # Each slot gets capital/slots of day-start equity, not independently compounded equity.
       daily=np.bincount(dd,weights=(gross-2*cost)*capital/slots/10000,minlength=len(days));eq=np.cumprod(1+daily);monthly=pd.Series(daily).groupby(month).apply(lambda v:np.prod(1+v)-1);peak=np.maximum.accumulate(np.r_[1,eq])[1:]
       rows.append({'mechanism_id':ident,'ranking':ranking,'slots':slots,'capital':capital,'cost':cost,'gross_bps':float(gross.mean()),'trades':len(gross),'trades_day':len(gross)/len(days),'return_pct':(eq[-1]-1)*100,'daily_dd_pct':(1-eq/peak).max()*100,'positive_months':int((monthly>0).sum()),'worst_month_pct':monthly.min()*100,'median_month_pct':monthly.median()*100,'bps_day':daily.mean()*10000,'first_half_bps':daily[:126].mean()*10000,'second_half_bps':daily[126:].mean()*10000,'trim5_bps_day':(daily.sum()-np.sort(daily)[-5:].sum())/len(days)*10000})
    print('RULE',ident,'TRADES',len(ix),flush=True)
pd.DataFrame(rules).to_parquet(D/'rules.parquet',index=False);pd.DataFrame(rows).to_parquet(D/'results.parquet',index=False);pd.concat(ledgers,ignore_index=True).to_parquet(D/'trades.parquet',index=False)
s=pd.DataFrame(rows);print(s[(s.cost==0)&(s.capital==1)&(s.slots==5)].sort_values(['positive_months','trim5_bps_day'],ascending=False).head(8).to_string(index=False))

