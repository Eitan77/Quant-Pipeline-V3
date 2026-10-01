"""Simple evidence-led two-session dislocation hypotheses and their controls."""
import json
import pandas as pd
import competition_under2d as engine
from competition_fresh_search import OUT

def nominate(grid):
    rows=[]
    definitions=[
        ('trend_dislocation','a2cfbdd1248d9ad6c2d1d20a','ema_distance__20d__raw__daily_close','return_skip_recent_63d_ex_5d__63d__raw__daily_close',5,[4],2),
        ('trend_dislocation_same_day','a2cfbdd1248d9ad6c2d1d20a','ema_distance__20d__raw__daily_close','return_skip_recent_63d_ex_5d__63d__raw__daily_close',5,[4],1),
        ('trend_dislocation_broad','a2cfbdd1248d9ad6c2d1d20a','ema_distance__20d__raw__daily_close','return_skip_recent_63d_ex_5d__63d__raw__daily_close',3,[2],2),
        ('trend_dislocation_fine','a2cfbdd1248d9ad6c2d1d20a','ema_distance__20d__raw__daily_close','return_skip_recent_63d_ex_5d__63d__raw__daily_close',10,[8,9,18,19],2),
        ('parent_ema','ema_distance__20d__raw__daily_close','ema_distance__20d__raw__daily_close','',5,[0],2),
        ('parent_old_trend','return_skip_recent_63d_ex_5d__63d__raw__daily_close','return_skip_recent_63d_ex_5d__63d__raw__daily_close','',5,[4],2),
        ('activity_drawdown','944e9dc7de8fc0568c5f857f','positive_return_sum__20d__raw__daily_close','window_max_drawdown__20d__raw__daily_close',10,[90],2),
        ('activity_drawdown_region','944e9dc7de8fc0568c5f857f','positive_return_sum__20d__raw__daily_close','window_max_drawdown__20d__raw__daily_close',10,[80,81,90,91],2),
        ('activity_drawdown_coarse','944e9dc7de8fc0568c5f857f','positive_return_sum__20d__raw__daily_close','window_max_drawdown__20d__raw__daily_close',5,[20],2),
        ('market_low_reclaim','b3e2ab206855be38f7a5798c','market_downside_vol__20d__raw__daily_close','prior_low_reclaim_strength__20d__raw__daily_close',10,[32,33,42,43],2),
        ('jump_balance','89ce8084267f6c82b4390d04','jump_variance_share__20d__raw__daily_close','positive_jump_fraction__20d__raw__daily_close',10,[33],2)]
    for name,pair,fa,fb,r,cells,hold in definitions:
        rows.append(dict(candidate_id=name,grid=grid,state_kind='dual' if fb else 'single',pair_id=pair,feature_a=fa,feature_b=fb,
            resolution=r,cells=json.dumps(cells),direction=1,target_id=f'target_{hold}d__raw__daily_close',time_group=-1))
    f=pd.DataFrame(rows);f.to_parquet(OUT/'nominations_daily_close.parquet',index=False);return f

if __name__=='__main__':
    import exchange_calendars as xc
    schedule=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    close_col='close' if 'close' in schedule else 'market_close'
    engine.SESSION_CLOSES={pd.Timestamp(day).strftime('%Y-%m-%d'):pd.Timestamp(stamp).tz_localize('UTC') if pd.Timestamp(stamp).tzinfo is None else pd.Timestamp(stamp) for day,stamp in schedule[close_col].items()}
    engine.OUT=OUT;engine.ENTRY_LAG_MINUTES=0;engine.FULL_YEAR=True;engine.EXIT_LAST_MINUTE=True
    engine.COMPLETED_CLOSE_REFERENCES=True;engine.SAVE_ELIGIBLE_EVENTS=True;engine.nominate=nominate
    engine.replay_grid('daily_close')
    f=pd.read_parquet(OUT/'replay_daily_close.parquet')
    print(f[f.bps.isin([0,5])][['candidate_id','bps','trades','mean_trade_bps','additive_pct','max_dd_pct','positive_months','days','symbols','top5_profit_share','ex_top5_mean_bps','max_hold_hours']].to_string(index=False))
