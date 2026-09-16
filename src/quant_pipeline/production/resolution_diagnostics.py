from pathlib import Path
from quant_pipeline.production.outputs import load_duals

def build_resolution_diagnostics(*,run_root:Path,research:dict)->Path:
    out=Path(run_root)/"v3_diagnostics"; out.mkdir(parents=True,exist_ok=True); destination=out/"dual_resolution_summary.parquet"; load_duals(run_root,research["resolutions"]).to_parquet(destination,index=False); return destination
