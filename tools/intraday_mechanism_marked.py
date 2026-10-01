"""Minute-open marked sensitivity for five-slot midpoint portfolio, quote-priced endpoints."""
from pathlib import Path
import json,pandas as pd,numpy as np
O=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/intraday_strategy_20260928');D=O/'mechanism_quote_full';m=pd.read_parquet(D/'manifest.parquet');r=pd.read_parquet(D/'replays.parquet');r=r[(r.method=='0')&r.filled];a=json.loads((O/'price_axes.json').read_text());p=np.load(O/'opens.npy',mmap_mode='r');curves=np.zeros((251,391));missing_marks=0
for t in r.itertuples():
 z=m.iloc[t.sample];di=int(z.day);si=int(z.security_code);path=D/f'{z.symbol}_{int(z.entry_minute)}_entry{"_asof" if z.symbol=="PARA" else ""}.parquet';q=pd.read_parquet(path);e=q[q.ns<=int(z.entry_minute)*60_000_000_000].iloc[-1];limit=np.ceil(((e.bid+e.ask)/2-1e-10)*100)/100;ep=e.bid if limit<=e.bid else limit
 start=int(np.ceil(z.entry_minute-a['open_minutes'][di]+t.wait_seconds/60));end=int(z.exit_minute-a['open_minutes'][di]);prices=p[di,si,start:end];missing_marks+=int(np.isnan(prices).sum());prices=pd.Series(prices).ffill().fillna(ep).to_numpy();curves[di,start:end]+=(1-prices/ep)/5;curves[di,end:]+=t.bps/50000
base=1.;peak=1.;maxdd=0
for c in curves:
 eq=base*(1+c);peaks=np.maximum.accumulate(np.r_[peak,eq])[1:];maxdd=max(maxdd,float((1-eq/peaks).max()));peak=max(peak,float(eq.max()));base=float(eq[-1])
result={'portfolio':'five slots, midpoint,100pct capital','minute_open_marked_dd_pct':maxdd*100,'return_pct':(base-1)*100,'missing_minute_marks_forward_carried':missing_marks,'limitations':'Minute opens are not liquidation bid/ask and omit intraminute extrema; pending-orders omitted from P&L but reserved in original fixed schedule.'};(D/'minute_marked.json').write_text(json.dumps(result,indent=2));print(result)
