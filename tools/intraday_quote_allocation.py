"""Capital allocation on frozen quote schedules; no new signal selection or fee overlays."""
import sys,json
from pathlib import Path
import pandas as pd,numpy as np
O=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/intraday_strategy_20260928');D=O/sys.argv[1];m=pd.read_parquet(D/'manifest.parquet');r=pd.read_parquet(D/'replays.parquet');a=json.loads((O/'price_axes.json').read_text());months=pd.to_datetime(a['days']).strftime('%Y-%m');prices=np.load(O/'opens.npy',mmap_mode='r');rows=[];ledgers=[]
m['tie']=((m.security_code.astype(np.uint64)+1)*2654435761)%4294967291
m['priority']=0.;m['volatility']=np.nan
for i,t in m.iterrows():
 di=int(t.day);si=int(t.security_code);mi=int(t.entry_minute)-a['open_minutes'][di]-1;v=prices[di,si,max(0,mi-30):mi+1];m.loc[i,'volatility']=max(float(np.nanstd(np.diff(np.log(v)))),1e-6)
for i,t in m.iterrows():
 if t.ranking=='recent_move':
  di=int(t.day);si=int(t.security_code);mi=int(t.entry_minute)-a['open_minutes'][di]-1;m.loc[i,'priority']=abs(prices[di,si,mi]/prices[di,si,max(0,mi-5)]-1)
for (strategy,method),g in r.groupby(['strategy','method']):
 g=g.copy();g['priority']=g['sample'].map(m.priority);g['tie']=g['sample'].map(m.tie);g['volatility']=g['sample'].map(m.volatility)
 for slots in [1,3,5,10]:
  for sizing in ['fixed','available','inverse_vol']:
   active=[];chosen=[];attempts=0
   for ts,group in g.sort_values(['entry_minute','priority','tie'],ascending=[True,False,True]).groupby('entry_minute',sort=False):
    active=[v for v in active if v[0]>ts];capacity=slots-len(active)
    if capacity<=0:continue
    picks=list(group.head(capacity).itertuples());free=max(0.,1-sum(v[1] for v in active));weight=min(1/slots,free/len(picks)) if sizing=='fixed' else free/len(picks)
    if weight<1e-10:continue
    weights=np.full(len(picks),weight)
    if sizing=='inverse_vol':
     inv=np.array([1/v.volatility if np.isfinite(v.volatility) else 1. for v in picks]);weights=free*inv/inv.sum()
    for t,weight in zip(picks,weights):
     attempts+=1;active.append((t.exit_minute if t.filled else ts+1,weight))
     if t.filled:chosen.append((int(t.day),float(t.bps),weight,int(t.sample)))
   for capital in [.25,.5,1.]:
    daily=np.zeros(251)
    for day,bps,weight,sample in chosen:daily[day]+=bps*weight*capital/10000
    eq=np.cumprod(1+daily);dd=(1-eq/np.maximum.accumulate(np.r_[1,eq])[1:]).max()*100;mr=pd.Series(daily).groupby(months).apply(lambda v:np.prod(1+v)-1)
    rows.append({'strategy':strategy,'method':method,'slots':slots,'sizing':sizing,'capital':capital,'attempts':attempts,'fills':len(chosen),'fills_day':len(chosen)/251,'return_pct':(eq[-1]-1)*100,'daily_dd_pct':dd,'positive_months':int((mr>0).sum()),'worst_month_pct':mr.min()*100,'first_half_bps_day':daily[:126].mean()*10000,'second_half_bps_day':daily[126:].mean()*10000,'trim5_bps_day':(daily.sum()-np.sort(daily)[-5:].sum())/251*10000})
   for day,bps,weight,sample in chosen:ledgers.append({'strategy':strategy,'method':method,'slots':slots,'sizing':sizing,'day':day,'bps':bps,'weight':weight,'sample':sample})
s=pd.DataFrame(rows);s.to_parquet(D/'allocation_results.parquet',index=False);pd.DataFrame(ledgers).to_parquet(D/'allocation_trades.parquet',index=False);print('coverage',r['sample'].nunique(),len(m));print(s[(s.capital==1)&s.method.isin(['market','0'])].to_string(index=False))
