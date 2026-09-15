import json
from pathlib import Path
import duckdb,pyarrow.parquet as pq,yaml
from quant_pipeline.app import run_pipeline
from quant_pipeline.config import load_research_config,load_machine_config
ROOT=Path(__file__).resolve().parents[2]
def test_end_to_end_and_resume(tmp_path):
    r=load_research_config(ROOT/"configs/research/smoke.yaml"); r["run_name"]="pytest_smoke"
    m=load_machine_config(ROOT/"configs/machines/local.yaml"); m={**m,"cache_root":str(tmp_path/"cache"),"run_root":str(tmp_path/"runs"),"scratch_root":str(tmp_path/"scratch"),"duckdb_temp":str(tmp_path/"scratch/duckdb")}
    run_pipeline(research=r,machine=m); d=Path(m["run_root"])/r["run_name"]
    manifest=json.loads((d/"run_manifest.json").read_text()); assert not manifest["replication_accessed"] and manifest["canonical_trial_coverage"]=="reconciled"
    dual=pq.read_table(d/"dual_summary.parquet").to_pandas(); assert set(dual.resolution)=={3,5,10}; assert (dual.direction<0).any() and (dual.direction>0).any()
    ledger=pq.read_table(d/"trial_ledger.parquet").to_pandas(); assert len(ledger)==3*3*3 and set(ledger.status)=={"executed"}
    con=duckdb.connect(str(d/"analysis_bundle/research.duckdb"),read_only=True); assert con.execute("select count(*) from dual_summary").fetchone()[0]==27; con.close()
    run_pipeline(research=r,machine=m,resume=True); status=json.loads((d/"STATUS.json").read_text()); assert len(status["reused_stages"])==13

