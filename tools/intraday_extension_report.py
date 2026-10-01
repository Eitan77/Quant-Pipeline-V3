import json
from pathlib import Path
import numpy as np
import pandas as pd
from intraday_strategy_search import OUT,COSTS,obs_arrays
from intraday_entry_search import DEST

def main():
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    price=np.load(OUT/'opens.npy',mmap_mode='r');axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes'])
    top=pd.read_parquet(DEST/'topone_trades.parquet');conf=pd.read_parquet(DEST/'confirmation_trades.parquet');seq=pd.read_parquet(DEST/'sequential_trades.parquet')
    models={'Top-one 240m':top[top.id==1], 'Top-one plus reversal':seq[seq.portfolio=='core_plus_reversal'],
        '10m acceleration-confirmed':conf[conf.confirmation_id==302], '5m high-frequency':conf[conf.confirmation_id==1004],
        '15m fresh-cross':conf[conf.confirmation_id==840], 'Core + reversal + 10m':seq[seq.portfolio=='core_reversal_fast']}
    rows=[];diag=[]
    for name,frame in models.items():
        f=frame.sort_values('entry_minute').copy()
        assert (f.entry_minute.to_numpy()[1:]>=f.exit_minute.to_numpy()[:-1]).all()
        assert (f.exit_minute.to_numpy()<=closes[f.day.to_numpy()]-5).all()
        gross=f.gross_bps.to_numpy();d=f.day.to_numpy();record={'strategy':name,'trades':len(f),'trades_day':len(f)/251,
            'gross_bps':float(gross.mean()),'active_days':len(np.unique(d))}
        for c in COSTS:
            net=(gross-2*c)/10000
            daily=np.expm1(np.bincount(d,weights=np.log1p(net),minlength=251))
            equity=np.cumprod(1+daily);peak=np.maximum.accumulate(np.r_[1,equity])[1:]
            record.update({f'return_c{c}':float((equity[-1]-1)*100),f'sharpe_c{c}':float(daily.mean()/daily.std(ddof=1)*np.sqrt(252)),
                f'dd_c{c}':float((1-equity/peak).max()*100)})
            if c==1:
                weekly=np.array([daily[i:i+5].sum() for i in range(0,len(daily),5)])
                rng=np.random.default_rng(20260928);boot=rng.choice(weekly,(2000,len(weekly)),replace=True).mean(axis=1)/5*10000
                di={'strategy':name,'mean_daily_bps_bootstrap_95':np.quantile(boot,[.025,.975]).tolist(),
                    'positive_months':int((pd.Series(daily,index=days).groupby(days.strftime('%Y-%m')).apply(lambda x:np.prod(1+x)-1)>0).sum()),
                    'first_half_gross':float(gross[d<126].mean()),'second_half_gross':float(gross[d>=126].mean()),
                    'best5_net_profit_share':float(np.sort(gross-2)[-5:].sum()/(gross-2).sum())}
                # Intraday mark-to-market drawdown on available one-minute opens, one full-equity short at a time.
                current=1.;peak=1.;maxdd=0.
                for tr in f.itertuples():
                    start=int(tr.entry_minute-opens[tr.day]);end=int(tr.exit_minute-opens[tr.day]);p0=price[tr.day,tr.security_code,start]
                    path=price[tr.day,tr.security_code,start:end+1];marked=current*(1+(1-path/p0)-.0001)
                    marked=marked[np.isfinite(marked)]
                    if len(marked):
                        peaks=np.maximum.accumulate(np.r_[peak,marked])[1:];maxdd=max(maxdd,float((1-marked/peaks).max()));peak=max(peak,float(marked.max()))
                    current*=1+(tr.gross_bps-2)/10000;peak=max(peak,current);maxdd=max(maxdd,1-current/peak)
                di['one_minute_open_mtm_dd_c1_pct']=maxdd*100
                diag.append(di)
        rows.append(record)
    results=pd.DataFrame(rows);results.to_parquet(DEST/'full_equity_results.parquet',index=False)
    (DEST/'full_equity_diagnostics.json').write_text(json.dumps(diag,indent=2))
    lines=['# V3 selective-entry and top-one extension','',
        '**Best positive-cost candidate:** top-one opening short plus a selective reversal backup. About 59% discovery profit at 1 bp/side; inspect the exact recomputed table below. The high-frequency alternatives are attractive only under cheaper cost assumptions. No May 2026+ data was accessed.','',
        'All rows below use one position at a time, 100% current equity notional, compounded after every completed trade. Five-minute-before-close hard cutoff; no overnight positions. Returns are modeled raw-open returns under the specified per-side friction.','',
        '| Strategy | Trades/day | -1 bp | 0 bp | 1 bp | 2 bps | 3 bps | 4 bps | 5 bps |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:lines.append('|'+r['strategy']+f'|{r["trades_day"]:.2f}|'+ '|'.join(f'{r[f"return_c{c}"]:.2f}%' for c in COSTS)+'|')
    lines+=['','## Rules and selection','',
        '- Top-one 240m: R00530, opening-hour breakdown-distance bottom 5% and acceleration-halves top 10%. At the first eligible decision while flat, choose the highest acceleration-halves percentile; submit after the decision and enter the next-minute raw open. Hold 240 minutes. At most one full-equity short. No return-based ticker whitelist.',
        '- Reversal backup: C0412, acceleration-halves r10 bin 8 and acceleration-thirds bin 1, 60-minute hold, with a positive preceding five-minute price move before shorting. At simultaneous timestamps the 240m engine has priority. The combined model consumes signals from two independent virtual engines; each engine advances its own hypothetical position schedule even when the shared portfolio rejects its trade. This explicit scheduling restriction is part of the candidate, not a sum of standalone P&Ls.',
        '- 10m acceleration-confirmed: C0210 all-day state, market-beta rank in top decile and positive-jump-fraction rank in [70%,80%), plus acceleration-halves rank >=90%; short, 10-minute hold. Select the largest absolute preceding-five-minute move at competing timestamps. One full-equity position.',
        '- 5m high-frequency: C0490 expanded all day, market-beta top decile and positive-jump-fraction rank in [30%,40%); short, 5-minute hold, same causal tie ranking. Reentry only after prior exit.',
        '- 15m fresh-cross: C0410, p95-subreturn bottom decile and Parkinson-volatility rank in [80%,90%), fresh state entry versus the exact prior five-minute observation. Short for 15 minutes; same causal tie ranking.','',
        'Cross-sectional ranks use V3 average-tie rules and PIT eligible observations. Market-derived rank labels can have large tie masses, so these are exact bin predicates, not necessarily economic thresholds on SPY itself.','',
        '## Evidence and fragility','',
        'Completed 11,739 entry/holding/time/capital variants across 41 non-EMA states, 1,015 confirmation variants, and 180 top-one variants. Confirmation families included fresh state entry, persistence, recent price agreement/disagreement, turns, volatility, acceleration, and joint filters. The earlier broken EMA feature remains excluded.',
        'The 45-trades/day five-minute rule earns only 0.399 gross bps/trade. Adding one minute of entry delay reduces that to 0.056 bps. Its spectacular rebate scenario is chiefly rebate arithmetic; it is not evidence those executions receive rebates. The ten-minute acceleration-confirmed rule averages 1.38 gross bps/trade, versus 1.78 with one extra minute of delay, and is positive in both discovery halves. It loses at 1 bp/side.',
        'The 240m top-one rule averages 23.25 gross bps/trade, 12.36 in the first half and 33.96 in the second. Its best five trades account for about 70% of net additive profit; removing them still leaves positive aggregate profit. This is substantial tail concentration, not smooth daily income.',
        'The 15m fresh-cross rule stays positive at 1 bp/side after one- and two-minute entry delays, but has fewer than one trade per session and stronger second-half returns.','',
        '## Risk and uncertainty at 1 bp/side','',
        '| Strategy | Daily Sharpe | Daily max DD | One-minute-open MTM DD | Positive months |','|---|---:|---:|---:|---:|']
    for r,d in zip(rows,diag):lines.append(f'|{r["strategy"]}|{r["sharpe_c1"]:.2f}|{r["dd_c1"]:.2f}%|{d["one_minute_open_mtm_dd_c1_pct"]:.2f}%|{d["positive_months"]}/12|')
    lines+=['','Five-day-block bootstrap intervals are saved in full_equity_diagnostics.json. They describe discovery uncertainty and do not correct for selecting winners from thousands of trials. One-minute-open marking cannot capture intraminute extremes.','',
        '## Limit-entry findings','',
        'Tested 2/5/10/20 bp favorable entry offsets with five-minute expiry. Orders anchor to an observed next-minute open, then may fill only at a subsequent sampled open crossing the limit; fills are priced at the limit. Pending and expired orders reserve both capital and the security. The proxy has no queue, quote spread, or partial-fill model. It is therefore hypothetical, not quote-executable P&L.',
        'Passive offsets generally reduced throughput and did not beat the best immediate-entry top-one rule. A fresh/high-volatility filtered C0401 2-bp-offset variant improved versus its parent, but remains a proxy and did not displace the main candidate.','',
        '## Decision','',
        'Freeze the top-one 240m candidate and its reversal backup for later OOS testing; retain the 10m acceleration-confirmed rule for genuinely zero/rebated execution. Prefer the earlier 10-slot diversified portfolio if the top-one concentration is unacceptable. No strategy here is yet proven out of sample.',
        '',f'Artifacts: `{DEST}`. Scripts: tools/intraday_entry_search.py, tools/intraday_confirmation_search.py, tools/intraday_topone.py, tools/intraday_extension_report.py.']
    report=Path(__file__).resolve().parents[1]/'docs/research/V3_TOP_ONE_AND_CONFIRMATIONS_2026-09-28.md'
    report.write_text('\n'.join(lines)+'\n',encoding='utf-8');(DEST/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(results[['strategy','trades_day','return_c-1','return_c0','return_c1','return_c5','sharpe_c1','dd_c1']].round(3).to_string(index=False));print(json.dumps(diag,indent=2))

if __name__=='__main__':main()
