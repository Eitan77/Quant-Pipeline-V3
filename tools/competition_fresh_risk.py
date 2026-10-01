"""Minute marks, funded cash accounting and conditional discovery uncertainty."""
import json, argparse, heapq
import numpy as np,pandas as pd,duckdb
from competition_fresh_search import OUT
from competition_under2d import ROOT
PATH_FILE=None

def extract():
    f=pd.read_parquet(OUT/'policy_pool.parquet');parts=[]
    for column in ['entry_ts','exit_ts']:
        p=f[['security_id',column]].copy();p['session_date']=p[column].dt.tz_convert('America/New_York').dt.date
        parts.append(p[['security_id','session_date']])
    days=pd.concat(parts).drop_duplicates()
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    with duckdb.connect(source,read_only=True) as c:
        c.execute("SET memory_limit='5GB'");c.execute('SET threads=4');c.register('days',days)
        bars=c.execute('''SELECT b.security_id,b.bar_start_ts_utc stamp,b.high,b.low,b.close
            FROM bars_1m_raw b JOIN days d USING(security_id,session_date)''').fetchdf()
        c.register('signals',f)
        integrity=c.execute('''SELECT s.observation_id,bool_or(coalesce(m.in_universe,false)) eligible
          FROM signals s LEFT JOIN sp500_pit_membership_daily m ON s.security_id=m.security_id AND s.session_date=m.session_date GROUP BY 1''').fetchdf()
    assert integrity.eligible.all(),'PIT membership failure'
    bars.to_parquet(OUT/'policy_minute_paths.parquet',index=False)
    (OUT/'policy_pit_integrity.json').write_text(json.dumps({'signals':len(f),'pit_membership_passed':bool(integrity.eligible.all()),'outside_discovery_prices':bool((bars.stamp>=pd.Timestamp('2026-05-01',tz='America/New_York')).any())},indent=2))
    print('PATHS',len(bars),'security-days',len(days),flush=True)

def funded(g,slots,fee):
    pending=[];cash=1.;budgets={};minimum=1.;seq=0
    for t,h in g.groupby('selection_ts' if 'selection_ts' in g else 'entry_ts',sort=True):
        while pending and pending[0][0]<=t.value:
            _,_,credit=heapq.heappop(pending);cash+=credit
        budget=cash/(slots-len(pending))
        for r in h[h.entry_filled].itertuples():
            budgets[r.order_id]=budget;cash-=budget;seq+=1
            heapq.heappush(pending,(r.exit_fill_ts.value,seq,budget*(1+r.return_value-fee/1e4)))
        minimum=min(minimum,cash)
    cash+=sum(item[2] for item in pending)
    assert minimum>=-1e-10,'Borrowed cash'
    return budgets,cash,minimum

