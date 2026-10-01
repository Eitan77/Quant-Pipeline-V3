"""New simple reclaim/continuation mechanisms after abandoning weak shock scalps."""
import json
import pandas as pd
import competition_under2d as engine
from competition_scalp import OUT

DEST=OUT/'reset_reclaim';DEST.mkdir(exist_ok=True)
HOLDS=[15,30]

def nominate(grid):
    rows=[]
    for hold in HOLDS:
        for name,pair,fa,fb,r,cells in [
            ('reclaim_single','prior_high_reclaim_strength__30m__raw__intraday_5m','prior_high_reclaim_strength__30m__raw__intraday_5m','',10,[5]),
            ('reclaim_context','f35a92c418d668fbc5a85676','market_risk_adjusted_momentum__30m__raw__intraday_5m','prior_high_reclaim_strength__30m__raw__intraday_5m',10,[45]),
            ('reclaim_coherent','f35a92c418d668fbc5a85676','market_risk_adjusted_momentum__30m__raw__intraday_5m','prior_high_reclaim_strength__30m__raw__intraday_5m',10,[35,45,55,65]),
            ('jump_continuation','c1375a29f15d623c4d7ce457','momentum_sign_agreement__5m_30m__raw__intraday_5m','positive_jump_fraction__30m__raw__intraday_5m',10,[54]),
            ('jump_continuation_coarse','c1375a29f15d623c4d7ce457','momentum_sign_agreement__5m_30m__raw__intraday_5m','positive_jump_fraction__30m__raw__intraday_5m',5,[10])]:
            rows.append({'candidate_id':f'{name}_{hold}m','grid':grid,'state_kind':'dual' if fb else 'single','pair_id':pair,
                'feature_a':fa,'feature_b':fb,'resolution':r,'cells':json.dumps(cells),'direction':1,
                'target_id':f'target_{hold}m__raw__intraday_5m','time_group':-1})
    result=pd.DataFrame(rows);result.to_parquet(DEST/'nominations_intraday_5m.parquet',index=False);return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--holds',type=int,nargs='+',default=HOLDS);parser.add_argument('--name',default='reset_reclaim')
    args=parser.parse_args();HOLDS=args.holds;DEST=OUT/args.name;DEST.mkdir(exist_ok=True)
    engine.OUT=DEST;engine.ENTRY_LAG_MINUTES=0;engine.FULL_YEAR=True;engine.EXIT_LAST_MINUTE=True;engine.nominate=nominate
    engine.replay_grid('intraday_5m')
    f=pd.read_parquet(DEST/'replay_intraday_5m.parquet')
    print(f[f.bps.isin([0,1,2])][['candidate_id','bps','trades','mean_trade_bps','additive_pct','positive_months','max_dd_pct','symbols','ex_top5_mean_bps']].to_string(index=False))
