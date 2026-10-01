"""Compact evidence record and frozen discovery candidate, with honest limits."""
import json
from hashlib import sha256
import numpy as np,pandas as pd
from competition_full_year import ROOT,OUT
from competition_under2d import allocate_frame

def summarize():
    detail=pd.read_parquet(OUT/'quote_replay/attainability_trades.parquet')
    q=detail[(detail.candidate_id=='positive_return_ma_tail')&(detail.slots==1)&(detail.bps==5)&detail.entry_attainable].copy()
    source=pd.read_parquet(OUT/'trades_daily_close.parquet');source=source[source.candidate_id=='positive_return_ma_tail']
    q=q.merge(source[['observation_id','security_id','decision_ts']],on='observation_id',validate='one_to_one')
    q.to_parquet(OUT/'selected_strategy_trades.parquet',index=False)
    # All selected windows have bars already acquired; no extra quotes needed.
    bars=pd.read_parquet(OUT/'daily_core_paths.parquet');bars=bars[bars.candidate_id=='positive_return_ma_tail']
    marks=bars.merge(q[['observation_id','entry_limit','strategy_return','actual_exit_price','entry_first_attainable_ts','exit_first_attainable_ts','exit_status','exit_ts']],on='observation_id',validate='many_to_one')
    marks['mark_ts']=marks.stamp+pd.Timedelta(minutes=1)
    marks=marks[marks.mark_ts>=marks.entry_first_attainable_ts].copy()
    exit_actual=marks.exit_first_attainable_ts.fillna(marks.exit_ts+pd.Timedelta(seconds=59))
    marks['pnl']=np.where(marks.mark_ts>=exit_actual,marks.strategy_return,marks.close/marks.entry_limit-1)
    matrix=marks.pivot(index='mark_ts',columns='observation_id',values='pnl').sort_index()
    for oid,g in q.set_index('observation_id').iterrows():
        if oid not in matrix:continue
        after=matrix.index>=g.exit_ts+pd.Timedelta(minutes=1)
        matrix.loc[after,oid]=g.strategy_return
        matrix[oid]=matrix[oid].ffill().fillna(0)
    equity=matrix.sum(axis=1);dd=np.maximum.accumulate(np.r_[0.,equity.to_numpy()])[1:]-equity.to_numpy()
    equity.rename('fixed_base_return').to_frame().to_parquet(OUT/'selected_strategy_minute_equity.parquet')
    q['exit_date']=q.exit_ts.dt.tz_convert('America/New_York').dt.normalize().dt.tz_localize(None)
    dates=pd.read_parquet(ROOT/'cache/features/daily_close/observations.parquet',columns=['session_date']).session_date.drop_duplicates().sort_values()
    daily=q.groupby('exit_date').strategy_return.sum().reindex(pd.DatetimeIndex(pd.to_datetime(dates)),fill_value=0)
    monthly=daily.groupby(daily.index.strftime('%Y-%m')).sum()
    bysymbol=q.groupby('symbol').strategy_return.agg(['count','mean','sum']).sort_values('sum',ascending=False)
    bysymbol.to_parquet(OUT/'selected_strategy_symbols.parquet')
    byday=q.groupby('exit_date').strategy_return.sum().sort_values(ascending=False)
    weeks=daily.groupby(daily.index.to_period('W')).sum().to_numpy()
    rng=np.random.default_rng(20260930);boot=rng.choice(weeks,(3000,len(weeks)),replace=True).sum(axis=1)
    tiedetail=detail[(detail.candidate_id=='positive_return_ma_tail')&(detail.slots==10)&(detail.bps==5)].set_index('observation_id')
    ties=[]
    for seed in range(10):
        selected=allocate_frame(source,1,seed)
        returns=tiedetail.loc[selected.observation_id,'strategy_return']
        ties.append(float(returns.sum()*100))
    top5=byday.head(5).sum();exsym=q[~q.symbol.isin(bysymbol.head(5).index)]
    stats={'quote_supported_fixed_base_return_pct':float(q.strategy_return.sum()*100),
        'filled_trades':len(q),'mean_filled_trade_bps':float(q.strategy_return.mean()*10000),
        'minute_mark_drawdown_pct':float(dd.max()*100),'positive_months':int((monthly>0).sum()),
        'monthly_pct':monthly.mul(100).to_dict(),'symbols':int(q.symbol.nunique()),'positive_symbol_fraction':float((bysymbol['sum']>0).mean()),
        'top5_symbol_profit_share':float(bysymbol['sum'].head(5).sum()/q.strategy_return.sum()),
        'excluding_top5_symbols_mean_trade_bps':float(exsym.strategy_return.mean()*10000),
        'excluding_best5_days_return_pct':float((q.strategy_return.sum()-top5)*100),
        'excluding_best_month_return_pct':float((monthly.sum()-monthly.max())*100),
        'weekly_resampling_95pct_return_interval_pct':(np.quantile(boot,[.025,.975])*100).tolist(),
        'quote_supported_tie_order_return_range_pct':[min(ties),max(ties)],
        'resampling_caveat':'Descriptive resampling within selected discovery; not a selection-adjusted significance test or OOS validation.',
        'hold_minutes_nominal':388,'entry_latency_seconds':1,'unfilled_entry_policy':'Skip that session; do not substitute another name.'}
    (OUT/'selected_strategy_summary.json').write_text(json.dumps(stats,indent=2))
    rule={'name':'Positive-return activity / below-SMA tail reversal','status':'frozen_discovery_candidate',
        'discovery':['2025-05-01','2026-04-30'],'pair_id':'a80d744f007ca5a9b3818172','grid':'daily_close',
        'feature_a':'positive_return_sum__20d__raw__daily_close','feature_b':'price_minus_sma_volnorm__20d__raw__daily_close',
        'direction':'long','rank_method':'Same-decision cross-sectional average percentile rank over eligible PIT securities.',
        'state':'r10 cell 90: feature A bin 9 and feature B bin 0','resolution':10,'cells':[90],
        'target':'target_1d__raw__daily_close','entry':'Next trading session 09:31 New York; 1-second latency; limit reference is that minute open.',
        'exit':'Same session 15:59 New York; limit reference is that minute open; force close at last valid bid before 16:00 if limit fails.',
        'execution_offsets_bps_per_side':[-1,0,1,2,3,4,5],'conservative_reporting_offset_bps_per_side':5,
        'order_ttl_seconds':59,'max_positions':1,'gross_exposure_limit':1.,'fixed_base_notional':1.,
        'tie_break':'uint64 pandas hash of stable security_id + decision session_date + string 0; lowest first. Independent of outcomes.',
        'entry_failure':'No filled order => cash for that session; no fallback signal.',
        'max_hold_seconds_exclusive':172800,'practical_hold':'about 6.5 hours; no overnight positions',
        'quote_check':'ASK <= buy limit; BID >= sell limit. No queue/size claim beyond requested attainability.',
        'missing_exit_quotes':'Block performance claim; never drop open positions.',
        'out_of_sample_accessed':False,'remaining':'Frozen out-of-sample validation; explicit notional/depth capacity and broker fee specification.',
        'artifacts':'selected_strategy_trades.parquet; selected_strategy_summary.json; quote_replay/summary.parquet'}
    rule['definition_sha256']=sha256(json.dumps(rule,sort_keys=True).encode()).hexdigest()
    (OUT/'FROZEN_STRATEGY.json').write_text(json.dumps(rule,indent=2))
    print(json.dumps(stats,indent=2),flush=True)

if __name__=='__main__':summarize()
