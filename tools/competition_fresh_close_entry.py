"""Path-led alternative: same lagged state/rank, close entry and next close exit."""
import json,shutil
import pandas as pd
import competition_fresh_quotes as quotes
import competition_fresh_risk as risk
from competition_fresh_search import OUT

if __name__=='__main__':
    sub=OUT/'close_entry_comparison';sub.mkdir(exist_ok=True)
    f=pd.read_parquet(OUT/'policy_pool.parquet');f=f[~f.calendar_same_day].copy()
    f['entry_ts']=f.first_session_exit_ts;f['entry_price']=f.first_session_exit_price
    f=f.rename(columns={'entry_reference_bar':'original_open_reference_bar'})
    f['entry_reference_provenance']='first-session completed close; cached source availability <= planned close minute'
    assert ((f.exit_ts-f.entry_ts)<pd.Timedelta(days=2)).all()
    f.to_parquet(sub/'policy_pool.parquet',index=False)
    shutil.copyfile(OUT/'policy_endpoint_bars.parquet',sub/'policy_endpoint_bars.parquet')
    (sub/'scope.json').write_text(json.dumps({'same_lagged_signal_same_rank':True,'mechanism':'Avoid losing entry-session intraday exposure; retain next-session carry.',
        'no_friday_to_monday_holds':True,'selection_delay_seconds':4,'entry_order_activation_seconds':5,'exit_order_activation_seconds':1,
        'exit_limit_cutoff_seconds':54,'force_execution_seconds':56,'emergency_close':'Cancel at second 54, assume cancellation acknowledgement by 55 and liquidation at fresh bid from second 56. Cap forced price at exit limit to avoid optimistic in-flight cancellation pricing.',
        'capacity':'Only exits already completed by selection time release cash/slots. New buy orders begin one second later.',
        'fees':0,'out_of_sample_accessed':False},indent=2))
    quotes.OUT=sub;quotes.Q=OUT/'policy_quotes';quotes.ACTIVATION_SECONDS=5;quotes.EXIT_ACTIVATION_SECONDS=1;quotes.SELECTION_DELAY_SECONDS=4;quotes.EXIT_LIMIT_TTL_SECONDS=54;quotes.FORCE_SECONDS=56;quotes.run()
    risk.OUT=sub;risk.PATH_FILE=OUT/'policy_minute_paths.parquet';risk.analyze()
