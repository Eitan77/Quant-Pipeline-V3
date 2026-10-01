from types import SimpleNamespace
import numpy as np
import pandas as pd
from quant_pipeline.alpha_discovery.features.base import FeatureBuilder


def test_ema_distance_is_row_order_invariant_and_causal():
    timestamps=pd.date_range('2026-01-01',periods=6,tz='UTC')
    frame=pd.DataFrame({'security_id':['A']*6+['B']*6,'decision_ts':list(timestamps)*2,
                        'session_date':list(timestamps.date)*2,'close':[100,102,98,103,104,500,50,51,49,52,51,300]})
    frame['open']=frame['high']=frame['low']=frame.close
    frame['volume']=100
    spec=SimpleNamespace(decision_grid='daily_close',scale=SimpleNamespace(kind='days',value=20),
                         concept_id='ema_distance',parameters={},feature_id='ema',representation='raw')

    def calculate(f):
        builder=FeatureBuilder(f)
        result=builder.frame[['security_id','decision_ts']].copy()
        result['ema']=builder.build(spec)
        return result.set_index(['security_id','decision_ts']).sort_index().ema

    expected=calculate(frame)
    shuffled=calculate(frame.sample(frac=1,random_state=8).reset_index(drop=True))
    pd.testing.assert_series_equal(shuffled,expected)
    previous=frame[frame.decision_ts<timestamps[-1]]
    pd.testing.assert_series_equal(calculate(previous),expected.loc[(slice(None),slice(None,timestamps[-2]))])
    assert np.isclose(expected.loc[('A',timestamps[1])],102/(100+2*(2/21))-1)
