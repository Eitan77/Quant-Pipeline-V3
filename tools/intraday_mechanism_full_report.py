import json,numpy as np,pandas as pd
from pathlib import Path
O=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/intraday_strategy_20260928');D=O/'mechanism_quote_full';m=pd.read_parquet(D/'manifest.parquet');r=pd.read_parquet(D/'replays.parquet');a=json.loads((O/'price_axes.json').read_text());months=pd.to_datetime(a['days']).strftime('%Y-%m');rows=[];dailyrows=[]
for method,g in r.groupby('method'):
 g=g.copy();g['security_code']=g['sample'].map(m.security_code);g['tie']=((g.security_code.astype(np.uint64)+1)*2654435761)%4294967291
 for slots in [1,3,5]:
  free=np.full(slots,-1.);chosen=[];attempts=0
  for t in g.sort_values(['entry_minute','tie']).itertuples():
   slot=free.argmin()
   if t.entry_minute<free[slot]:continue
   attempts+=1;free[slot]=t.exit_minute if t.filled else t.entry_minute+1
   if t.filled:chosen.append(t)
  for capital in [.25,.5,1.]:
   daily=np.zeros(251)
   for t in chosen:daily[int(t.day)]+=t.bps*capital/slots/10000
   equity=np.cumprod(1+daily);dd=(1-equity/np.maximum.accumulate(np.r_[1,equity])[1:]).max()*100;monthret=pd.Series(daily).groupby(months).apply(lambda v:np.prod(1+v)-1)
   rows.append({'method':method,'slots':slots,'capital':capital,'attempts':attempts,'fills':len(chosen),'fills_day':len(chosen)/251,'return_pct':(equity[-1]-1)*100,'daily_dd_pct':dd,'positive_months':int((monthret>0).sum()),'worst_month_pct':monthret.min()*100,'first_half_bps_day':daily[:126].mean()*10000,'second_half_bps_day':daily[126:].mean()*10000,'trim5_bps_day':(daily.sum()-np.sort(daily)[-5:].sum())/251*10000})
   for d,v in enumerate(daily):dailyrows.append({'method':method,'slots':slots,'capital':capital,'day':d,'return':v})
s=pd.DataFrame(rows);s.to_parquet(D/'portfolio_results.parquet',index=False);pd.DataFrame(dailyrows).to_parquet(D/'portfolio_daily.parquet',index=False);print(s[(s.capital==1)&(s.slots==5)].to_string(index=False));print('ALLOCATION MIDPOINT');print(s[s.method=='0'].to_string(index=False))
lines=['# Late-session mechanism: full quote schedule','',f'{len(m)} scheduled orders;{r["sample"].nunique()} with quote states. No added hypothetical costs/rebates. Entry/exit quotes are historical as-of states; passive fill requires strict move-through within60seconds. This is not queue-confirmed execution or capital-sized depth validation.','', 'Signal: spread-proxy top decile and information-discreteness bottom decile, short during the final-hour bucket,30minute scheduled hold, mandatory close-minus-five-minute exit. These are price-path conditions; the estimated spread feature is not the actual NBBO spread. Neutral deterministic ranking; at most five original slots. One and three slots restrict that same fixed candidate schedule by the same causal hash ranking. Missed fills reserve a slot for60seconds; newly freed capital does not regenerate suppressed signals.25/50/100%total capital is divided equally across slots using day-start equity.','', '| Entry offset | Slots | Capital | Fills/day | Return | Daily-close DD | Positive months | Worst month |','|---|---:|---:|---:|---:|---:|---:|---:|']
for t in s.itertuples():lines.append(f'| {t.method} | {t.slots} | {t.capital:.0%} | {t.fills_day:.2f} | {t.return_pct:.2f}% | {t.daily_dd_pct:.2f}% | {t.positive_months}/12 | {t.worst_month_pct:.2f}% |')
lines+=['','The discovery sample selected this mechanism. Full-year discovery confirms or rejects that lead but is not OOS evidence. Daily-close DD does not bound intraday drawdown. Lower capital reduces both gain and loss; it cannot turn a negative month positive. Adjacent-offset stability matters more than one best cell. Features passed six prefix-only checks. May2026+ untouched.','', 'Artifacts:mechanism_quote_full/{manifest,replays,portfolio_results,portfolio_daily}.parquet;missing.json. Reproduce with intraday_mechanism_quotes.py --mechanism-full and intraday_mechanism_full_report.py.']
Path('docs/research/V3_MECHANISM_FULL_QUOTES_2026-09-28.md').write_text('\n'.join(lines)+'\n')