def analyze():
    attempts=pd.read_parquet(OUT/'policy_quote_attempts.parquet').rename(columns={'return':'return_value'})
    bars=pd.read_parquet(PATH_FILE or OUT/'policy_minute_paths.parquet');bars['mark_ts']=bars.stamp+pd.Timedelta(minutes=1)
    bysid={sid:h.sort_values('mark_ts') for sid,h in bars.groupby('security_id',sort=False)}
    # Market calendar determines both zero-return sessions and month-end marks.
    import exchange_calendars as xc
    schedule=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    col='close' if 'close' in schedule else 'market_close';closes=pd.DatetimeIndex(pd.to_datetime(schedule[col],utc=True))
    results=[];monthrecords=[];equities=[];fundedledgers=[];symbolrecords=[]
    for (slots,ranked,bps),g in attempts.groupby(['slots','ranked','bps'],sort=True):
        if not g.priced.all():continue
        assert (g.entry_ts>g.decision_ts).all()
        f=g[g.entry_filled].copy()
        assert np.isfinite(f.return_value).all(),'Priced holding has no finite return'
        assert ((f.exit_fill_ts-f.entry_fill_ts)<pd.Timedelta(days=2)).all()
        for fee in [0.]:
            budgets,ending,mincash=funded(g,int(slots),fee)
            f['budget']=f.order_id.map(budgets);f['net_return']=f.return_value-fee/1e4
            f['funded_pnl']=f.budget*f.net_return
            if fee==0.:fundedledgers.append(f.assign(fee_bps=fee))
            deltas=[];fixed=[]
            for r in f.itertuples():
                p=bysid[r.security_id];p=p[(p.mark_ts>r.entry_fill_ts)&(p.mark_ts<r.exit_fill_ts)]
                ts=np.r_[r.entry_fill_ts.value,p.mark_ts.dt.as_unit('ns').astype('int64').to_numpy(),r.exit_fill_ts.value]
                pnl=np.r_[0.,p.close.to_numpy()/r.executed_entry_price-1,r.net_return]
                change=np.diff(pnl,prepend=0.)
                deltas.append(pd.Series(change*r.budget,index=pd.to_datetime(ts,utc=True)))
                fixed.append(pd.Series(change/int(slots),index=pd.to_datetime(ts,utc=True)))
            changes=pd.concat(deltas).groupby(level=0).sum().sort_index()
            eq=(changes.cumsum()+1).reindex(changes.index.union(closes)).sort_index().ffill().fillna(1.)
            assert eq.index.min()>=pd.Timestamp('2025-05-01',tz='UTC'),'Timestamp unit mismatch'
            fixchanges=pd.concat(fixed).groupby(level=0).sum().sort_index()
            fixeq=(fixchanges.cumsum()+1).reindex(eq.index).ffill().fillna(1.)
            assert abs(eq.iloc[-1]-ending)<1e-8
            closeeq=eq.reindex(closes);daily=closeeq.diff();daily.iloc[0]=closeeq.iloc[0]-1
            months=daily.groupby(closes.tz_convert('America/New_York').strftime('%Y-%m')).sum()
            monthlyret=closeeq.groupby(closes.tz_convert('America/New_York').strftime('%Y-%m')).last();monthlyret=monthlyret/monthlyret.shift(1).fillna(1.)-1
            drawdown=1-eq/np.maximum.accumulate(np.r_[1.,eq.to_numpy()])[1:]
            fixeddd=np.maximum.accumulate(np.r_[1.,fixeq.to_numpy()])[1:]-fixeq
            weekly=daily.groupby(closes.tz_convert('America/New_York').tz_localize(None).to_period('W')).sum().to_numpy()
            rng=np.random.default_rng(20260930);boot=rng.choice(weekly,(3000,len(weekly)),replace=True).sum(axis=1)
            sym=f.groupby('symbol').agg(trades=('order_id','size'),pnl=('funded_pnl','sum'),mean_bps=('net_return',lambda v:v.mean()*1e4)).sort_values('pnl',ascending=False)
            trim=f[~f.symbol.isin(sym.head(5).index)]
            results.append({'slots':int(slots),'ranked':bool(ranked),'bps':int(bps),'fee_bps_roundtrip':fee,'attempts':len(g),'fills':len(f),
                'cash_funded_return_pct':(ending-1)*100,'minute_mark_relative_drawdown_pct':float(drawdown.max()*100),
                'fixed_base_return_pct':f.net_return.sum()/slots*100,'fixed_base_minute_drawdown_pct_points':float(fixeddd.max()*100),
                'green_months':int((months>0).sum()),'green_weeks':int((weekly>0).sum()),'weeks':len(weekly),
                'profitable_symbol_fraction':float((sym.pnl>0).mean()),'symbols':len(sym),'top5_symbol_profit_share':float(sym.pnl.head(5).sum()/f.funded_pnl.sum()),
                'ex_top5_symbols_mean_bps':float(trim.net_return.mean()*1e4),'excluding_best_month_return_pct':float((months.sum()-months.max())*100),
                'excluding_best5_marked_days_return_pct':float((daily.sum()-daily.nlargest(5).sum())*100),
                'weekly_conditional_bootstrap_95_pct_low':float(np.quantile(boot,.025)*100),'weekly_conditional_bootstrap_95_pct_high':float(np.quantile(boot,.975)*100),
                'max_actual_hold_hours':float((f.exit_fill_ts-f.entry_fill_ts).dt.total_seconds().max()/3600),'minimum_cash':mincash})
            for month,v in months.items():monthrecords.append({'slots':slots,'ranked':ranked,'bps':bps,'fee':fee,'month':month,'funded_pct_of_initial':v*100,'monthly_return_pct':monthlyret.loc[month]*100})
            if fee==0.:
                equities.append(pd.DataFrame({'stamp':eq.index,'funded_equity':eq.to_numpy(),'fixed_base_equity':fixeq.to_numpy(),'slots':slots,'ranked':ranked,'bps':bps}))
                symbolrecords.append(sym.reset_index().assign(slots=slots,ranked=ranked,bps=bps))
    result=pd.DataFrame(results);result.to_parquet(OUT/'policy_risk_summary.parquet',index=False)
    pd.DataFrame(monthrecords).to_parquet(OUT/'policy_monthly.parquet',index=False)
    pd.concat(equities).to_parquet(OUT/'policy_minute_equity.parquet',index=False)
    pd.concat(fundedledgers).to_parquet(OUT/'policy_funded_trades.parquet',index=False)
    pd.concat(symbolrecords).to_parquet(OUT/'policy_symbol_contribution.parquet',index=False)
    print(result[(result.bps.isin([0,5]))&(result.fee_bps_roundtrip==0)].to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['extract','analyze']);a=p.parse_args();globals()[a.stage]()
