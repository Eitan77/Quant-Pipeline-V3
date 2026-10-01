"""Independent intraday and overnight mechanism checks, without added filters."""
import argparse,json
import pandas as pd
import competition_under2d as engine
from competition_fresh_search import OUT

def nominate(grid):
    mapped=pd.read_parquet(OUT/'evidence_map.parquet');rows=[]
    hypotheses={
      'intraday_5m':[
        ('intraday_rebound','6bf8967f0709f3d05b861133',5,[20],1,'240m'),
        ('intraday_rebound_shorter','6bf8967f0709f3d05b861133',5,[20],1,'120m'),
        ('intraday_rebound_vwap','005eb9ded12827988c624424',5,[20],1,'240m'),
        ('beta_vol_expansion','f0d9207cb6693f54020c2e00',10,[99],1,'240m'),
        ('beta_vol_expansion_shorter','f0d9207cb6693f54020c2e00',10,[99],1,'120m'),
        ('jump_fade_parent','positive_jump_fraction__30m__raw__intraday_5m',5,[3],-1,'240m')],
      'preclose_1555':[
        ('overnight_downvol_jump','306b333fd69bc576376df568',10,[44],1,'overnight'),
        ('overnight_vol_jump','b84befec53fe0cc039e1bb3f',10,[44],1,'overnight'),
        ('overnight_drawdown_ownvol','5b56a81cde3de7f625d94f3d',10,[43],1,'overnight'),
        ('overnight_low_reversal','9686365ecc055e644f4b7b23',5,[7],1,'overnight')]}
    for name,pair,r,cells,direction,horizon in hypotheses[grid]:
        single=name.endswith('_parent')
        if single:fa,fb=pair,''
        else:
            g=mapped[(mapped.grid==grid)&(mapped.pair_id==pair)]
            if g.empty:raise RuntimeError('Unmapped canonical hypothesis '+pair)
            fa,fb=g.iloc[0].feature_a,g.iloc[0].feature_b
        rows.append(dict(candidate_id=name,grid=grid,state_kind='single' if single else 'dual',pair_id=pair,feature_a=fa,feature_b=fb,
            resolution=r,cells=json.dumps(cells),direction=direction,target_id=f'target_{horizon}__raw__{grid}',time_group=-1))
    f=pd.DataFrame(rows);f.to_parquet(OUT/f'nominations_{grid}.parquet',index=False);return f

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('grid',choices=['intraday_5m','preclose_1555']);args=p.parse_args()
    engine.OUT=OUT;engine.ENTRY_LAG_MINUTES=0;engine.FULL_YEAR=True;engine.EXIT_LAST_MINUTE=True
    engine.COMPLETED_CLOSE_REFERENCES=True;engine.SAVE_ELIGIBLE_EVENTS=True;engine.EXIT_LAG_MINUTES=1 if args.grid=='preclose_1555' else 0;engine.nominate=nominate
    engine.replay_grid(args.grid)
    f=pd.read_parquet(OUT/f'replay_{args.grid}.parquet')
    print(f[f.bps.isin([0,5])][['candidate_id','bps','trades','mean_trade_bps','additive_pct','positive_months','days','symbols','ex_top5_mean_bps']].to_string(index=False))
