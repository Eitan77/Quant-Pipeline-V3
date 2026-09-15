from datetime import datetime,timezone
from pathlib import Path
import json,pyarrow.parquet as pq,pytest
from quant_pipeline.app import run_pipeline
from quant_pipeline.candidates.service import export_candidate_sip,promote_replication
from quant_pipeline.config import load_machine_config,load_research_config
from quant_pipeline.errors import SealedDataViolation
ROOT=Path(__file__).resolve().parents[2]

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root=tmp_path_factory.mktemp("candidate-services"); research=load_research_config(ROOT/"configs/research/smoke.yaml"); research["run_name"]="candidate_service_smoke"; base=load_machine_config(ROOT/"configs/machines/local.yaml"); machine={**base,"cache_root":str(root/"cache"),"run_root":str(root/"runs"),"scratch_root":str(root/"scratch"),"duckdb_temp":str(root/"scratch/duckdb")}; run_pipeline(research=research,machine=machine); run=Path(machine["run_root"])/research["run_name"]; candidate=pq.read_table(run/"edge_registry.parquet").to_pylist()[0]; return machine,run,candidate

def test_sip_export_accepts_candidate_id(built):
    machine,_,candidate=built; path=export_candidate_sip(candidate["candidate_id"],machine); assert path.exists() and pq.read_table(path).num_rows>0

def test_replication_requires_exact_explicit_authorization(built):
    machine,_,candidate=built
    with pytest.raises(SealedDataViolation): promote_replication(candidate["candidate_id"],machine)

def test_authorized_promotion_preserves_frozen_definition(built):
    machine,run,candidate=built; auth=run/"authorizations"/f"{candidate['candidate_id']}.json"; auth.parent.mkdir(); auth.write_text(json.dumps({"candidate_id":candidate["candidate_id"],"definition_hash":candidate["definition_hash"],"scope":"sealed_replication","authorized_by":"integration-test","authorized_at_utc":datetime.now(timezone.utc).isoformat()})); request=json.loads(promote_replication(candidate["candidate_id"],machine).read_text()); assert request["definition_hash"]==candidate["definition_hash"] and request["state_payload"]==candidate["state_payload"]
