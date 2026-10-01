"""One operational stress: five seconds to activate each unchanged limit order."""
import json,shutil
import competition_fresh_quotes as quotes
import competition_fresh_risk as risk
from competition_fresh_search import OUT

if __name__=='__main__':
    sub=OUT/'latency_5sec';sub.mkdir(exist_ok=True)
    for name in ['policy_pool.parquet','policy_endpoint_bars.parquet']:shutil.copyfile(OUT/name,sub/name)
    (sub/'scope.json').write_text(json.dumps({'same_signal_same_rank_same_prices':True,'order_activation_delay_seconds':5,'fees':0,'out_of_sample_accessed':False},indent=2))
    quotes.OUT=sub;quotes.Q=OUT/'policy_quotes';quotes.ACTIVATION_SECONDS=5;quotes.run()
    risk.OUT=sub;risk.PATH_FILE=OUT/'policy_minute_paths.parquet';risk.analyze()
