"""Full annual quotes for causal HF intentions and fixed, prior-only ranking control."""
import argparse,json
import pandas as pd
import competition_fresh_quotes as engine
import competition_fresh_risk as risk
from competition_fresh_search import OUT

DEST=OUT/'intraday_rebound_120_causal'
def quotes():
    engine.OUT=DEST;engine.Q=OUT/'policy_quotes';engine.RUN_ALLOCATION=False;engine.run()

def allocate():
    pool=pd.read_parquet(DEST/'policy_quote_pool.parquet');d=pd.read_parquet(DEST/'policy_quote_outcomes.parquet')
    policies=pd.read_parquet(DEST/'nomination_policies.parquet');frames=[]
    for ranked in [False,True]:
        ids=policies.loc[policies.nomination_ranked==ranked,'observation_id']
        g=pool[pool.observation_id.isin(ids)].merge(d,on='order_id',validate='one_to_many')
        g['slots']=10;g['ranked']=ranked;g['selection_ts']=g.entry_ts;frames.append(g)
    f=pd.concat(frames,ignore_index=True)
    for c in ['entry_fill_ts','exit_fill_ts']:f[c]=pd.to_datetime(f[c],utc=True).dt.as_unit('ns')
    f.to_parquet(DEST/'policy_quote_attempts.parquet',index=False)
    print('ANNUAL POLICY ATTEMPTS',len(f),'unpriced',int((~f.priced).sum()),flush=True)
    risk.OUT=DEST;risk.analyze()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['quotes','allocate','paths']);a=p.parse_args()
    if a.stage=='paths':risk.OUT=DEST;risk.extract()
    else:globals()[a.stage]()
