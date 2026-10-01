"""Focused canonical momentum/reclaim structure, not an additional grid search."""
import json
import pandas as pd
import competition_under2d as engine
from competition_scalp import OUT

def nominate(grid):
    rows=[]
    for name,cells in [('reclaim_center',[13]),('reclaim_neighbor',[14]),('reclaim_region',[8,9,13,14])]:
        rows.append(dict(candidate_id=name,grid=grid,state_kind='dual',pair_id='e7725806edb7ae261b5661a9',
            feature_a='momentum_sign_agreement__5m_30m__raw__intraday_5m',
            feature_b='prior_high_reclaim_strength__30m__raw__intraday_5m',resolution=5,cells=json.dumps(cells),
            direction=1,target_id='target_2m__raw__intraday_5m',time_group=-1))
    f=pd.DataFrame(rows);f.to_parquet(engine.OUT/'nominations_intraday_5m.parquet',index=False);return f

if __name__=='__main__':
    engine.OUT=OUT/'canonical_momentum';engine.OUT.mkdir(exist_ok=True)
    engine.ENTRY_LAG_MINUTES=0;engine.FULL_YEAR=True;engine.EXIT_LAST_MINUTE=True;engine.nominate=nominate
    engine.replay_grid('intraday_5m')
    f=pd.read_parquet(engine.OUT/'replay_intraday_5m.parquet')
    print(f[f.bps.isin([0,1])][['candidate_id','bps','trades','mean_trade_bps','additive_pct','max_dd_pct','positive_months','symbols','top5_profit_share','ex_top5_mean_bps']].to_string(index=False))
