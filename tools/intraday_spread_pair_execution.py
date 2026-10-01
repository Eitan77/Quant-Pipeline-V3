"""Pair-aware quote replay: unwind unmatched entry legs at the fixed entry expiry."""
from pathlib import Path
import pandas as pd,numpy as np,json
O=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/intraday_strategy_20260928');Q=O/'spread_quote_sample';D=O/'spread_both_legs';m=pd.read_parquet(Q/'manifest.parquet');r=pd.read_parquet(D/'both_legs_replays.parquet');r['pair_index']=r['sample'].map(m.pair_index)
strategy='mechanism12_paired5';base=r[r.strategy==strategy];rows=[];missing=[];unwinds={}
for t in m[(m.strategy==strategy)&m.index.isin(base['sample'])].itertuples():
 q=pd.read_parquet(Q/f'{t.symbol}_{int(t.entry_minute)}_entry{"_asof" if t.symbol=="PARA" else ""}.parquet');deadline=int(t.entry_minute)*60_000_000_000+60_000_000_000;e=q[q.ns<=deadline].sort_values('ns',kind='stable').iloc[-1]
 assert e.bid>0 and e.ask>=e.bid and e.bs>0 and e.az>0
 unwinds[t.Index]=e.bid if t.side==1 else e.ask
for (pair,en,ex),g in base.groupby(['pair_index','entry_method','exit_method']):
 if len(g)!=2:missing.append([int(pair),en,ex]);continue
 count=int(g.entry_filled.sum());bps=0.
 if count==2:bps=g.bps.sum()/2
 elif count==1:
  leg=g[g.entry_filled].iloc[0];side=m.loc[leg['sample'],'side'];bps=side*(unwinds[leg['sample']]/leg.entry_price-1)*10000/2
 rows.append({'pair_index':pair,'day':int(g.day.iloc[0]),'entry_method':en,'exit_method':ex,'filled_legs':count,'bps':bps,'unmatched_unwind':count==1})
f=pd.DataFrame(rows);f.to_parquet(D/'paired_execution.parquet',index=False);s=f.groupby(['entry_method','exit_method']).agg(attempts=('bps','count'),bps_attempt=('bps','mean'),matched_pairs=('filled_legs',lambda v:int((v==2).sum())),unmatched_unwinds=('unmatched_unwind','sum')).reset_index();s.to_parquet(D/'paired_summary.parquet',index=False);(D/'paired_missing.json').write_text(json.dumps(missing))
print(s.sort_values('bps_attempt',ascending=False).head(5).to_string(index=False));print('market',s[(s.entry_method=='market')&(s.exit_method=='market')].to_string(index=False))
