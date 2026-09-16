from hashlib import sha256
from pathlib import Path
import os,pytest
import numpy as np,pandas as pd
from quant_pipeline.alpha_discovery.cache.rank_store import build_multi_bins
from quant_pipeline.alpha_discovery.data.corporate_actions import build_split_consistent_view
from quant_pipeline.alpha_discovery.data.universe import apply_point_in_time_universe

ROOT=Path(__file__).resolve().parents[2]
V2_VALUE=os.getenv("QP_V2_REFERENCE_ROOT")
V2=Path(V2_VALUE) if V2_VALUE else None
MODULES=[
 "models.py","registry.py","config.py","data/universe.py","data/corporate_actions.py","data/panel.py","data/source.py","data/snapshot.py",
 "features/base.py","features/formulas.py","targets/builder.py","cache/rank_store.py","governance/access.py","execution/quote_replay.py"
]
def digest(p):return sha256(p.read_bytes()).hexdigest()
def test_authoritative_ported_modules_are_byte_identical():
    if V2 is None: pytest.skip("QP_V2_REFERENCE_ROOT not configured")
    for rel in MODULES:
        assert digest(ROOT/"src/quant_pipeline/alpha_discovery"/rel)==digest(V2/"src/quant_pipeline/alpha_discovery"/rel),rel
def test_pit_and_price_fixtures():
    raw=pd.DataFrame({"security_id":["s1","s1"],"session_date":pd.to_datetime(["2025-01-02","2025-01-03"]).date,"open":[100.,102.],"high":[103.,104.],"low":[99.,100.],"close":[102.,103.],"vwap":[101.,102.]})
    factor=pd.DataFrame({"security_id":["s1","s1"],"session_date":raw.session_date,"split_factor":[2.,1.]})
    got=build_split_consistent_view(raw,factor); np.testing.assert_allclose(got.research_close,[51.,103.])
    membership=pd.DataFrame({"security_id":["s1","s1"],"session_date":raw.session_date,"in_universe":[True,False]}); master=pd.DataFrame({"security_id":["s1"]})
    assert len(apply_point_in_time_universe(raw,membership,master))==1
def test_average_tie_bin_fixture():
    values=np.array([[1.],[1.],[3.],[2.],[2.],[5.]],np.float32); codes=np.array([0,0,0,1,1,1]); out=build_multi_bins(values,codes)
    assert set(out)=={3,5,10} and all(x.dtype==np.int8 for x in out.values())
