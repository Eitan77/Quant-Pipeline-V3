"""Bounded production evidence loop, without source-data access."""
from __future__ import annotations

import json
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pandas as pd

from quant_pipeline.production.coverage import execute_coverage,plan_coverage
from quant_pipeline.production.evidence_identity import file_digest
from quant_pipeline.production.evidence_store import publish_evidence
from quant_pipeline.production.research_service import ResearchService


def test_publication_coverage_query_and_search(tmp_path):
    root=tmp_path/"run"
    grid="intraday_5m"
    observations=pd.DataFrame({"observation_id":np.arange(8,dtype=np.int64),
                               "security_id":["A","A","B","B"]*2,
                               "session_date":["2025-05-01"]*4+["2025-05-02"]*4,
                               "decision_ts":pd.to_datetime(["2025-05-01 14:30Z","2025-05-01 15:30Z",
                                                              "2025-05-01 14:30Z","2025-05-01 15:30Z",
                                                              "2025-05-02 14:30Z","2025-05-02 15:30Z",
                                                              "2025-05-02 14:30Z","2025-05-02 15:30Z"])})
    obs_path=root/"cache"/"features"/grid/"observations.parquet"
    obs_path.parent.mkdir(parents=True)
    observations.to_parquet(obs_path,index=False)
    obs_hash=sha256(observations.observation_id.to_numpy().tobytes()).hexdigest()
    bin_dir=root/"cache"/"bins"/"packed"/grid
    bin_dir.mkdir(parents=True)
    bins=np.zeros((8,2),np.uint8)
    np.save(bin_dir/"block.npy",bins)
    (bin_dir/"block.json").write_text(json.dumps({"columns":["a","b"],"shape":[8,2],
        "sha256":file_digest(bin_dir/"block.npy"),"observation_id_sha256":obs_hash,
        "observations_sha256":file_digest(obs_path),
        "feature_definition_hashes":{"a":"ha","b":"hb"}}))
    target_dir=root/"cache"/"target_store"/grid
    target_dir.mkdir(parents=True)
    np.save(target_dir/"aligned.npy",np.array([8,-8,-8,8]*2,dtype=np.float32).reshape(-1,1)/10000)
    np.save(target_dir/"aligned.observations.npy",observations.observation_id.to_numpy())
    (target_dir/"aligned.json").write_text(json.dumps({"columns":["t"],"sha256":file_digest(target_dir/"aligned.npy")}))
    plan_dir=root/"cache"/"pair_plans"
    plan_dir.mkdir(parents=True)
    np.savez_compressed(plan_dir/f"{grid}.npz",feature_ids=np.array(["a","b"]),
                        pair_ids=np.array(["a-b"]),left=np.array([0]),right=np.array([1]))
    scope={"grids":[grid],"features":[{"id":"a","grid":grid,"definition_hash":"ha"},
                                      {"id":"b","grid":grid,"definition_hash":"hb"}],
           "targets":[{"id":"t","grid":grid,"definition_hash":"ht"}]}
    run=SimpleNamespace(root=root,config=SimpleNamespace(stability={"chronological_folds":2}))
    path=publish_evidence(run,scope,{"scan-singles":"stage"},
                          {"evidence":{"mandatory_groupings":[["security","time_bucket"]]}})
    manifest=json.loads(path.read_text())
    plan=plan_coverage(root,manifest,[3],max_state_bytes=1_000_000)
    status=execute_coverage(root,manifest,plan,device="cpu",row_chunk=3,max_state_bytes=1_000_000)
    assert status["mandatory_coverage_complete"] and status["planned_tasks"]==2
    service=ResearchService({"run_root":str(tmp_path),"duckdb_memory_limit_gb":1,"duckdb_threads":1},"run")
    page=service.query({"grid":grid,"grouping":"security_time_bucket","state_kind":"dual",
                        "pair_id":"a-b","target_id":"t","resolution":3,"group_id":0})
    assert page["status"]=="available" and page["rows"][0]["n"]==4
    result=service.search({"grid":grid,"grouping":"security_time_bucket","state_kind":"dual","limit":10})
    assert result["status"]=="complete" and result["rows"]>0
