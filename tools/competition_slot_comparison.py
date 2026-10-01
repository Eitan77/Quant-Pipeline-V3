"""One/two/three/ten-slot concentration comparison, reusing complete quote outcomes."""
import argparse,contextlib,io,json
from pathlib import Path
import numpy as np,pandas as pd
import competition_fresh_risk as risk
from competition_fresh_search import OUT

DEST=OUT/'slot_comparison_20260930';DEST.mkdir(exist_ok=True)

def select(pool,detail,slots,delay):
    w=pool.copy();w['tie']=pd.util.hash_pandas_object(w.security_id.astype(str)+w.session_date.astype(str)+'0',index=False).to_numpy()
    w=w.merge(detail,on='order_id',validate='one_to_one').sort_values(['entry_ts','rank_score','tie','observation_id'],ascending=[True,False,True,True],kind='stable')
    free=np.full(slots,-1,dtype=np.int64);active={};ids=[]
    for r in w.itertuples():
        clock=r.entry_ts.value+delay*1_000_000_000
        if active.get(r.security_id,-1)>clock:continue
        slot=int(free.argmin())
        if free[slot]>clock:continue
        release=(r.exit_fill_ts.value if r.entry_filled else clock+59_000_000_000)+1
        free[slot]=release;active[r.security_id]=release;ids.append(r.order_id)
    g=w[w.order_id.isin(ids)].copy();g['slots']=slots;g['ranked']=True;g['selection_ts']=g.entry_ts+pd.Timedelta(seconds=delay)
    assert g.priced.all(),'Unresolved holding liability'
    return g

