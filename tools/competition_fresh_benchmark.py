"""Matched unexecuted SPY price-return comparison, no invented hedge strategy."""
import json
import pandas as pd,duckdb
from competition_fresh_search import OUT
from competition_under2d import ROOT

if __name__=='__main__':
    sub=OUT/'close_entry_comparison';f=pd.read_parquet(sub/'policy_funded_trades.parquet');f=f[(f.slots==10)&f.ranked].copy()
    pts=pd.concat([f[['entry_ts']].rename(columns={'entry_ts':'stamp'}),f[['exit_ts']].rename(columns={'exit_ts':'stamp'})]).drop_duplicates()
    pts['stamp']=pd.to_datetime(pts.stamp,utc=True).dt.as_unit('ns')
    cache=pd.read_parquet(OUT/'matched_spy_references.parquet');cache['stamp']=pd.to_datetime(cache.stamp,utc=True).dt.as_unit('ns')
    missing=pts[~pts.stamp.isin(cache.stamp)].copy();missing['bar_start_ts_utc']=missing.stamp-pd.Timedelta(minutes=1)
    if len(missing):
        dates=','.join("DATE '"+str(x)+"'" for x in missing.stamp.dt.tz_convert('America/New_York').dt.date.unique())
        source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
        with duckdb.connect(source,read_only=True) as c:
            c.execute("SET memory_limit='4GB'");c.execute('SET threads=4');c.register('pts',missing)
            extra=c.execute(f'''SELECT p.stamp,b.symbol,b.close FROM bars_1m_raw b JOIN pts p USING(bar_start_ts_utc)
                WHERE b.symbol='SPY' AND b.availability_ts_utc<=p.stamp AND b.session_date IN ({dates})''').fetchdf()
        extra['stamp']=pd.to_datetime(extra.stamp,utc=True).dt.as_unit('ns');cache=pd.concat([cache,extra]).drop_duplicates('stamp')
    for column in ['entry_ts','exit_ts']:f[column]=pd.to_datetime(f[column],utc=True).dt.as_unit('ns')
    f=f.merge(cache[['stamp','close']].rename(columns={'stamp':'entry_ts','close':'spy_entry_reference'}),on='entry_ts',how='left',validate='many_to_one')
    f=f.merge(cache[['stamp','close']].rename(columns={'stamp':'exit_ts','close':'spy_exit_reference'}),on='exit_ts',how='left',validate='many_to_one')
    assert f.spy_entry_reference.gt(0).all() and f.spy_exit_reference.gt(0).all(),'Incomplete matched benchmark'
    f['spy_price_return']=f.spy_exit_reference/f.spy_entry_reference-1
    f['matched_excess_bps']=(f.net_return-f.spy_price_return)*1e4
    rows=[]
    for bps,g in f.groupby('bps'):
        rows.append({'bps':int(bps),'fills':len(g),'strategy_mean_bps':g.net_return.mean()*1e4,'matched_spy_mean_bps':g.spy_price_return.mean()*1e4,
            'mean_matched_excess_bps':g.matched_excess_bps.mean(),'same_actual_budget_weighted_spy_price_profit_pct':(g.budget*g.spy_price_return).sum()*100,
            'same_actual_budget_weighted_excess_profit_pct':(g.budget*(g.net_return-g.spy_price_return)).sum()*100})
    f.to_parquet(sub/'matched_benchmark_trades.parquet',index=False);pd.DataFrame(rows).to_parquet(sub/'matched_benchmark_summary.parquet',index=False)
    cache.to_parquet(OUT/'matched_spy_references.parquet',index=False);print(pd.DataFrame(rows).to_string(index=False),flush=True)
