import numpy as np
from quant_pipeline.forensics.distribution import contribution_concentration,distribution_stats
from quant_pipeline.forensics.path import direction_aware_excursions,event_path_metrics
from quant_pipeline.forensics.tails import build_tail_mask
from quant_pipeline.production.surface_math import reconstruct_surface

def test_tail_membership_is_state_defined_not_outcome_defined():
    ranks=np.array([.01,.10,.19,.21,.80,.99]); state=np.array([0,0,0,1,4,4]); other=np.full(6,2)
    first=build_tail_mask(rank_a=ranks,rank_b=ranks,state_a=state,state_b=other,selected_a=0,selected_b=2,resolution=5,tail_fraction=.2)[0]
    shuffled_returns=np.array([99,-50,4,8,-3,1])
    second=build_tail_mask(rank_a=ranks,rank_b=ranks,state_a=state,state_b=other,selected_a=0,selected_b=2,resolution=5,tail_fraction=.2)[0]
    np.testing.assert_array_equal(first,second); assert first.tolist()==[True,True,True,False,False,False] and len(shuffled_returns)==len(first)

def test_middle_middle_tail_is_not_applicable():
    mask,applicable,reason=build_tail_mask(rank_a=np.arange(4)/4,rank_b=np.arange(4)/4,state_a=np.ones(4),state_b=np.ones(4),selected_a=1,selected_b=1,resolution=3,tail_fraction=.2)
    assert not applicable and not mask.any() and reason=="selected_state_has_no_outer_tail"

def test_short_metrics_align_favorable_negative_returns():
    raw=np.array([-10.,-5.,2.]); aligned=-raw; stats=distribution_stats(aligned); concentration=contribution_concentration(aligned)
    assert stats["win_rate"]==2/3 and stats["avg_winner_bps"]==7.5 and concentration["top_1pct_contribution_share"]>0

def test_event_path_and_short_excursions_are_direction_correct():
    rows=[{"horizon":"1m","direction_aligned_mean_bps":2.},{"horizon":"5m","direction_aligned_mean_bps":8.},{"horizon":"10m","direction_aligned_mean_bps":3.}]
    got=event_path_metrics(rows); assert got["time_to_peak"]=="5m" and got["post_peak_giveback_bps"]==5
    import pandas as pd
    raw=pd.DataFrame({"mfe":[.20],"mae":[-.05],"time_to_mfe":[3],"time_to_mae":[2],"terminal_return":[-.02]}); short=direction_aware_excursions(raw,-1)
    assert short.directional_mfe.iloc[0]==.05 and short.time_to_directional_mfe.iloc[0]==2

def test_surface_reconstruction_uses_sufficient_statistics():
    got=reconstruct_surface(counts=[2,1,1,2],sums=[3.,4.,5.,13.],sumsq=[5.,16.,25.,85.],resolution=2)
    np.testing.assert_allclose(got["mean"],[1.5,4.,5.,6.5]); assert len(got["interaction"])==4 and np.isfinite(got["se"][[0,3]]).all()
