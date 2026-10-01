"""Full-year funded gap execution, concentration and causal ranking diagnostics."""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from intraday_causal_restart import OUT as RESEARCH
from intraday_minute_restart import OUT as MINUTE
from competition_slot_comparison import select
from competition_fresh_risk import funded

DEST=RESEARCH/'limits_gap_continuation_liquid_decile_60m_probe'

def run(slot_counts):
    axes=json.loads((MINUTE/'axes.json').read_text());days=axes['days'];cube=np.load(MINUTE/'close.npy',mmap_mode='r')
    f=pd.read_parquet(DEST/'policy_pool.parquet');detail=pd.read_parquet(DEST/'quote_outcomes.parquet')
    frozen=json.loads((DEST/'FROZEN_PROBE.json').read_text());gap=DEST.name.startswith('limits_gap_')
    spec={'slot_counts':slot_counts,'ranking':('Unchanged descending standardized market-relative opening gap; stable identity ties. One opening batch daily; misses are not replaced.' if gap else frozen['ranking']),
      'price_levels':[-1,0,1,2,3,4,5],'new_quote_pulls':0,'discovery_only':True,'ticker_filters':False,
      'strength_diagnostics':('Predefined descriptive bands [0.5,0.75,1,1.5,infinity], not fitted trade thresholds.' if gap else 'No additional strength filters; replay original nominations.'),
      'coverage':'Original ten-slot nomination pool; no unquoted replacement opportunities added.'}
    (DEST/('RANKING_SPEC_TOP2.json' if slot_counts==[2] else 'RANKING_SPEC.json')).write_text(json.dumps(spec,indent=2))
    def save(frame,name):
        path=DEST/name
        if path.exists():
            old=pd.read_parquet(path);frame=pd.concat([old[~old.slots.isin(slot_counts)],frame],ignore_index=True)
        frame.to_parquet(path,index=False);return frame
    calendar_closes=pd.to_datetime(np.array(axes['open_epoch_ns'])+np.array(axes['session_minutes'])*60_000_000_000,utc=True)
    rows=[];curves=[];monthrows=[];symbolrows=[];allfills=[]
    for slots in spec['slot_counts']:
        for bps in spec['price_levels']:
            g=select(f,detail[detail.bps==bps].rename(columns={'return_value':'return'}),slots,4).rename(columns={'return':'return_value'})
            assert g.priced.all()
            budgets,ending,mincash=funded(g,slots,0);g['budget']=g.order_id.map(budgets).fillna(0);g['funded_pnl']=g.budget*g.return_value
            fills=g[g.entry_filled].copy();assert np.isfinite(fills.return_value).all()
            assert ((fills.exit_fill_ts-fills.entry_fill_ts)<pd.Timedelta(days=2)).all()
            assert (fills.exit_fill_ts.to_numpy()<=calendar_closes[fills.day.to_numpy(int)].to_numpy()).all()
            events=pd.concat([pd.Series(1,index=fills.entry_fill_ts),pd.Series(-1,index=fills.exit_fill_ts)]).groupby(level=0).sum().sort_index().cumsum()
            assert events.min()>=0 and events.max()<=slots
            changes=[]
            for r in fills.itertuples():
                prices=cube[r.day,r.symbol_code];ts=np.array(axes['open_epoch_ns'][r.day]+(np.arange(390)+1)*60_000_000_000)
                keep=(ts>r.entry_fill_ts.value)&(ts<r.exit_fill_ts.value)&np.isfinite(prices)
                stamps=np.r_[r.entry_fill_ts.value,ts[keep],r.exit_fill_ts.value]
                pnl=np.r_[0.,r.direction*(prices[keep]/r.executed_entry_price-1),r.return_value]
                changes.append(pd.Series(np.diff(pnl,prepend=0.)*r.budget,index=pd.to_datetime(stamps,utc=True)))
            delta=pd.concat(changes).groupby(level=0).sum().sort_index() if changes else pd.Series(dtype=float,index=pd.DatetimeIndex([],tz='UTC'))
            equity=(delta.cumsum()+1).reindex(delta.index.union(calendar_closes)).sort_index().ffill().fillna(1.)
            assert abs(equity.iloc[-1]-ending)<1e-9
            closeeq=equity.reindex(calendar_closes);daily=closeeq.diff();daily.iloc[0]=closeeq.iloc[0]-1
            series=pd.Series(daily.to_numpy(),index=pd.to_datetime(days));months=series.groupby(series.index.strftime('%Y-%m')).sum();weeks=series.groupby(series.index.to_period('W')).sum()
            dd=1-equity/np.maximum.accumulate(np.r_[1.,equity.to_numpy()])[1:]
            sym=fills.groupby('symbol').agg(trades=('order_id','size'),pnl=('funded_pnl','sum'),mean_bps=('return_value',lambda x:x.mean()*1e4)).sort_values('pnl',ascending=False)
            trimmed=fills[~fills.symbol.isin(sym.head(5).index)]
            rng=np.random.default_rng(20260930);boot=rng.choice(weeks.to_numpy(),(3000,len(weeks)),replace=True).sum(axis=1)*100
            rows.append({'slots':slots,'bps':bps,'attempts':len(g),'fills':len(fills),'both_limits':int(g.limit_exit.sum()),'forced_exits':int(g.forced_exit.sum()),
              'cash_funded_return_pct':(ending-1)*100,'minute_mark_relative_drawdown_pct':float(dd.max()*100),'mean_fill_bps':float(fills.return_value.mean()*1e4),
              'positive_months':int((months>0).sum()),'positive_week_fraction':float((weeks>0).mean()),'positive_day_fraction':float((series>0).mean()),
              'without_best_month_pct':float((months.sum()-months.max())*100),'without_best5_days_pct':float((series.sum()-series.nlargest(5).sum())*100),
              'ex_top5_mean_bps':float(trimmed.return_value.mean()*1e4),'symbols':len(sym),'top5_profit_share':float(sym.pnl.head(5).sum()/fills.funded_pnl.sum()),
              'conditional_week_bootstrap_low_pct':float(np.quantile(boot,.025)),'conditional_week_bootstrap_high_pct':float(np.quantile(boot,.975)),
              'maximum_hold_minutes':float((fills.exit_fill_ts-fills.entry_fill_ts).dt.total_seconds().max()/60),'minimum_cash':mincash})
            curves.append(pd.DataFrame({'timestamp':equity.index,'funded_equity':equity.to_numpy(),'slots':slots,'bps':bps}))
            monthrows.extend({'month':m,'funded_pct_of_initial':v*100,'slots':slots,'bps':bps} for m,v in months.items())
            symbolrows.append(sym.reset_index().assign(slots=slots,bps=bps));allfills.append(fills)
    result=pd.DataFrame(rows);save(result,'funded_risk_and_ranking.parquet')
    save(pd.concat(curves,ignore_index=True),'funded_minute_equity.parquet')
    save(pd.DataFrame(monthrows),'funded_monthly.parquet')
    save(pd.concat(symbolrows,ignore_index=True),'funded_symbol_contributions.parquet')
    filled=save(pd.concat(allfills,ignore_index=True),'funded_fills.parquet')
    if gap:
        filled['strength_band']=pd.cut(filled.score,[.5,.75,1,1.5,np.inf],right=False)
        bands=filled[filled.slots==10].groupby(['bps','strength_band'],observed=True).agg(fills=('order_id','size'),mean_bps=('return_value',lambda x:x.mean()*1e4))
        bands.reset_index().assign(strength_band=lambda x:x.strength_band.astype(str)).to_parquet(DEST/'strength_descriptive.parquet',index=False)
    print(result[result.bps.isin([-1,0,1])][['slots','bps','attempts','fills','cash_funded_return_pct','minute_mark_relative_drawdown_pct','positive_months','mean_fill_bps','ex_top5_mean_bps','without_best5_days_pct']].to_string(index=False),flush=True)
    if gap:print('STRENGTH_BANDS_ZERO',bands.loc[0].to_string(),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--slots',type=int,nargs='+',default=[1,3,10]);p.add_argument('--candidate',default='gap_continuation_liquid_decile_60m');a=p.parse_args()
    DEST=RESEARCH/f'limits_{a.candidate}_probe';run(a.slots)
