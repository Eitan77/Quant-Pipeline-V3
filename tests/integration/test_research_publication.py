"""Bounded production evidence loop, without source-data access."""
from __future__ import annotations

import json
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_pipeline.production.coverage import execute_coverage,plan_coverage
from quant_pipeline.production.evidence_identity import file_digest
from quant_pipeline.production.evidence_store import publish_evidence
from quant_pipeline.production.research_service import ResearchService
from quant_pipeline.production.compatibility_moments import derive_compatibility


def test_publication_coverage_query_and_search(tmp_path,monkeypatch):
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
                          {"evidence":{"mandatory_groupings":[["security"],["fold"],["security","time_bucket"]]}})
    manifest=json.loads(path.read_text())
    plan=plan_coverage(root,manifest,[3],max_state_bytes=1_000_000)
    task_ids=[json.loads(line)["task"]["task_id"] for line in (root/plan["path"]).read_text().splitlines()]
    same_scope=plan_coverage(root,manifest,[3],max_state_bytes=2_000_000)
    assert same_scope["stage_id"]==plan["stage_id"]
    assert task_ids==[json.loads(line)["task"]["task_id"] for line in (root/plan["path"]).read_text().splitlines()]
    fused_plan=plan_coverage(root,manifest,[3,5,10],max_state_bytes=2_000_000)
    fused_rows=[json.loads(line) for line in (root/fused_plan["path"]).read_text().splitlines()]
    assert fused_plan["task_count"]==3*plan["task_count"]
    assert [row["task"]["resolution"] for row in fused_rows[:3]]==[3,5,10]
    changed=json.loads(json.dumps(manifest));changed["grids"][grid]["groups"]["security"]["definition_id"]="changed"
    changed_plan=plan_coverage(root,changed,[3],max_state_bytes=2_000_000)
    assert changed_plan["stage_id"]!=plan["stage_id"]
    plan=plan_coverage(root,manifest,[3],max_state_bytes=1_000_000)
    (root/"evidence"/"storage_plan.json").write_text(json.dumps({"cache_bytes":1}))
    calls=0
    def interrupted():
        nonlocal calls
        calls+=1
        return calls>7
    with pytest.raises(InterruptedError):
        execute_coverage(root,manifest,plan,device="cpu",row_chunk=3,max_state_bytes=1_000_000,
                         cancelled=interrupted)
    status=execute_coverage(root,manifest,plan,device="cpu",row_chunk=3,max_state_bytes=1_000_000)
    assert status["mandatory_coverage_complete"] and status["planned_tasks"]==6
    assert status["recomputable_tasks"]==6
    derived=derive_compatibility(root,plan,manifest,minimum=1,expected_folds=2,
                                 device="cpu",row_chunk=3,max_state_bytes=1_000_000)
    assert derived["security"]["rows"]==derived["fold"]["rows"]==1
    service=ResearchService({"run_root":str(tmp_path),"duckdb_memory_limit_gb":1,"duckdb_threads":1},"run")
    page=service.query({"grid":grid,"grouping":"security_time_bucket","state_kind":"dual",
                        "pair_id":"a-b","target_id":"t","resolution":3,"group_id":0})
    assert page["status"]=="available" and page["rows"][0]["n"]==4
    union=service.query({"grid":grid,"grouping":"security_time_bucket","state_kind":"dual",
                         "pair_id":"a-b","target_id":"t","resolution":3,"group_id":0,
                         "cell_union":[0,1],"include_distinct_sessions":True})
    assert union["rows"][0]["n"]==4 and union["rows"][0]["distinct_sessions"]==2
    result=service.search({"grid":grid,"grouping":"security_time_bucket","state_kind":"dual","limit":10})
    assert result["status"]=="complete" and result["rows"]>0
    diagnostic=service.inspect({"kind":"symbol","grid":grid,"state_kind":"dual","pair_id":"a-b",
                                "target_id":"t","resolution":3,"cells":[0]})
    assert diagnostic["status"]=="complete"
    neighbor=service.experiment({"kind":"neighbor","grid":grid,"grouping":"security_time_bucket",
                                 "state_kind":"dual","pair_ids":["a-b"],"target_id":"t","resolution":3})
    assert neighbor["status"]=="complete" and neighbor["children"]==1
    ledger=observations[["observation_id","security_id","session_date","decision_ts"]].copy()
    ledger["target_id"]="t";ledger["target_basis"]="raw"
    ledger["entry_ts"]=ledger.decision_ts+pd.Timedelta(minutes=5)
    ledger["exit_ts"]=ledger.decision_ts+pd.Timedelta(minutes=20)
    ledger["entry_price"]=100.0;ledger["exit_price"]=101.0;ledger["beta_prior"]=0.0
    ledger_path=root/"cache"/"targets"/f"{grid}.parquet"
    ledger_path.parent.mkdir(parents=True);ledger.to_parquet(ledger_path,index=False)
    from quant_pipeline.production import replay as replay_module
    real_read=pd.read_parquet
    monkeypatch.setattr(replay_module.pd,"read_parquet",lambda path,**kw:
        pd.DataFrame({"security_id":["A","B"],"symbol":["AAA","BBB"]}) if str(path).endswith("security_master.parquet") else real_read(path,**kw))
    prices=pd.Series(100.0,index=pd.to_datetime(["2025-05-01 14:36Z","2025-05-01 15:36Z",
                                                   "2025-05-02 14:36Z","2025-05-02 15:36Z"]))
    monkeypatch.setattr(replay_module,"_raw_opens",lambda machine,signals,**kw:{"A":prices,"B":prices})
    replay=service.experiment({"kind":"backtest","grid":grid,"state_kind":"dual","pair_id":"a-b",
                               "target_id":"t","resolution":3,"cells":[0],"direction":1,"return_basis":"raw"})
    assert replay["status"]=="complete"
    from quant_pipeline.production.research_jobs import JobStore
    from quant_pipeline.production.research_cli import _worker
    store=JobStore(root/"research"/"jobs.sqlite")
    jobs=[store.submit({"kind":kind,"payload":payload}) for kind,payload in [
        ("subgroup_search",{"grid":grid,"grouping":"security","state_kind":"dual","pair_id":"a-b","target_id":"t"}),
        ("diagnostic",{"kind":"symbol","grid":grid,"state_kind":"dual","pair_id":"a-b","target_id":"t","resolution":3,"cells":[0]}),
        ("neighbor_scan",{"kind":"neighbor","grid":grid,"grouping":"security","pair_ids":["a-b"],"target_id":"t"}),
        ("backtest",{"kind":"backtest","grid":grid,"state_kind":"dual","pair_id":"a-b","target_id":"t","resolution":3,"cells":[0],"direction":1}),
        ("stored_query",{"grid":grid,"grouping":"security","state_kind":"dual","pair_id":"a-b","target_id":"t","resolution":3,"group_id":0}),
    ]]
    assert _worker(service,{"run_root":str(tmp_path)},False)["jobs_processed"]==5
    assert all(store.get(job)["status"]=="complete" for job in jobs)
    store.close()
    assert json.loads((root/"evidence"/"coverage_status.json").read_text())["mandatory_coverage_complete"]
