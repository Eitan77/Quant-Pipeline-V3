from pathlib import Path
import importlib.util,os
import numpy as np, pandas as pd, pytest
from quant_pipeline.contracts import FeatureSpec
from quant_pipeline.discovery import plan_pairs,scan_surface_cpu
from quant_pipeline.features.state_store import build_multi_bins,pack_multi_bins,unpack_bins
from quant_pipeline.forensics.opportunities import build_episodes
from quant_pipeline.governance import PeriodGuard
from quant_pipeline.errors import SealedDataViolation

def feature(fid,canonical=True): return FeatureSpec(fid,fid,"f","g",canonical,("x",),1,"bar_end","raw")
def test_singles_do_not_gate_canonical_pairs():
    assert [p.pair_id for p in plan_pairs([feature("weak"),feature("other"),feature("variant",False)])]==["other__X__weak"]
def test_cpu_surface_keeps_both_signs():
    a=np.array([0,0,1,1],np.uint8); b=np.array([0,1,0,1],np.uint8); y=np.array([5,-4,-3,2.]); s=scan_surface_cpu(state_a=a,state_b=b,target_bps=y,target_valid=np.ones(4,bool),resolution=2)
    assert s.means_bps.max()==5 and s.means_bps.min()==-4
def test_v2_bin_tie_parity():
    if not os.getenv("QP_V2_REFERENCE_ROOT"): pytest.skip("QP_V2_REFERENCE_ROOT not configured")
    path=Path(os.environ["QP_V2_REFERENCE_ROOT"])/"src/quant_pipeline/alpha_discovery/cache/rank_store.py"
    spec=importlib.util.spec_from_file_location("v2_rank_store",path); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    x=np.array([[1.,2.],[1.,np.nan],[3.,0.],[2.,4.],[2.,4.],[5.,1.]],np.float32); codes=np.array([0,0,0,1,1,1])
    ours=build_multi_bins(x,codes)
    theirs=mod.build_multi_bins(x,codes)
    for r in (3,5,10): np.testing.assert_array_equal(ours[r],theirs[r])
    packed=pack_multi_bins(ours)
    for r in (3,5,10): np.testing.assert_array_equal(unpack_bins(packed,r),ours[r])
def test_sealed_period_rejected():
    c={"periods":{"discovery":{"start":"2025-05-01","end":"2026-04-30"},"replication":{"start":"2026-05-01","end":"2026-08-31"},"final_holdout":{"start":"2026-09-01"}}}; g=PeriodGuard.from_config(c)
    with pytest.raises(SealedDataViolation): g.authorize_discovery_range("2025-05-01","2026-05-01")
def test_episode_count_differs_from_active_rows():
    n=6; eps=build_episodes(obs_id=np.arange(n),security_id=np.zeros(n),session_id=np.zeros(n),security_session_seq=np.arange(n),decision_ts_ns=np.arange(n),active=np.array([1,1,1,0,1,1],bool))
    assert sum(x.observation_count for x in eps)==5 and len(eps)==2
