"""Small executable checks for the handoff reference modules, not a pipeline run."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_pipeline.production.evidence_identity import atomic_json, inside, task_identity
from quant_pipeline.production.evidence_store import EvidenceReader,build_groupings
from quant_pipeline.production.evidence_query import group_cells, open_catalog
from quant_pipeline.production.research_jobs import JobStore, worker_lock, run_one
from quant_pipeline.production.segmented_scan import SegmentedMoments, encode_groups, local_group_codes, prepare_tile
from quant_pipeline.production.segmented_task import execute_segmented_task
from quant_pipeline.production.variant_batches import plan_batches


def check_moments():
    rng = np.random.default_rng(43)
    packed = rng.integers(0, 150, (37, 3), dtype=np.uint8)
    packed[0, 0] = 255
    y = rng.normal(size=(37, 2)) / 10000
    y[1, 0] = np.nan
    groups = rng.integers(-1, 3, size=37)
    for single in (False, True):
        for r in (3, 5, 10):
            m = SegmentedMoments(pairs=2, targets=2, groups=3, resolution=r,
                                 singles=single, max_state_bytes=1_000_000)
            left, right = [0, 1], None if single else [1, 2]
            for a, b in [(0, 11), (11, 37)]:
                m.update(packed[a:b], left, right, y[a:b], groups[a:b])
            expected = [np.zeros(m.shape, dtype=d) for d in (np.int64, float, float)]
            decode = lambda x: int(x) % 3 if r == 3 else (int(x) // 3) % 5 if r == 5 else int(x) // 15
            for i in range(37):
                for p in range(2):
                    for t in range(2):
                        if groups[i] < 0 or not np.isfinite(y[i, t]) or packed[i, left[p]] == 255:
                            continue
                        cell = decode(packed[i, left[p]])
                        if not single:
                            if packed[i, right[p]] == 255:
                                continue
                            cell = cell * r + decode(packed[i, right[p]])
                        key = (t, p, groups[i], cell)
                        expected[0][key] += 1
                        expected[1][key] += y[i, t]
                        expected[2][key] += y[i, t] ** 2
            for observed, wanted in zip(m.numpy(), expected):
                np.testing.assert_allclose(observed, wanted, rtol=1e-12, atol=1e-16)
    np.testing.assert_array_equal(local_group_codes(np.array([-1, 0, 1, 2, 3]), 1, 3), [-1, -1, 0, 1, -1])


def check_store_query(root):
    root.mkdir()
    group_frame = pd.DataFrame({"security": [0, 0, 1, 1] * 2, "bucket": [0, 1, 0, 1] * 2})
    codes, labels = encode_groups(group_frame, ["security", "bucket"])
    y = np.array([8, -8, -8, 8] * 2, float).reshape(-1, 1) / 10000
    assert y.mean() == 0
    assert group_frame.assign(y=y[:, 0]).groupby("security").y.mean().eq(0).all()
    assert group_frame.assign(y=y[:, 0]).groupby("bucket").y.mean().eq(0).all()
    references = {}
    for name, array in [("bins", np.zeros((8, 2), np.uint8)), ("targets", y), ("groups", codes)]:
        np.save(root / f"{name}.npy", array)
        references[name] = dict(path=f"{name}.npy", shape=list(array.shape),
                                dtype=str(array.dtype), observation_id="obs")
    manifest = {"grids": {"g": dict(rows=8, observation_id="obs",
                bins={"a": {**references["bins"], "column": 0}, "b": {**references["bins"], "column": 1}},
                targets={"t": {**references["targets"], "column": 0}}, groups={"joint": references["groups"]})}}
    atomic_json(root / "reader.json", manifest)
    task = task_identity("stage", pair_ids=["a-b"], target_ids=["t"], resolution=3,
                         grouping_id="joint", group_start=0, group_stop=len(labels))
    reader = EvidenceReader(root, "reader.json", "g")
    args = dict(root=root, task=task, reader=reader, pair_definitions={"a-b": ("a", "b")},
                observation_id="obs", row_chunk=3, max_state_bytes=1_000_000)
    result = execute_segmented_task(**args)
    assert result == execute_segmented_task(**args)
    (root / result["artifact"]).parent.joinpath("complete.json").unlink()
    assert execute_segmented_task(**args)["sha256"] == result["sha256"]
    atomic_json(root / "catalog.json", {"tables": {"joint": {"files": [result["artifact"]]}}})
    con, _ = open_catalog(root, "catalog.json", memory_gib=1, threads=1)
    page = group_cells(con, table="joint", pair_id="a-b", target_id="t", resolution=3, group_id=0, limit=2)
    assert page["rows"][0]["n"] == 2 and page["rows"][0]["raw_mean_bps"] == 8
    assert page["next_cell"] == 1
    absent = group_cells(con, table="joint", pair_id="missing", target_id="t", resolution=3, group_id=0)
    assert absent["status"] == "absent_requires_coverage_check"
    con.close()
    moved = root.with_name("moved")
    shutil.copytree(root, moved)
    con, _ = open_catalog(moved, "catalog.json", memory_gib=1, threads=1)
    assert con.execute("SELECT count(*) FROM joint").fetchone()[0] == 4
    con.close()
    (root / result["artifact"]).unlink()
    assert execute_segmented_task(**args)["populated_groups"] == 4
    try:
        inside(root, "../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("Path escape was accepted")


def check_planner_jobs(root):
    requests = [dict(feature_a=a, feature_b=b, target_id=t) for a, b, ts in
                [("a", "b", ["x", "y"]), ("a", "c", ["x"]), ("b", "c", ["x", "y"])] for t in ts]
    work = list(plan_batches(requests + requests[:1], dict.fromkeys(["a", "b", "c"], "g"), max_pairs=1, max_targets=1))
    actual = [(a, b, t) for task in work for a, b in task["pairs"] for t in task["targets"]]
    expected = [(r["feature_a"], r["feature_b"], r["target_id"]) for r in requests]
    assert sorted(actual) == sorted(expected)
    with worker_lock(root / "worker.lock"):
        store = JobStore(root / "jobs.sqlite")
        job = store.submit({"kind": "check", "evidence_id": "one"})
        assert run_one(store, {"check": lambda spec, cancelled: {"rows": 4}})
        assert store.get(job)["status"] == "complete"
        other = store.submit({"kind": "check", "evidence_id": "two"})
        old = store.claim()
        store.recover_after_lock()
        new = store.claim()
        try:
            store.finish(other, old[1], result={})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Accepted stale completion")
        store.cancel(other)
        store.finish(other, new[1], result={})
        assert store.get(other)["status"] == "cancelled"
        store.close()


def check_overlap(repo):
    from quant_pipeline.forensics.opportunities import opportunity_timing_summary
    rng = np.random.default_rng(17)
    for count in [0, 1, 20, 500]:
        starts = rng.integers(0, 100, size=count)
        ends = starts + rng.integers(-2, 20, size=count)
        opportunities = [SimpleNamespace(start_ts_ns=int(s), start_obs_id=i) for i, s in enumerate(starts)]
        result = opportunity_timing_summary(opportunities=opportunities, end_ts_by_obs=dict(enumerate(ends)))
        expected = np.array([np.sum((starts <= ts) & (ends > ts)) for ts in starts])
        assert result["average_concurrency"] == (float(expected.mean()) if count else 0.0)
        assert result["peak_concurrency"] == (int(expected.max()) if count else 0)


def test_moment_reference():
    check_moments()


def test_cuda_shared_prepared_tile_parity():
    torch=pytest.importorskip("torch")
    if not torch.cuda.is_available():pytest.skip("CUDA unavailable")
    rng=np.random.default_rng(74)
    packed=rng.integers(0,150,(97,3),dtype=np.uint8)
    packed[::11,1]=255
    y=rng.normal(size=(97,2)).astype(np.float64)/10000
    y[::7,0]=np.nan
    groups=rng.integers(-1,5,97)
    prepared=prepare_tile(packed,y,"cuda:0")
    for resolution in (3,5,10):
        cpu=SegmentedMoments(pairs=2,targets=2,groups=5,resolution=resolution,
                             max_state_bytes=1_000_000)
        gpu=SegmentedMoments(pairs=2,targets=2,groups=5,resolution=resolution,
                             max_state_bytes=1_000_000,device="cuda:0")
        cpu.update(packed,[0,2],[1,0],y,groups)
        gpu.update_prepared(prepared,[0,2],[1,0],groups)
        for actual,expected in zip(gpu.numpy(),cpu.numpy()):
            np.testing.assert_allclose(actual,expected,rtol=1e-12,atol=1e-16)


def test_hidden_joint_store_and_query(tmp_path):
    check_store_query(tmp_path / "evidence")


def test_planner_and_job_recovery(tmp_path):
    check_planner_jobs(tmp_path)


def test_windows_worker_exclusion(tmp_path):
    lock=tmp_path/"numerical.lock"
    with worker_lock(lock):
        with pytest.raises(OSError):
            with worker_lock(lock):
                pass


def test_job_blocked_retry_and_cancel(tmp_path):
    store=JobStore(tmp_path/"jobs.sqlite")
    blocked=store.submit({"kind":"check","request":"blocked"})
    assert run_one(store,{"check":lambda spec,cancelled:{"status":"blocked_storage"}})
    assert store.get(blocked)["status"]=="blocked_storage"
    store.retry(blocked)
    assert run_one(store,{"check":lambda spec,cancelled:{"status":"complete","rows":2}})
    assert store.get(blocked)["status"]=="complete" and store.get(blocked)["attempt"]==2
    cancelled=store.submit({"kind":"check","request":"cancel"})
    store.cancel(cancelled)
    assert store.get(cancelled)["status"]=="cancelled"
    store.close()


def test_opportunity_replacement_parity():
    repo = Path(__file__).resolve().parents[2]
    check_overlap(repo)


def test_early_close_grouping_excludes_after_session(tmp_path):
    observations=pd.DataFrame({"security_id":["A","A"],"session_date":["2025-07-03"]*2,
        "decision_ts":pd.to_datetime(["2025-07-03 16:30Z","2025-07-03 17:30Z"])})
    groups=build_groupings(tmp_path,"g",observations,"obs",definitions=[("time_bucket",)],folds=1)
    codes=np.load(tmp_path/groups["time_bucket"]["path"])
    assert codes[0]>=0 and codes[1]==-1


def test_replay_preparer_uses_exact_governed_benchmark_leg(tmp_path,monkeypatch):
    from quant_pipeline.production import replay
    grid="intraday_5m"
    adjusted=f"target_5m__benchmark_adjusted__{grid}"
    raw=f"target_5m__raw__{grid}"
    stamp=pd.Timestamp("2025-05-01 14:30Z")
    events=tmp_path/"events.parquet"
    pd.DataFrame({"observation_id":[1],"security_id":["A"],"session_date":[stamp.date()],
                  "decision_ts":[stamp]}).to_parquet(events,index=False)
    ledger=tmp_path/"cache"/"targets"/f"{grid}.parquet"
    ledger.parent.mkdir(parents=True)
    pd.DataFrame({"observation_id":[1,2],"security_id":["A","BENCH"],
                  "session_date":[stamp.date()]*2,"decision_ts":[stamp]*2,
                  "target_id":[adjusted,raw],"target_basis":["benchmark_adjusted","raw"],
                  "entry_ts":[stamp+pd.Timedelta(minutes=5)]*2,
                  "entry_price":[100.,400.],"exit_ts":[stamp+pd.Timedelta(minutes=20)]*2,
                  "exit_price":[101.,402.],"beta_prior":[0.8,0.0]}).to_parquet(ledger,index=False)
    monkeypatch.setattr(replay,"prepare_state_events",lambda *args,**kw:(events,"event"))
    original=replay.pd.read_parquet
    monkeypatch.setattr(replay.pd,"read_parquet",lambda path,**kw:
        pd.DataFrame({"security_id":["A","BENCH"],"symbol":["AAA","SPY"]})
        if str(path).endswith("security_master.parquet") else original(path,**kw))
    signals,meta=replay.prepare_replay_inputs(tmp_path,{"evidence_id":"e"},
        {"grid":grid,"target_id":adjusted,"direction":1,"return_basis":"benchmark_adjusted",
         "benchmark_symbol":"SPY"})
    assert meta["benchmark_security_id"]=="BENCH"
    assert len(signals)==1 and signals.iloc[0].benchmark_exit_price==402.
