"""Same signal/ranking, same governed comparison pool, only earlier scheduled exit."""
import json,shutil
import pandas as pd
import competition_fresh_quotes as quotes
import competition_fresh_risk as risk
from competition_fresh_search import OUT

if __name__=='__main__':
    sub=OUT/'same_day_comparison';sub.mkdir(exist_ok=True)
    pool=pd.read_parquet(OUT/'policy_pool.parquet');pool['exit_ts']=pool.first_session_exit_ts;pool['exit_price']=pool.first_session_exit_price
    assert pool.exit_price.gt(0).all()
    pool['target_id']='same_day_shared_governed_pool';pool.to_parquet(sub/'policy_pool.parquet',index=False)
    shutil.copyfile(OUT/'policy_endpoint_bars.parquet',sub/'policy_endpoint_bars.parquet')
    (sub/'scope.json').write_text(json.dumps({'fees':0,'same_signal_same_rank':True,'earlier_exit_only':True,'shared_governed_pool':len(pool),
        'not_full_native_one_day_signal_pool':True,'complete_quote_replay_of_shared_pool':True,'out_of_sample_accessed':False},indent=2))
    quotes.OUT=sub;quotes.Q=OUT/'policy_quotes';quotes.run()
    risk.OUT=sub;risk.PATH_FILE=OUT/'policy_minute_paths.parquet';risk.analyze()
