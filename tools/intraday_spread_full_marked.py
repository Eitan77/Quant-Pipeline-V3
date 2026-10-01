import json,numpy as np,pandas as pd
from pathlib import Path
O=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/intraday_strategy_20260928');D=O/'spread_full_both_legs';a=json.loads((O/'price_axes.json').read_text());prices=np.load(O/'opens.npy',mmap_mode='r');s=pd.read_parquet(D/'portfolio_summary.parquet');tr=pd.read_parquet(D/'portfolio_trades.parquet');times=np.concatenate([np.arange(o,c-4)*60 for o,c in zip(a['open_minutes'],a['close_minutes'])]);rows=[];monthly=[]
selected=s[(s.entry_method=='market')&(s.exit_method=='market') | (s.strategy.str.contains('12_')&(s.entry_method=='market')&(s.exit_method=='2')) | (s.strategy.str.contains('19_')&(s.entry_method=='-1')&(s.exit_method=='5'))]
for conf in selected.itertuples():
 g=tr[(tr.strategy==conf.strategy)&(tr.entry_method==conf.entry_method)&(tr.exit_method==conf.exit_method)&(tr.sizing==conf.sizing)];realized=np.zeros(len(times)+1);unrealized=np.zeros(len(times));missing=0
 for t in g.itertuples():
  start=np.searchsorted(times,t.entry_time,side='left');end=np.searchsorted(times,t.exit_time,side='left');realized[end]+=t.pnl
  if end>start:
   minutes=(times[start:end]//60-a['open_minutes'][t.day]).astype(int);px=prices[t.day,t.security_code,minutes].copy();missing+=int((~np.isfinite(px)).sum());px=pd.Series(px).ffill().fillna(t.entry_price).to_numpy();unrealized[start:end]+=t.principal*(px/t.entry_price-1)
 equity=1+np.cumsum(realized)[:-1]+unrealized;peak=np.maximum.accumulate(np.r_[1,equity])[1:];dd=(1-equity/peak).max()*100
 assert abs((1+realized.sum()-1)*100-conf.return_pct)<1e-7
 rows.append({'strategy':conf.strategy,'entry_method':conf.entry_method,'exit_method':conf.exit_method,'sizing':conf.sizing,'minute_open_marked_dd_pct':dd,'missing_marks_forward_filled':missing})
 daily=g.groupby('day').pnl.sum().reindex(range(len(a['days'])),fill_value=0);eq=1+daily.cumsum();rets=eq/np.r_[1,eq.to_numpy()[:-1]]-1
 for month,z in pd.Series(rets.to_numpy(),index=pd.to_datetime(a['days'])).groupby(lambda d:d.strftime('%Y-%m')):monthly.append({'strategy':conf.strategy,'entry_method':conf.entry_method,'exit_method':conf.exit_method,'sizing':conf.sizing,'month':month,'return_pct':(np.prod(1+z)-1)*100})
pd.DataFrame(rows).to_parquet(D/'marked_drawdowns.parquet',index=False);pd.DataFrame(monthly).to_parquet(D/'portfolio_months.parquet',index=False);print(pd.DataFrame(rows).to_string(index=False))
