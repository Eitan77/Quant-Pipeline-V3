"""Conservative closing replay: no same-window cash reuse, five-second activation."""
import json,shutil
import pandas as pd
import competition_fresh_quotes as quotes
import competition_fresh_risk as risk
from competition_fresh_search import OUT

if __name__=='__main__':
    source=OUT/'close_entry_comparison';sub=OUT/'close_entry_conservative';sub.mkdir(exist_ok=True)
    for name in ['policy_pool.parquet','policy_endpoint_bars.parquet']:shutil.copyfile(source/name,sub/name)
    (sub/'scope.json').write_text(json.dumps({'same_signal_prices_ranking':True,'selection':'Select new entries before any same-minute exit fills. Reuse none of their proceeds or slots in that window.',
        'entry_activation_seconds':5,'exit_activation_seconds':5,'fees':0,'out_of_sample_accessed':False},indent=2))
    quotes.OUT=sub;quotes.Q=OUT/'policy_quotes';quotes.ACTIVATION_SECONDS=5;quotes.EXIT_ACTIVATION_SECONDS=5;quotes.SELECTION_DELAY_SECONDS=0;quotes.EXIT_LIMIT_TTL_SECONDS=54;quotes.FORCE_SECONDS=56;quotes.run()
    risk.OUT=sub;risk.PATH_FILE=OUT/'policy_minute_paths.parquet';risk.analyze()
