from pathlib import Path
from quant_pipeline.features import load_pack
def test_builtin_pack_loads_without_core_edits():
    root=Path(__file__).resolve().parents[2];meta,registry,impl=load_pack(root/"feature_packs/builtin/v2_port/pack.yaml");assert meta["pack_id"]=="builtin_v2_port" and callable(registry) and impl.__name__=="FeatureBuilder"

