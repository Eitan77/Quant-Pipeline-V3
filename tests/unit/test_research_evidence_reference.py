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

from quant_pipeline.production.evidence_identity import atomic_json, inside, task_identity
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.production.evidence_query import group_cells, open_catalog
from quant_pipeline.production.research_jobs import JobStore, worker_lock, run_one
from quant_pipeline.production.segmented_scan import SegmentedMoments, encode_groups, local_group_codes
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


def test_hidden_joint_store_and_query(tmp_path):
    check_store_query(tmp_path / "evidence")


def test_planner_and_job_recovery(tmp_path):
    check_planner_jobs(tmp_path)


def test_opportunity_replacement_parity():
    repo = Path(__file__).resolve().parents[2]
    check_overlap(repo)
