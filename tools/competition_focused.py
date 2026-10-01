"""Focused hypotheses drawn from the full-year economic structures."""
import argparse,json
import pandas as pd
import competition_under2d as engine
from competition_full_year import OUT,ROOT

HYPOTHESES={
 'preclose_1555':[
 ('shock_spread','cbdd2260b45ea814154c660a',10,[24],1,'overnight'),
 ('shock_spread_broader','cbdd2260b45ea814154c660a',5,[7],1,'overnight'),
 ('shock_ownvol','b07c480db499fe4c523a6202',10,[43],1,'overnight'),
 ('shock_ownvol_broader','b07c480db499fe4c523a6202',5,[11],1,'overnight'),
 ('shock_disagreement','f56c89aae2d8e06075c1a888',10,[44],1,'overnight'),
 ('shock_disagreement_broad','f56c89aae2d8e06075c1a888',5,[12],1,'overnight'),
 ('shock_market_downvol','306b333fd69bc576376df568',10,[44],1,'overnight'),
 ('jump_marketvol','f4cf57cafd91be9e7ab2130b',10,[34],1,'overnight'),
 ('downrun_marketvol','1f94cb178f501fe799d41dcd',10,[24],1,'overnight'),
 ],
 'daily_close':[
 ('downtrend_reclaim_short','a6490e669f0c30b97c908983',3,[2],-1,'1d'),
 ('downtrend_reclaim_tail_short','a6490e669f0c30b97c908983',10,[45],-1,'1d'),
 ('positive_return_ma_tail','a80d744f007ca5a9b3818172',10,[90],1,'1d'),
 ('positive_return_ma_r5','a80d744f007ca5a9b3818172',5,[20],1,'1d'),
 ('positive_return_ma_r3','a80d744f007ca5a9b3818172',3,[6],1,'1d'),
 ('positive_return_ma_low20','a80d744f007ca5a9b3818172',10,[90,91],1,'1d'),
 ('positive_return_ma_high20','a80d744f007ca5a9b3818172',10,[80,90],1,'1d'),
 ('parent_a_positive_return','a80d744f007ca5a9b3818172',5,[4],1,'1d'),
 ('parent_b_ma_distance','a80d744f007ca5a9b3818172',5,[0],1,'1d'),
 ('low_reclaim_tail','9a1a80ec86701b65a087166d',10,[65],1,'1d'),
 ('broad_marketvol','77a596b0a6ed242fa6ca6c24',10,[54],1,'1d'),
 ],
 'intraday_5m':[
 ('jump_disagreement_short','6bce379896c4039f115d96b4',10,[66],-1,'240m'),
 ('jump_disagreement_short_region','6bce379896c4039f115d96b4',10,[55,56,65,66],-1,'240m'),
 ('jump_disagreement_long','6bce379896c4039f115d96b4',5,[11],1,'240m'),
 ('marketvol_breakout','74e208bf5d26c314c4a21cf9',10,[53],1,'240m'),
 ('distance_low_ema','6bf8967f0709f3d05b861133',5,[20],1,'240m'),
 ('positivejump_marketvol','4a7ab04cf449c7852f542beb',10,[34],1,'240m'),
 ('reclaim_pullback_fast','107b09a582bd4651921a0a9b',10,[52],1,'10m'),
 ('reclaim_pullback_15m','107b09a582bd4651921a0a9b',10,[52],1,'15m'),
 ('reclaim_pullback_60m','107b09a582bd4651921a0a9b',10,[52],1,'60m'),
 ('lead_positivejump_short','abd45bb85b6c9691bbeb708a',5,[20],-1,'240m'),
 ]}

def nominate(grid):
    evidence=pd.read_parquet(OUT/'evidence_map.parquet')
    rows=[]
    for name,pair,r,cells,direction,horizon in HYPOTHESES[grid]:
        matches=evidence[(evidence.pair_id==pair)]
        if matches.empty:
            raise ValueError('Missing mapped pair '+pair)
        ref=matches.iloc[0]
        single=name.startswith('parent_')
        first=ref.feature_b if name.startswith('parent_b_') else ref.feature_a
        rows.append({'candidate_id':name,'grid':grid,'state_kind':'single' if single else 'dual','pair_id':first if single else pair,'feature_a':first,'feature_b':'' if single else ref.feature_b,
            'resolution':r,'cells':json.dumps(cells),'direction':direction,'target_id':f'target_{horizon}__raw__{grid}','time_group':-1,
            'hypothesis':name})
    result=pd.DataFrame(rows);result.to_parquet(OUT/f'nominations_{grid}.parquet',index=False)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('grid',choices=list(HYPOTHESES));args=p.parse_args()
    engine.OUT=OUT;engine.ENTRY_LAG_MINUTES=0;engine.FULL_YEAR=True;engine.EXIT_LAST_MINUTE=True;engine.nominate=nominate
    engine.replay_grid(args.grid)
