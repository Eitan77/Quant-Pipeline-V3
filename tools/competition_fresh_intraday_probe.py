"""Zero-fee, all-offset execution diagnostics of simple high-frequency mechanisms."""
import json
import numpy as np,pandas as pd
import competition_fresh_quotes as engine
from competition_fresh_search import OUT

PROBE=OUT/'intraday_limit_probe';PROBE.mkdir(exist_ok=True)
def prepare():
    f=pd.read_parquet(OUT/'trades_intraday_5m.parquet');f=f[f.direction==1].copy()
    f['month']=f.entry_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m')
    f['tie']=pd.util.hash_pandas_object(f.security_id.astype(str)+f.entry_ts.astype(str)+'fresh_quote_probe',index=False).to_numpy()
    f=f.sort_values('tie').groupby(['candidate_id','month'],group_keys=False).head(20).sort_values('entry_ts').reset_index(drop=True)
    f['rank_score']=0
    f.to_parquet(PROBE/'policy_pool.parquet',index=False)
    bars=pd.read_parquet(OUT/'endpoint_bars_intraday_5m.parquet')
    points=pd.concat([f[['security_id','entry_ts']].rename(columns={'entry_ts':'stamp'}),f[['security_id','exit_ts']].rename(columns={'exit_ts':'stamp'})]).drop_duplicates()
    bars=bars.merge(points,on=['security_id','stamp'],validate='one_to_one');bars.to_parquet(PROBE/'policy_endpoint_bars.parquet',index=False)
    (PROBE/'scope.json').write_text(json.dumps({'fees':0,'offsets_per_side':engine.LEVELS,'selection':'20 outcome-independent hashed finite-slot trades per candidate per discovery month',
        'full_year_discovery':True,'complete_annual_strategy_validation':False,'out_of_sample_accessed':False,'sample_trades':len(f),'quote_router':'Only touched entry bars; forced exits retained as liabilities.',
        'purpose':'Do not discard a mechanism solely because +5bp bar results weaken. Test -1/0/1/2/3/4/5 limit attainability.'},indent=2))

def summarize():
    f=pd.read_parquet(PROBE/'policy_quote_pool.parquet');d=pd.read_parquet(PROBE/'policy_quote_outcomes.parquet').merge(f,on='order_id',validate='many_to_one')
    if 'month' not in d:d['month']=d.entry_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m')
    rows=[]
    for (candidate,bps),g in d.groupby(['candidate_id','bps'],sort=True):
        fills=g[g.entry_filled];months=g.groupby('month')['return'].sum()
        rows.append({'candidate_id':candidate,'bps':bps,'attempts':len(g),'fills':len(fills),'forced_exits':int(g.forced_exit.sum()),'unpriced':int((~g.priced).sum()),
          'mean_per_attempt_bps':g['return'].mean()*1e4 if g.priced.all() else np.nan,'mean_per_fill_bps':fills['return'].mean()*1e4 if g.priced.all() else np.nan,
          'positive_sample_months':int((months>0).sum()),'sample_months':len(months)})
    result=pd.DataFrame(rows);result.to_parquet(PROBE/'summary.parquet',index=False);print(result.to_string(index=False),flush=True)

if __name__=='__main__':
    prepare();engine.OUT=PROBE;engine.Q=OUT/'policy_quotes';engine.RUN_ALLOCATION=False;engine.run();summarize()
