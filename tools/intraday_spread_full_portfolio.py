"""Cash-reserved sequential portfolio replay of all quote-covered scheduled orders."""
import json,heapq
from pathlib import Path
import numpy as np,pandas as pd
from intraday_strategy_search import ROOT,OUT
O=OUT;D=O/'spread_full_both_legs';Q=O/'spread_quote_full';a=json.loads((O/'price_axes.json').read_text());days=pd.to_datetime(a['days']);months=days.strftime('%Y-%m');m=pd.read_parquet(Q/'manifest.parquet');base=pd.read_parquet(Q/'replays.parquet');r=pd.read_parquet(D/'both_legs_replays.parquet');wait=base.set_index(['sample','method']).wait_seconds
for meta in (ROOT/'cache/features/intraday_5m').glob('*.json'):
 info=json.loads(meta.read_text());cols=info.get('columns',[])
 if 'dollar_volume__30m__raw__intraday_5m' in cols:liq=np.load(meta.with_suffix('.npy'),mmap_mode='r')[:,cols.index('dollar_volume__30m__raw__intraday_5m')];break
m['liquidity']=np.nan_to_num(liq[m.observation_id.to_numpy()],nan=-1)
rows=[];ledgers=[]
for (strategy,en,ex),g in r.groupby(['strategy','entry_method','exit_method']):
 slots=1 if strategy.endswith('long1') else 5
 for sizing in ['fixed','available']:
  cash=1.;queue=[];serial=0;equity=[];pending=[];day_start=1.;previous=0;skipped=0
  for day in range(len(days)):
   while queue:
    _,_,principal,pnl=heapq.heappop(queue);cash+=principal+pnl
   day_start=cash;gd=g[g.day==day].copy();gd['submit']=gd['sample'].map(m.entry_minute)*60;gd['liquidity']=gd['sample'].map(m.liquidity)
   for now,block in gd.sort_values(['submit','liquidity','sample'],ascending=[True,False,True]).groupby('submit',sort=True):
    while queue and queue[0][0]<=now:
     _,_,principal,pnl=heapq.heappop(queue);cash+=principal+pnl
    available=slots-len(queue);block=block.iloc[:max(available,0)];skipped+=int((gd.submit==now).sum())-len(block)
    if not len(block):continue
    amount=cash/len(block) if sizing=='available' else min(day_start/slots,cash/len(block))
    for b in block.itertuples():
     if amount<=0:continue
     t=m.loc[b.sample];filled=bool(b.entry_filled);entry_time=now+wait.loc[(b.sample,en)];exit_time=int(t.exit_minute)*60+b.exit_wait_seconds if filled else now+60;pnl=amount*b.bps/10000 if filled else 0.
     cash-=amount;serial+=1;heapq.heappush(queue,(exit_time,serial,amount,pnl))
     if filled:pending.append({'strategy':strategy,'entry_method':en,'exit_method':ex,'sizing':sizing,'sample':b.sample,'day':day,'security_code':int(t.security_code),'entry_time':entry_time,'exit_time':exit_time,'entry_price':b.entry_price,'principal':amount,'pnl':pnl})
   while queue:
    _,_,principal,pnl=heapq.heappop(queue);cash+=principal+pnl
   equity.append(cash)
  eq=np.asarray(equity);daily=eq/np.r_[1,eq[:-1]]-1;monthly=pd.Series(daily).groupby(months).apply(lambda z:np.prod(1+z)-1);peak=np.maximum.accumulate(np.r_[1,eq])[1:]
  rows.append({'strategy':strategy,'entry_method':en,'exit_method':ex,'sizing':sizing,'trades':len(pending),'trades_day':len(pending)/len(days),'return_pct':(eq[-1]-1)*100,'daily_dd_pct':(1-eq/peak).max()*100,'positive_months':int((monthly>0).sum()),'worst_month_pct':monthly.min()*100,'trim5_bps_day':(daily.sum()-np.sort(daily)[-5:].sum())/len(days)*10000,'skipped_conflicts':skipped})
  ledgers.extend(pending)
s=pd.DataFrame(rows);s.to_parquet(D/'portfolio_summary.parquet',index=False);pd.DataFrame(ledgers).to_parquet(D/'portfolio_trades.parquet',index=False)
print('MARKET',s[(s.entry_method=='market')&(s.exit_method=='market')].to_string(index=False));print('BEST',s.sort_values('return_pct',ascending=False).groupby(['strategy','sizing'],sort=False).head(1).to_string(index=False))
