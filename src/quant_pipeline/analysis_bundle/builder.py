from __future__ import annotations
import json, shutil
from pathlib import Path
import duckdb

class AnalysisBundleBuilder:
    NAMES=("feature_registry","target_registry","single_summary","dual_summary","surface_cells","trial_ledger","specialist_summary","edge_registry")
    def __init__(self,bundle_dir:Path): self.bundle_dir=Path(bundle_dir); self.bundle_dir.mkdir(parents=True,exist_ok=True)
    def collect(self,run_dir:Path):
        for name in self.NAMES:
            src=Path(run_dir)/f"{name}.parquet"
            if src.exists(): shutil.copy2(src,self.bundle_dir/src.name)
    def build_duckdb(self):
        path=self.bundle_dir/"research.duckdb"
        if path.exists(): path.unlink()
        con=duckdb.connect(str(path))
        try:
            for name in self.NAMES:
                p=self.bundle_dir/f"{name}.parquet"
                if p.exists():
                    path_sql=str(p).replace("'","''")
                    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path_sql}')")
        finally: con.close()
        return path
    def write_manifest(self,payload):
        p=self.bundle_dir/"bundle_manifest.json"; p.write_text(json.dumps(payload,indent=2,sort_keys=True,default=str),encoding="utf-8"); return p
