import numpy as np
import pytest

from quant_pipeline.production.segmented_scan import SegmentedMoments, prepare_tile, local_group_codes


@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("track_sumsq", [False, True])
def test_fused_and_resident_match_cpu(single, track_sumsq):
    torch = pytest.importorskip("torch")
    pytest.importorskip("cupy")
    if not torch.cuda.is_available():
        pytest.skip("CUDA required")
    from quant_pipeline.production.segmented_cuda import FusedSegmentedBatch, ResidentEvidenceGrid
    rng = np.random.default_rng(713)
    packed = rng.integers(0, 150, (211, 3), dtype=np.uint8)
    packed[::9, 0] = 255
    y = rng.normal(size=(211, 3)) / 10000
    y[:4, 2] = [np.nan, np.inf, -np.inf, 0]
    codes = {"a": rng.integers(-1, 5, size=211), "b": np.full(211, -1, dtype=np.int64)}
    left, right, targets = [2, 0], None if single else [1, 2], [2, 0]
    expected, live = [], []
    for family in codes:
        for start, stop in ((0, 2), (2, 4)):
            for resolution in (3, 5, 10):
                task = {"grouping_id": family, "group_start": start, "group_stop": stop,
                        "resolution": resolution}
                args = dict(pairs=2, targets=2, groups=2, resolution=resolution,
                            singles=single, track_sumsq=track_sumsq, max_state_bytes=1_000_000)
                cpu = SegmentedMoments(**args)
                cpu.update(packed, left, right, y[:, targets], local_group_codes(codes[family], start, stop))
                expected.append(cpu)
                live.append((task, SegmentedMoments(**args, device="cuda:0")))
    fused = FusedSegmentedBatch(live, left, right, targets)
    for start, stop in ((0, 37), (37, 211)):
        fused.update(prepare_tile(packed[start:stop], y[start:stop], "cuda:0"),
                     {family: value[start:stop] for family, value in codes.items()})

    def check():
        for cpu, (_, gpu) in zip(expected, live):
            np.testing.assert_array_equal(cpu.n, gpu.counts_and_sums()[0])
            np.testing.assert_allclose(cpu.s, gpu.counts_and_sums()[1], rtol=1e-12, atol=1e-16)
            if track_sumsq:
                np.testing.assert_allclose(cpu.q, gpu.numpy()[2], rtol=1e-12, atol=1e-16)
    check()
    for _, gpu in live:
        gpu.n.zero_(); gpu.s.zero_()
        if gpu.q is not None:
            gpu.q.zero_()

    class Reader:
        rows = len(packed)
        grid = {"bins": dict.fromkeys(["f0", "f1", "f2"]),
                "targets": dict.fromkeys(["t0", "t1", "t2"]), "groups": codes}
        def read_columns(self, kind, ids, start, stop):
            return (packed if kind == "bins" else y)[start:stop, [int(key[1:]) for key in ids]]
        def read_groups(self, family, start, stop):
            return codes[family][start:stop]
    resident = ResidentEvidenceGrid(Reader(), "cuda:0", reserve_bytes=1_000_000, row_chunk=37)
    pairs = [("f2",), ("f0",)] if single else [("f2", "f1"), ("f0", "f2")]
    resident.accumulate(live, pairs, ["t2", "t0"], lambda: False)
    check()
    with pytest.raises(InterruptedError):
        resident.accumulate(live, pairs, ["t2", "t0"], lambda: True)


@pytest.mark.parametrize("single", [False, True])
def test_joint_resolution_projection_matches_direct_cpu(single):
    torch = pytest.importorskip("torch")
    pytest.importorskip("cupy")
    if not torch.cuda.is_available():
        pytest.skip("CUDA required")
    from quant_pipeline.production.segmented_cuda import ResidentEvidenceGrid
    rng = np.random.default_rng(721)
    # An arbitrary alphabet also checks that nesting of resolution bins is not assumed.
    alphabet = np.array([0, 5, 17, 29, 41, 53, 65, 89, 101, 113, 125, 149], np.uint8)
    packed = rng.choice(alphabet, size=(601, 3))
    packed[::17, 1] = 255
    y = rng.normal(size=(601, 3)) / 10000
    y[:3, 2] = [np.nan, np.inf, -np.inf]
    codes = {"a": rng.integers(-1, 5, size=601), "b": np.full(601, -1, np.int64)}
    class Reader:
        rows = len(packed)
        grid = {"bins": dict.fromkeys(["f0", "f1", "f2"]),
                "targets": dict.fromkeys(["t0", "t1", "t2"]), "groups": codes}
        def read_columns(self, kind, ids, start, stop):
            return (packed if kind == "bins" else y)[start:stop, [int(key[1:]) for key in ids]]
        def read_groups(self, family, start, stop):
            return codes[family][start:stop]
    resident = ResidentEvidenceGrid(Reader(), "cuda:0", reserve_bytes=1_000_000, row_chunk=73)
    np.testing.assert_array_equal(resident.joint_codes, alphabet)
    pairs = [("f2",), ("f0",)] if single else [("f2", "f1"), ("f0", "f2")]
    rows = [{"grid": "g", "task": {"grouping_id": family, "group_start": start,
             "group_stop": stop, "resolution": resolution, "state_kind": "single" if single else "dual"}}
            for family in codes for start, stop in ((0, 2), (2, 4)) for resolution in (3, 5, 10)]
    rows = rows[:-1]  # A batch need not contain every resolution of its final partition.
    expected_groups = []
    def consume(task, actual, metadata):
        reference = SegmentedMoments(pairs=2, targets=2, groups=task["group_stop"]-task["group_start"],
            resolution=task["resolution"], singles=single, max_state_bytes=1_000_000, track_sumsq=False)
        reference.update(packed, [2, 0], None if single else [1, 2], y[:, [2, 0]],
                         local_group_codes(codes[task["grouping_id"]], task["group_start"], task["group_stop"]))
        n, s = actual.counts_and_sums()
        np.testing.assert_array_equal(n, reference.n)
        np.testing.assert_allclose(s, reference.s, rtol=1e-12, atol=1e-16)
        expected_groups.append(int(np.any(reference.n, axis=-1).sum()))
        assert metadata["rows_evaluated"] == len(y)
    assert resident.joint_batch(rows, pairs, ["t2", "t0"], 1, consume, lambda: False) is None
    results = resident.joint_batch(rows, pairs, ["t2", "t0"], 1_000_000, consume, lambda: False)
    assert [result["populated_groups"] for result in results] == expected_groups
