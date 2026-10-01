"""Bounded source audit and preregistered selectivity diagnostics."""
import argparse,json
import numpy as np,pandas as pd,duckdb
from intraday_minute_restart import OUT
from intraday_causal_restart import OUT as RESEARCH
from competition_slot_comparison import select
from competition_fresh_risk import funded

def audit(candidate):
    shock=candidate.startswith('shock_reversion');assert shock or candidate.startswith('momentum_confirmation')
    with duckdb.connect() as c:
        f=c.execute('SELECT * FROM read_parquet(?) WHERE candidate_id=?',[str(OUT/'survivor_nominations.parquet'),candidate]).fetchdf()
    cube=np.load(OUT/'close.npy',mmap_mode='r');rng=np.random.default_rng(20260930)
    sample=f.iloc[rng.choice(len(f),min(len(f),1000 if shock else 100),replace=False)];errors=[]
    for r in sample.itertuples():
        history=cube[r.day,r.symbol_code,r.signal_minute-31:r.signal_minute+1]
        returns=np.log(history[1:]/history[:-1]);sigma=returns[:-1].std(ddof=1)
        score=(returns[-1]/sigma if shock else np.log(history[-1]/history[-6])/(sigma*np.sqrt(5)))
        assert r.entry_price==history[-1] and r.direction==np.sign(score)*(-1 if shock else 1)
        if not shock:assert returns[-1]*r.direction>0
        errors.append(abs(abs(score)-r.score))
        # A future-price perturbation leaves this prefix and its signal unchanged.
        changed=np.array(cube[r.day,r.symbol_code]);changed[r.signal_minute+1:]*=1.5
        hist=changed[r.signal_minute-31:r.signal_minute+1]
        ret=np.log(hist[1:]/hist[:-1]);newscore=ret[-1]/ret[:-1].std(ddof=1) if shock else np.log(hist[-1]/hist[-6])/(ret[:-1].std(ddof=1)*np.sqrt(5))
        assert newscore==score
    assert max(errors)<1e-10
    (OUT/('shock_source_audit.json' if shock else candidate+'_source_audit.json')).write_text(json.dumps({'candidate':candidate,'random_nominations':len(sample),'maximum_signal_error':max(errors),
      'exact_entry_prices':True,'correct_reversal_sides':True,'future_price_perturbation_invariance':True,'lookback':'30 prior completed one-minute returns, excluding current shock'},indent=2))
    f['strength_bucket']=pd.cut(f.score,[2,3,4,6,np.inf],right=False) if shock else pd.cut(f.score,[1.5,2,3,np.inf],right=False)
    f['return_bps']=f.direction*(f.exit_price/f.entry_price-1)*10000
    result=f.groupby(['direction','strength_bucket'],observed=True).agg(trades=('score','size'),mean_bps=('return_bps','mean'))
    result.to_csv(OUT/(('shock' if shock else candidate)+'_strength_descriptive.csv'));print('AUDITED',candidate,len(sample),'source signals; max error',max(errors));print(result.to_string())

def controls(candidate):
    dest=RESEARCH/('limits_'+candidate+'_probe')
    assert (RESEARCH/'minute_selectivity_controls.json').exists()
    f=pd.read_parquet(dest/'policy_pool.parquet');detail=pd.read_parquet(dest/'quote_outcomes.parquet')
    ranked=f.sort_values(['entry_ts','score','observation_id'],ascending=[True,False,True],kind='stable')
    policies={'all':f,'strength_at_least_3':f[f.score>=3],
      'top3_per_minute':ranked.groupby('entry_ts',sort=False).head(3),'top1_per_minute':ranked.groupby('entry_ts',sort=False).head(1)}
    rows=[];ledgers=[]
    for policy,pool in policies.items():
        for bps in [-1,0,1,2,3,4,5]:
            outcomes=detail[(detail.bps==bps)&detail.order_id.isin(pool.order_id)].copy()
            if not outcomes.priced.all():continue
            g=select(pool,outcomes.rename(columns={'return_value':'return'}),10,4).rename(columns={'return':'return_value'})
            budgets,cash,mincash=funded(g,10,0);g['budget']=g.order_id.map(budgets).fillna(0);g['funded_pnl']=g.budget*g.return_value
            fills=g[g.entry_filled];daily=g.groupby(g.session_date)['funded_pnl'].sum();months=g.groupby(g.session_date.dt.strftime('%Y-%m'))['funded_pnl'].sum()
            sym=fills.groupby('security_id').return_value.sum().sort_values(ascending=False)
            trim=fills[~fills.security_id.isin(sym.head(5).index)]
            rows.append({'candidate_id':candidate,'policy':policy,'bps':bps,'attempts':len(g),'fills':len(fills),
              'fill_rate':len(fills)/len(g) if len(g) else 0,'both_limit_trades':int(g.limit_exit.sum()),'forced_exits':int(g.forced_exit.sum()),
              'mean_filled_bps':float(fills.return_value.mean()*1e4),'mean_per_attempt_bps':float(g.return_value.mean()*1e4),
              'sampled_fragment_funded_return_pct':(cash-1)*100,'positive_sample_days':int((daily>0).sum()),'sample_days':len(daily),
              'positive_sample_months':int((months>0).sum()),'ex_top5_mean_bps':float(trim.return_value.mean()*1e4),
              'maximum_hold_minutes':float((fills.exit_fill_ts-fills.entry_fill_ts).dt.total_seconds().max()/60),'minimum_cash':mincash})
            ledgers.append(g.assign(policy=policy))
    result=pd.DataFrame(rows);result.to_parquet(dest/'selectivity_summary.parquet',index=False)
    pd.concat(ledgers,ignore_index=True).to_parquet(dest/'selectivity_attempts.parquet',index=False)
    print(result[result.bps.isin([-1,0])][['policy','bps','attempts','fills','forced_exits','mean_filled_bps','mean_per_attempt_bps','positive_sample_months']].to_string(index=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['audit','controls']);p.add_argument('--candidate',default='shock_reversion_stocks_2m');a=p.parse_args()
    if a.stage=='audit':audit(a.candidate)
    else:controls(a.candidate)
