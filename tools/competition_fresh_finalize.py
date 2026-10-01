"""Freeze the fresh discovery candidate and a compact, reproducible evidence record."""
import contextlib,hashlib,io,json
from pathlib import Path
import numpy as np,pandas as pd,exchange_calendars as xc
import competition_fresh_quotes as quotes
import competition_fresh_risk as risk
from competition_fresh_search import OUT
from competition_under2d import ROOT

PAIR='a2cfbdd1248d9ad6c2d1d20a'
DEST=OUT/'close_entry_comparison'

def selected(name,folder=DEST):
    f=pd.read_parquet(folder/name)
    return f[(f.slots==10)&f.ranked].copy()

def table(f,columns):
    head='| '+' | '.join(columns)+' |\n| '+' | '.join(['---']*len(columns))+' |\n'
    return head+'\n'.join('| '+' | '.join(f'{v:.3f}' if isinstance(v,(float,np.floating)) else str(v) for v in row)+' |' for row in f[columns].itertuples(index=False,name=None))

def main():
    pool=pd.read_parquet(DEST/'policy_quote_pool.parquet')
    result=selected('policy_risk_summary.parquet');summary=selected('policy_quote_summary.parquet')
    stress=selected('policy_risk_summary.parquet',OUT/'close_entry_conservative')
    trades=selected('policy_funded_trades.parquet');working=trades[trades.bps==1].copy()
    attempts=selected('policy_quote_attempts.parquet');months=selected('policy_monthly.parquet')
    assert len(result)==7 and attempts.priced.all() and np.isfinite(trades.net_return).all()
    assert np.allclose(trades.executed_entry_price,trades.entry_price*(1+trades.bps/1e4))
    assert np.allclose(trades.loc[trades.limit_exit,'executed_exit_price'],trades.loc[trades.limit_exit,'exit_price']*(1-trades.loc[trades.limit_exit,'bps']/1e4))
    assert (trades.entry_fill_ts>=trades.entry_ts+pd.Timedelta(seconds=5)).all()
    assert (trades.exit_fill_ts>=trades.exit_ts+pd.Timedelta(seconds=1)).all()
    assert ((trades.exit_fill_ts-trades.entry_fill_ts)<pd.Timedelta(days=2)).all()
    assert (pool.entry_ts>pool.decision_ts).all()
    assert ((pool.exit_ts.dt.tz_convert('America/New_York').dt.normalize()-pool.entry_ts.dt.tz_convert('America/New_York').dt.normalize()).dt.total_seconds()<48*3600).all()
    cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    closemap=dict(zip(cal.index.strftime('%Y-%m-%d'),pd.to_datetime(cal['close'],utc=True)))
    exitclose=pd.to_datetime(trades.exit_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d').map(closemap),utc=True)
    assert (trades.exit_fill_ts<exitclose).all()
    for bps,g in trades.groupby('bps'):
        for sid,h in g.groupby('security_id'):
            h=h.sort_values('entry_fill_ts');assert (h.entry_fill_ts.iloc[1:].to_numpy()>h.exit_fill_ts.iloc[:-1].to_numpy()).all()
        events=pd.concat([pd.Series(1,index=g.entry_fill_ts),pd.Series(-1,index=g.exit_fill_ts)]).groupby(level=0).sum().sort_index().cumsum()
        assert events.max()<=10 and events.min()>=0
    assert result.minimum_cash.min()>-1e-10
    # Stage A uses exactly the closing references subsequently replayed with quotes.
    stage=OUT/'close_entry_bar_assumption';stage.mkdir(exist_ok=True);frames=[]
    for bps in quotes.LEVELS:
        frames.append(pd.DataFrame({'order_id':pool.order_id,'bps':bps,'entry_filled':True,'limit_exit':True,'forced_exit':False,'priced':True,
          'entry_fill_ts':pool.entry_ts+pd.Timedelta(seconds=5),'exit_fill_ts':pool.exit_ts+pd.Timedelta(seconds=1),
          'executed_entry_price':pool.entry_price*(1+bps/1e4),'executed_exit_price':pool.exit_price*(1-bps/1e4),
          'return':pool.exit_price*(1-bps/1e4)/(pool.entry_price*(1+bps/1e4))-1}))
    quotes.OUT=stage;quotes.SELECTION_DELAY_SECONDS=4
    with contextlib.redirect_stdout(io.StringIO()):quotes.allocate(pool,pd.concat(frames,ignore_index=True))
    assumed=selected('policy_quote_attempts.parquet',stage).rename(columns={'return':'return_value'});ar=[]
    for bps,g in assumed.groupby('bps'):
        _,ending,_=risk.funded(g,10,0)
        ar.append({'bps':bps,'trades':len(g),'mean_trade_bps':g.return_value.mean()*1e4,'cash_funded_return_pct':(ending-1)*100})
    assumed_summary=pd.DataFrame(ar);assumed_summary.to_parquet(stage/'summary.parquet',index=False)
    # Complete-bar path summaries exclude the pre-fill part of the entry minute.
    bars=pd.read_parquet(OUT/'policy_minute_paths.parquet');by={s:h for s,h in bars.groupby('security_id',sort=False)};paths=[]
    for r in working.itertuples():
        h=by[r.security_id];h=h[(h.stamp>=r.entry_fill_ts)&(h.stamp+pd.Timedelta(minutes=1)<=r.exit_fill_ts)]
        paths.append({'order_id':r.order_id,'mfe_bps':max(0,r.net_return,(h.high/r.executed_entry_price-1).max())*1e4,
                      'mae_bps':min(0,r.net_return,(h.low/r.executed_entry_price-1).min())*1e4,'terminal_bps':r.net_return*1e4})
    paths=pd.DataFrame(paths);paths.to_parquet(DEST/'working_trade_paths.parquet',index=False)
    evidence=pd.read_parquet(OUT/'evidence_map.parquet');evidence=evidence[(evidence.pair_id==PAIR)&(evidence.target_id=='target_2d__raw__daily_close')]
    evidence.to_parquet(DEST/'canonical_state_evidence.parquet',index=False)
    surfaces=[]
    for res,g in evidence.groupby('resolution'):
        r=g.iloc[0]
        for cell,(n,v) in enumerate(zip(r.surface_n,r.surface_bps)):surfaces.append({'resolution':res,'cell':cell,'a_bin':cell//res,'b_bin':cell%res,'n':n,'mean_bps':v})
    pd.DataFrame(surfaces).to_parquet(DEST/'canonical_full_surfaces.parquet',index=False)
    s=result[result.bps==1].iloc[0];qs=summary[summary.bps==1].iloc[0];cs=stress[stress.bps==1].iloc[0]
    reader=json.loads((ROOT/'evidence/reader.json').read_text());features=['ema_distance__20d__raw__daily_close','return_skip_recent_63d_ex_5d__63d__raw__daily_close']
    spec={'strategy_id':'fresh_close_carry_trend_dislocation_20260930','status':'frozen_discovery_candidate','discovery':['2025-05-01','2026-04-30'],
      'out_of_sample_accessed':False,'evidence_id':reader['evidence_id'],'pair_id':PAIR,'features':features,
      'definitions':{'A':'close / EMA(span=20, adjust=False) - 1','B':'close.shift(5) / close.shift(63) - 1'},
      'feature_definition_hashes':{f:reader['grids']['daily_close']['bins'][f]['definition_hash'] for f in features},
      'universe':'Point-in-time SP500 eligible observations; valid inputs, no future target validity or action gates.',
      'state':'Previous-session daily close: A r5=0 and B r5=4. Equivalent r10 cells [8,9,18,19].',
      'binning':'Same-decision cross-sectional average-tie percentile ranks, min(int(percentile*r),r-1); never full-year fitted cutoffs.',
      'rank':'Descending B_r10 - A_r10; ties ascending pandas hash(security_id string + original session_date string + 0), then observation_id. pandas '+pd.__version__,
      'entry':'Following session official close minus 1 minute; select at second 4, buy active at second 5. Prior completed minute reference, availability <= planned time, lookback at most five minutes.',
      'exit':'Next session close minus 1 minute, sell active at second 1. Only calendar holds strictly below 48h; ordinary next-calendar-day carry, no weekend/holiday crossing.',
      'capacity':'10 long positions, one per security, cash funded. Only actual exits completed by selection release slots/cash. Budget cash/free slots; each missed attempt consumes its window; no same-window replacement.',
      'offsets_per_side':quotes.LEVELS,'working_bps_per_side':1,'buy_limit':'entry_reference*(1+bps/10000)','sell_limit':'exit_reference*(1-bps/10000)',
      'entry_expiry_seconds':59,'exit_limit_expiry_seconds':54,'cancel_acknowledgement_seconds':55,'force_execution_seconds':56,
      'emergency_exit':'Fresh valid bid age <=2 sec at 56, else next valid quote strictly before session close. Conservative min(bid,sell_limit) for in-flight cancellation.',
      'quote_checks':'Noncrossed positive prices and positive bid/ask sizes; BUY requires ask<=limit, SELL requires bid>=limit. Pre-window as-of NBBO, maximum age 2 seconds.',
      'quote_routing':'Entry touched bars at maximum +5bp and missing-bar coverage exceptions. All possible-entry exits plus forced liquidation windows.',
      'fees':0,'dividend_cash':'Ignored; 13 source holding actions, no splits. No action-based eligibility filter.',
      'uncertainty':'All discovery selection; monthly/fold consistency and weekly bootstrap are conditional, not independent or selection-adjusted OOS evidence.',
      'limitations':['Historical quote attainability, not actual order fills.','No account notional, displayed-depth consumption, market impact, or cancellation acknowledgements validated.','Drawdown uses minute-close marks, not complete tick paths.','Later replication/final holdout remain sealed.']}
    (DEST/'FROZEN_STRATEGY.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    working.to_parquet(DEST/'working_trades.parquet',index=False)
    stats=result.merge(summary[['bps','mean_fill_bps','forced_exits','misses']],on='bps',validate='one_to_one')
    stats['entry_attainment_pct']=100*stats.fills/stats.attempts;stats['sell_limit_attainment_pct']=100*(stats.fills-stats.forced_exits)/stats.fills
    stats['both_limits_attainment_pct']=100*(stats.fills-stats.forced_exits)/stats.attempts
    stats.to_parquet(DEST/'execution_results.parquet',index=False)
    hf=pd.read_parquet(OUT/'intraday_rebound_120_causal/policy_risk_summary.parquet')
    record=f'''# Fresh strategy discovery, 2026-09-30

Frozen discovery candidate: prior-close low EMA-distance / high older-momentum state, enter next close and exit the following close. Two features, one rank, no extra alpha filters. Working offset +1 bp per side, zero fees, ten cash-funded positions. The entire May 2025–April 2026 year is discovery; later OOS remains sealed.

Working result: **{s.cash_funded_return_pct:.2f}% return; {int(s.fills)} fills; {s.minute_mark_relative_drawdown_pct:.2f}% minute-close drawdown; {int(s.green_months)}/12 positive months; {int(s.green_weeks)}/53 positive weeks; maximum hold {s.max_actual_hold_hours:.3f} hours.** {int(s.symbols)} names, {working.entry_ts.dt.date.nunique()} filled entry sessions, {int(s.attempts)} attempts, {len(pool)} eligible calendar/priced intentions. Win rate {working.net_return.gt(0).mean()*100:.2f}%. Correlated stock trades are not independent trials.

## Rules and execution

State is A bottom quintile AND B top quintile of contemporaneous cross-sectional ranks, using the original prior-session daily decision. A=close/EMA20-1; B=close[-5]/close[-63]-1. Prefer stronger B/lower A using B_decile-A_decile; outcome-independent stable hash ties. These bins are per decision, with no future distribution fitting.

Buy at session close minus one minute +5 seconds; sell next ordinary adjacent-day session at close minus one minute +1 second. Use the latest completed source close at each planned minute, no later than that time. BUY=reference*(1+bps/10000), SELL=reference*(1-bps/10000). Valid fresh ask<=BUY and bid>=SELL establish quote attainability. Select new entries at +4 seconds using only freed cash/slots. Buy expires at +59; sell cancels at +54, assumed acknowledged +55, force liquidation from +56 before close. Forced bid is capped at sell limit conservatively. Known early closes and calendar crossings are handled explicitly; no hold reaches 48 hours. No leverage, no same-security overlap, no fill-conditioned replacement of missed orders.

Stage A uses exactly the closing reference prices replayed in Stage B:

{table(assumed_summary,['bps','trades','mean_trade_bps','cash_funded_return_pct'])}

Stage B retains missed attempts and forced exits; all closing liabilities are priced. Per-side offsets are limit levels, not fees:

{table(stats,['bps','attempts','fills','mean_fill_bps','cash_funded_return_pct','minute_mark_relative_drawdown_pct','green_months','forced_exits','entry_attainment_pct','sell_limit_attainment_pct','both_limits_attainment_pct'])}

## Evidence and controls

Canonical unit: {PAIR}, target_2d__raw__daily_close, r5 cell 4. Active mean 77.611 bp, N=2,269, frequency 2.075%, interaction lift 45.616 bp, weighted contribution 1.610 bp. Parent A 23.331 bp, parent B 18.628 bp. Lift is active-parentA-parentB+overall. Five chronological fold means positive, weakest component fold 40.517 bp. These descriptive targets precede the calendar/funding/quote policy and are not executed returns.

r3 broader corner N=6,192, mean 44.859 bp. Equivalent four r10 children all positive: cells 8/9/18/19 have approximately 94.9/100.9/48.0/58.9 bp; stronger lower-EMA gradient, not one isolated spike. Full surfaces and all distinct evidence lenses are saved alongside this record. Nearby EMA/return definitions were scanned in the full canonical map; not every definition received annual quote validation.

The source feature-only state has 2,455 observations, 2,448 discovery entry dates, six unavailable causal opening references, and 2,442 initially priceable intentions. Closing-calendar selection retains {len(pool)}. Corporate actions were audited without conditioning selection on them. PIT membership passed. Source dividends are ignored, no split accounting exception occurred.

Slower control: both legs activate after five seconds and select new entries before any same-minute sale can free cash/slots. +1bp gives **{cs.cash_funded_return_pct:.2f}%**, {int(cs.fills)} fills, {cs.minute_mark_relative_drawdown_pct:.2f}% drawdown, {int(cs.green_months)}/12 green months. All seven levels remain positive in this control. Uniform hash selection at +1bp also retains approximately 62.5% return and 12 green months; the economic state does not depend on finely optimized ranking. Three slots increases concentration and return, but reduces annual sample and monthly consistency; ten slots is the high-sample primary candidate.

Top five names contribute {s.top5_symbol_profit_share*100:.2f}% of funded profit. Remaining names average {s.ex_top5_symbols_mean_bps:.2f} bp/trade; {s.profitable_symbol_fraction*100:.2f}% of traded names are profitable. Removing the best month leaves {s.excluding_best_month_return_pct:.2f}% of initial capital in marked profit; removing five best marked days leaves {s.excluding_best5_marked_days_return_pct:.2f}%. These are contributions of the existing wallet, not independent reallocated backtests.

Matched SPY same-window reference comparison gives about 7.07 bp/trade versus 58.93 bp for the strategy, 51.86 bp excess. Its actual-budget weighted SPY price profit is about 7.70% versus 64.35% for stocks. This is timing attribution using unexecuted SPY reference prices, not a quote-executed hedge or independent SPY portfolio.

Complete-bar path median MFE {paths.mfe_bps.median():.2f} bp, median MAE {paths.mae_bps.median():.2f} bp, median terminal {paths.terminal_bps.median():.2f} bp. Intrabar extremes are path diagnostics, not attainable stops. The executed same-day opening-to-close variant loses at every level; moving entry to close is an exposure/limit-attainment hypothesis supported by its full-year replay, not a claim that all raw intraday state means are negative.

## Informative failures and search coverage

Fresh full canonical map: 666,498 surfaces, 29,770,244 cells; raw short intraday horizons, overnight, daily one/two-day across r3/r5/r10, with full surfaces, coherent regions, parents, symbol/fold lenses. Daily two-day descriptors were converted to actual calendar holds below 48h before strategy claims. Existing strategy rankings were discarded; code/data/cache were reused.

Opening carry is weaker and sensitive to activation delay. Same-day dislocation loses after quote fills. Activity/drawdown tails lose breadth when top names are removed; scarce overnight and market-regime states have too few independent sessions. Balanced five-mechanism intraday diagnostics use only 240 intentions per mechanism and are not annual strategy evidence.

Full causal two-hour rebound: 437,092 state observations -> 193,921 eligible episodes -> 7,470 reserved annual intentions per hash/ranked head, union 9,612. Exact zero/-1bp annual execution loses despite thousands of fills. No extra filters added to salvage it. +1..+5 ranked heads retain one unresolved ERIE exit each and are explicitly not complete annual performance claims. Hash policies and ranked zero/-1 have complete liquidation coverage:

{table(hf,['ranked','bps','fills','cash_funded_return_pct','minute_mark_relative_drawdown_pct','green_months'])}

## Limits and next test

All reported results are discovery simulations after a broad search. Weekly bootstrap conditional interval {s.weekly_conditional_bootstrap_95_pct_low:.2f}% to {s.weekly_conditional_bootstrap_95_pct_high:.2f}% does not adjust for selection or establish out-of-sample confidence. Quote attainability has positive displayed size, but account notional, depth consumption, queue/impact, and actual cancellation acknowledgements remain unvalidated. Minute-close drawdown may omit brief intraminute losses. Test the frozen policy unchanged on the later sealed data, with a stated account notional, before promotion. No further parameter fitting on that test.

Machine rules: FROZEN_STRATEGY.json. Actual funded fills: working_trades.parquet. All offsets, attempts/misses, equity/months, concentration and matched benchmark are adjacent Parquet files. Reproduce with competition_fresh_close_entry.py, competition_fresh_close_stress.py, competition_fresh_benchmark.py, then competition_fresh_finalize.py. Earlier legacy/full diagnostic folders are not promoted or substituted for the causal replay.
'''
    (OUT/'RESEARCH_RECORD.md').write_text(record,encoding='utf-8')
    local=Path('docs/research/FRESH_STRATEGY_DISCOVERY_20260930.md');local.parent.mkdir(parents=True,exist_ok=True);local.write_text(record,encoding='utf-8')
    files=[DEST/'FROZEN_STRATEGY.json',DEST/'working_trades.parquet',DEST/'execution_results.parquet',DEST/'policy_monthly.parquet',DEST/'matched_benchmark_summary.parquet',DEST/'canonical_full_surfaces.parquet',OUT/'RESEARCH_RECORD.md']
    files+=list(Path('tools').glob('competition_fresh_*.py'))
    manifest={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (DEST/'FROZEN_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (OUT/'DISCOVERY_CANDIDATE_COMPLETE.json').write_text(json.dumps({'candidate_id':spec['strategy_id'],'status':'frozen_discovery_candidate','all_closing_offset_liabilities_priced':True,'hf_ranked_positive_offset_unpriced_liabilities':5,'out_of_sample_accessed':False,'research_record':str(local.resolve())},indent=2),encoding='utf-8')
    print('FROZEN',local.resolve(),flush=True)

if __name__=='__main__':main()
