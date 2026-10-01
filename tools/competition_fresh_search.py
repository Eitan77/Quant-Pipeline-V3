"""Fresh canonical discovery over every economically eligible sub-48h horizon."""
import argparse,json
from pathlib import Path
import competition_full_year as mapper

OUT=mapper.ROOT/'research/fresh_under48h_consistency_20260930';OUT.mkdir(exist_ok=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['map','annotate']);p.add_argument('--grid',choices=mapper.GRIDS)
    args=p.parse_args();mapper.OUT=OUT
    if args.stage=='map':
        filt="target_id LIKE '%__raw__%'"
        if args.grid=='daily_close':filt="target_id IN ('target_1d__raw__daily_close','target_2d__raw__daily_close')"
        mapper.broad(args.grid,filt)
    else:mapper.annotate(valid_components_only=True)
    (OUT/(f'scope_{args.grid}.json' if args.stage=='map' else 'scope.json')).write_text(json.dumps({'discovery':'2025-05-01 through 2026-04-30','out_of_sample_accessed':False,
        'objective':'Profitable, high independent sample, consistent returns, defensible execution.',
        'hold_limit_seconds_exclusive':172800,'grids':mapper.GRIDS,'daily_horizons':[1,2],
        'two_day_horizon':'Keep only actual elapsed holds under 48h; exclude weekend/holiday crossings exceeding this.',
        'previous_strategy_rankings_used':False,'reuse':'Code, canonical immutable data, quote caches only.',
        'research_unit':'Pair-target-resolution-region; separate edge/lift/N/frequency/contribution.',
        'selection':'Simple states and coherent regions; reject fragile bases rather than stack filters.',
        'execution_offsets_per_side':[-1,0,1,2,3,4,5]},indent=2))