def run(profile):
    source=OUT/('close_entry_comparison' if profile=='main' else 'close_entry_conservative')
    sub=DEST/profile;sub.mkdir(exist_ok=True)
    pool=pd.read_parquet(source/'policy_quote_pool.parquet');d=pd.read_parquet(source/'policy_quote_outcomes.parquet')
    for col in ['entry_fill_ts','exit_fill_ts']:d[col]=pd.to_datetime(d[col],utc=True).dt.as_unit('ns')
    delay=4 if profile=='main' else 0;frames=[]
    baseline=pd.read_parquet(source/'policy_quote_attempts.parquet')
    for slots in [1,2,3,10]:
        for bps in [-1,0,1,2,3,4,5]:
            g=select(pool,d[d.bps==bps],slots,delay)
            if slots in [3,10]:
                old=baseline[(baseline.slots==slots)&baseline.ranked&(baseline.bps==bps)]
                assert set(g.order_id)==set(old.order_id),'Cached baseline nomination mismatch'
            fills=g[g.entry_filled]
            assert np.isfinite(fills['return']).all()
            assert ((fills.exit_fill_ts-fills.entry_fill_ts)<pd.Timedelta(days=2)).all()
            events=pd.concat([pd.Series(1,index=fills.entry_fill_ts),pd.Series(-1,index=fills.exit_fill_ts)]).groupby(level=0).sum().sort_index().cumsum()
            assert events.max()<=slots and events.min()>=0
            frames.append(g)
    pd.concat(frames,ignore_index=True).to_parquet(sub/'policy_quote_attempts.parquet',index=False)
    (sub/'scope.json').write_text(json.dumps({'source':str(source),'slots':[1,2,3,10],'ranking':'Unchanged B_decile-A_decile, descending; stable hash ties. No fitted new ranking.',
      'funding':'All available cash divided by free slots; one slot places all available capital into the highest eligible ranked attempt. Misses stay cash and are not replaced in the same window.',
      'select_before_fill':True,'fresh_quote_pulls':0,'fees':0,'out_of_sample_accessed':False,'timing_profile':profile,
      'notional_depth_validated':False,'frozen_primary_policy_changed':False},indent=2))
    risk.OUT=sub;risk.PATH_FILE=OUT/'policy_minute_paths.parquet'
    with (sub/'risk.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):risk.analyze()
    z=pd.read_parquet(sub/'policy_risk_summary.parquet');old=pd.read_parquet(source/'policy_risk_summary.parquet')
    check=z[z.slots.isin([3,10])].merge(old[old.ranked],on=['slots','ranked','bps','fee_bps_roundtrip'],suffixes=('_new','_old'),validate='one_to_one')
    assert np.allclose(check.cash_funded_return_pct_new,check.cash_funded_return_pct_old)
    print(profile,z[z.bps==1][['slots','attempts','fills','cash_funded_return_pct','minute_mark_relative_drawdown_pct','green_months','symbols','top5_symbol_profit_share']].to_string(index=False),flush=True)

def report():
    frames=[]
    for profile in ['main','conservative']:
        g=pd.read_parquet(DEST/profile/'policy_risk_summary.parquet');g['profile']=profile;frames.append(g)
    f=pd.concat(frames,ignore_index=True);f.to_parquet(DEST/'comparison.parquet',index=False)
    lines=[]
    for profile in ['main','conservative']:
        for r in f[(f.profile==profile)&(f.bps==1)].itertuples():
            lines.append(f'| {profile} | {r.slots} | {r.cash_funded_return_pct:+.2f}% | {r.minute_mark_relative_drawdown_pct:.2f}% | {r.green_months}/12 | {r.fills} | {r.symbols} | {r.top5_symbol_profit_share*100:.1f}% |')
    text='''# Concentration comparison, 2026-09-30

Same frozen stock state, rank, closing clocks, limits and May 2025-April 2026 discovery. Only position capacity changes: one, two, three or ten slots. All seven prescribed per-side offsets were replayed from existing complete quote outcomes, with zero new downloads and zero fees. Existing three/ten-slot selections and funded returns reproduce exactly. Later OOS remains untouched; the ten-slot frozen primary policy is unchanged.

At +1bp per side:

| Execution profile | Slots | Cash-funded return | Minute-close drawdown | Positive months | Fills | Names | Top-five profit share |
| --- | --- | --- | --- | --- | --- | --- | --- |
'''+ '\n'.join(lines)+'''

Main execution profile selects at close minute +4sec, activates buys at +5sec and sells at +1sec. Only completed exits free cash/slots. Conservative profile selects before same-minute exits, uses +5sec activation on both legs, and reuses no same-minute sale cash. Both cancel sells at +54sec and force from +56sec, before the official close, using the existing priced outcomes.

Capital is divided by free slots. A one-slot filled attempt invests all available cash in the highest eligible ranked name. Two/three slots allow overlapping carry positions and allocate cash to free slots; a failed limit stays cash and consumes the window. Selection is causal, before attainability; a pending holding can prevent a new entry. This is not hindsight choosing the best return, nor always refilling an existing holding on every day.

Ranking is the existing decile difference B-A. Inside the frozen bottom-EMA/top-older-momentum corner, many names tie; stable security/date hashes break those ties. Concentration does not supply a newly fitted predictor of the single best stock. Smaller trade samples and greater name concentration weaken confidence even when in-sample return is larger.

comparison.parquet contains all 56 combinations; each profile has exact attempts, funded trades, minute equity, monthly returns and name contributions. No unpriced reported liabilities, borrowing, capacity overflow or holds of 48h or longer occurred. Quote attainability is not live fill proof: putting all capital into one name increases order size, and account notional/displayed-depth consumption/impact have not been validated. Drawdowns use minute-close marks.

Reproduce: competition_slot_comparison.py main; conservative; report.
'''
    local=Path('docs/research/FRESH_STRATEGY_SLOTS_20260930.md');local.write_text(text,encoding='utf-8');(DEST/'RESEARCH_RECORD.md').write_text(text,encoding='utf-8')
    (DEST/'COMPLETE.json').write_text(json.dumps({'slot_counts':[1,2,3,10],'profiles':['main','conservative'],'prescribed_offsets':[-1,0,1,2,3,4,5],'combinations':len(f),'out_of_sample_accessed':False,'primary_frozen_policy_changed':False,'notional_depth_validated':False,'record':str(local.resolve())},indent=2))
    print('SAVED',local.resolve(),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['main','conservative','report']);a=p.parse_args()
    if a.stage=='report':report()
    else:run(a.stage)
