from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from quant_pipeline.alpha_discovery.cache.rank_store import build_multi_bins, pack_multi_bins, unpack_bins
from quant_pipeline.alpha_discovery.features.base import FeatureBuilder, apply_representation
from quant_pipeline.alpha_discovery.cache.target_store import TargetStore
from quant_pipeline.alpha_discovery.candidates import CandidateRule, dual_positions
from quant_pipeline.alpha_discovery.governance.exhaustiveness import ExhaustivenessAudit
from quant_pipeline.alpha_discovery.governance.freeze import freeze_candidates
from quant_pipeline.alpha_discovery.scan.dual_coarse import DualTileScanner
from quant_pipeline.alpha_discovery.scan.dual_coarse import _cluster_segments, _cluster_reduce, _cluster_fold_map
from quant_pipeline.alpha_discovery.scan.pair_plan import PairPlan, canonical_concept_features
from quant_pipeline.alpha_discovery.models import CompiledFeatureSpec, TimeScale
from quant_pipeline.alpha_discovery.config import AlphaDiscoveryConfig, ComputeConfig
from quant_pipeline.alpha_discovery.run import AlphaDiscoveryRun, _edge_autopsy_parallel_capacity
from quant_pipeline.alpha_discovery.autopsy.persistence import persistence_turnover
from quant_pipeline.alpha_discovery.autopsy.placebo import placebo_test


def test_bounded_multi_bins_match_pandas():
    values=np.array([[1.,np.nan],[1.,3.],[2.,2.],[4.,1.],[4.,1.]])
    codes=np.array([0,0,0,1,1]); actual=build_multi_bins(values,codes)
    ranked=pd.DataFrame(values).groupby(pd.Series(codes),sort=False).rank(method="average",pct=True).to_numpy()
    for bins,labels in actual.items():
        expected=np.full(values.shape,-1,dtype=np.int8); valid=np.isfinite(ranked)
        expected[valid]=np.minimum((ranked[valid]*bins).astype(int),bins-1)
        assert np.array_equal(labels,expected)


def test_packed_bins_are_lossless():
    values=np.array([[1.,np.nan],[1.,3.],[2.,2.],[4.,1.],[4.,1.]])
    bins=build_multi_bins(values,np.array([0,0,0,1,1])); packed=pack_multi_bins(bins)
    assert packed.dtype==np.uint8 and packed[0,1]==255
    for resolution in (3,5,10): assert np.array_equal(unpack_bins(packed,resolution),bins[resolution])


def test_persistence_turnover_uses_grouped_rank_column():
    ranks=np.array([.1,.2,.8,.9,.3,.4,.7,.95]); securities=np.array(["a","b","a","b","a","b","a","b"])
    result=persistence_turnover(ranks,securities,lags=(1,))
    assert result.lag.tolist()==[1]
    assert np.isfinite(result.rank_autocorrelation.iloc[0])


@pytest.mark.parametrize("codes", [[0,0,2,2,5,5], [5,0,2,5,2,0], [2], []])
def test_segmented_clusters_match_mask_reference(codes):
    codes=np.asarray(codes,dtype=np.int64); rng=np.random.default_rng(21)
    values=rng.normal(size=(len(codes),3)); valid=rng.random(values.shape)>.3
    values[~valid]=np.nan
    plan=_cluster_segments(codes); sums,counts=_cluster_reduce(values,valid,plan)
    for index,group in enumerate(plan[0]):
        mask=codes==group
        np.testing.assert_allclose(sums[index],np.where(valid[mask],values[mask],0).sum(0),rtol=1e-12,atol=1e-12)
        np.testing.assert_array_equal(counts[index],valid[mask].sum(0))
    folds=np.arange(len(codes),dtype=np.int16)%3; groups=int(codes.max())+1 if len(codes) else 0
    expected=np.full(groups,-1,dtype=np.int16)
    for group in range(groups):
        rows=np.flatnonzero(codes==group)
        if len(rows): expected[group]=folds[rows[0]]
    np.testing.assert_array_equal(_cluster_fold_map(codes,folds,groups),expected)


def test_compiled_history_percentile_matches_reference():
    rng=np.random.default_rng(4); values=pd.Series(rng.choice([1.,2.,3.,np.nan],200)); groups=pd.Series(np.repeat(["a","b"],100))
    actual=apply_representation(values,pd.DataFrame({"security_id":groups}),"own_history_percentile",20)
    def reference(window): return float(np.mean(window[:-1] <= window[-1])) if len(window)>1 else np.nan
    expected=values.groupby(groups,sort=False).rolling(21,min_periods=21).apply(reference,raw=True).reset_index(level=0,drop=True)
    assert np.allclose(actual,expected,equal_nan=True)


def test_single_pass_top_k_share_matches_rolling_reference():
    values=pd.Series([np.nan,1.,-2.,3.,-4.,2.,0.,5.,-1.,2.]); groups=pd.Series(["a"]*len(values))
    builder=object.__new__(FeatureBuilder); builder._cache={}; builder._group_kind="security"; builder._current_group=groups
    for k in (1,2,3,5):
        actual=builder._top_abs_return_share(values,5,k)
        expected=values.groupby(groups).rolling(5,min_periods=5).apply(
            lambda x: np.sort(np.abs(x))[-k:].sum()/np.abs(x).sum() if np.abs(x).sum()>0 else np.nan,raw=True
        ).reset_index(level=0,drop=True)
        assert np.allclose(actual,expected,equal_nan=True)


def test_chunked_clustered_scanner_is_deterministic():
    rng=np.random.default_rng(9); a=rng.integers(0,5,size=(400,3),dtype=np.int8); b=rng.integers(0,5,size=(400,3),dtype=np.int8); y=rng.normal(size=400)
    clusters=np.repeat(np.arange(20),20); folds=clusters//5; scanner=DualTileScanner(bins=5,prefer_cuda=False)
    def run(chunk):
        def reader(start,end): return a[start:end],b[start:end],y[start:end],None,None
        return scanner.scan_reader(len(y),3,reader,chunk,cluster_codes=clusters,fold_codes=folds)
    left,right=run(400),run(37)
    for column in ("candidate_effect","cluster_se","p_value","neighbor_effect_retention"):
        assert np.allclose(left[column],right[column],equal_nan=True,atol=1e-12)


def test_multi_target_scan_matches_individual_scans():
    rng=np.random.default_rng(12); a=rng.integers(0,3,size=(240,4),dtype=np.int8); b=rng.integers(0,3,size=(240,4),dtype=np.int8)
    targets=rng.normal(size=(240,2)); clusters=np.repeat(np.arange(12),20); folds=clusters//3
    scanner=DualTileScanner(bins=3,prefer_cuda=False)
    def reader(start,end): return a[start:end],b[start:end],targets[start:end],None,None
    combined=scanner.scan_reader(240,4,reader,47,cluster_codes=clusters,fold_codes=folds,target_count=2)
    for target_index in range(2):
        def single_reader(start,end,i=target_index): return a[start:end],b[start:end],targets[start:end,i],None,None
        single=scanner.scan_reader(240,4,single_reader,47,cluster_codes=clusters,fold_codes=folds)
        selected=combined[combined.target_index.eq(target_index)].reset_index(drop=True)
        for column in ("candidate_effect","cluster_se","p_value","neighbor_effect_retention"):
            assert np.allclose(selected[column],single[column],equal_nan=True,atol=1e-12)


def test_fused_packed_resolutions_match_separate_scans():
    rng=np.random.default_rng(18); ranks=rng.random((180,6)).astype(np.float32); missing=rng.random(ranks.shape)<.04; ranks[missing]=np.nan
    bins={n:np.where(np.isfinite(ranks),np.minimum((ranks*n).astype(int),n-1),-1).astype(np.int8) for n in (3,5,10)}
    packed=pack_multi_bins(bins); left=np.array([0,1,2,3]); right=np.array([2,3,4,5]); targets=rng.normal(size=(180,2))
    clusters=np.repeat(np.arange(9),20); folds=clusters//3; scanner=DualTileScanner(prefer_cuda=False)
    def packed_reader(start,end): return packed[start:end,left],packed[start:end,right],targets[start:end]
    fused=scanner.scan_packed_resolutions(180,4,packed_reader,row_chunk_size=31,target_count=2,cluster_codes=clusters,fold_codes=folds)
    def unique_reader(start,end): return packed[start:end],left,right,targets[start:end]
    unique_fused=scanner.scan_packed_resolutions(180,4,unique_reader,row_chunk_size=31,target_count=2,cluster_codes=clusters,fold_codes=folds)
    for resolution in (3,5,10):
        separate=DualTileScanner(bins=resolution,prefer_cuda=False)
        def reader(start,end,r=resolution): return bins[r][start:end,left],bins[r][start:end,right],targets[start:end],None,None
        expected=separate.scan_reader(180,4,reader,31,cluster_codes=clusters,fold_codes=folds,target_count=2)
        for column in ("selected_cell_effect","candidate_effect","cluster_se","p_value","neighbor_effect_retention"):
            assert np.allclose(fused[resolution][column],expected[column],equal_nan=True,atol=1e-12)
            assert np.allclose(unique_fused[resolution][column],expected[column],equal_nan=True,atol=1e-12)


@pytest.mark.skipif(not __import__("torch").cuda.is_available(),reason="CUDA unavailable")
def test_cuda_cluster_reduction_matches_cpu():
    rng=np.random.default_rng(42); rows=240; pairs=5; target_count=2
    packed=rng.integers(0,150,size=(rows,8),dtype=np.uint8); left=np.arange(pairs); right=np.arange(1,pairs+1)
    targets=rng.normal(size=(rows,target_count)).astype(np.float32); targets[::19,0]=np.nan
    clusters=np.repeat(np.arange(12),20); folds=clusters//3
    def reader(start,end): return packed[start:end],left,right,targets[start:end]
    cpu=DualTileScanner(prefer_cuda=False).scan_packed_resolutions(rows,pairs,reader,row_chunk_size=37,target_count=target_count,cluster_codes=clusters,fold_codes=folds)
    gpu=DualTileScanner(prefer_cuda=True,memory_fraction=.5).scan_packed_resolutions(rows,pairs,reader,row_chunk_size=37,target_count=target_count,cluster_codes=clusters,fold_codes=folds)
    for resolution in (3,5,10):
        for column in ("candidate_effect","cluster_se","test_statistic","p_value","outlier_cluster_share","fold_sign_consistency","fold_magnitude_ratio"):
            assert np.allclose(gpu[resolution][column],cpu[resolution][column],equal_nan=True,rtol=2e-5,atol=2e-7)


def test_realized_alias_plan_and_frozen_dual_rule():
    plan=PairPlan.compile(["a","b","c"],{"a":"same","b":"same","c":"other"})
    assert plan.alias_of=={"b":"a"} and len(plan.left)==1
    rule=CandidateRule.create("dual",("a","c"),"target",-1,5,(7,))
    assert np.array_equal(dual_positions(np.array([1,0]),np.array([2,2]),rule),np.array([-1,0]))


def test_duals_choose_one_raw_anchor_scale_per_concept():
    def spec(concept,scale,representation):
        unit="minutes" if scale.endswith("m") else "sessions"; value=int(scale[:-1])
        return CompiledFeatureSpec(f"{concept}__{scale}__{representation}",concept,"returns",TimeScale(unit,value,scale),representation,"intraday_5m","causal",value,concept,"returns","split_consistent","hash")
    specs=[spec("a","5m","raw"),spec("a","30m","raw"),spec("a","30m","own_history_percentile"),spec("b","5m","raw")]
    selected,excluded=canonical_concept_features(specs,{"intraday_5m":"30m"})
    assert [item.feature_id for item in selected]==["a__30m__raw","b__5m__raw"]
    assert len(excluded)==2 and set(excluded.values())=={"a__30m__raw"}


def test_target_store_is_aligned_and_lineaged(tmp_path: Path):
    ledger=tmp_path/"ledger"; ledger.write_bytes(b"frozen")
    store=TargetStore(tmp_path/"targets"); ids=np.array([4,7,9])
    store.build_columns("aligned",ids,["a","b"],lambda name: np.arange(3)+(name=="b"),ledger)
    values,names=store.read("aligned")
    assert names==["a","b"] and np.array_equal(values[:,1],[1,2,3])


def test_target_store_batched_build_matches_columns(tmp_path: Path):
    ledger=tmp_path/"ledger"; ledger.write_bytes(b"frozen"); ids=np.array([4,7,9]); columns=["a","b","c"]
    store=TargetStore(tmp_path/"targets")
    store.build_batches("aligned",ids,columns,lambda batch:np.column_stack([np.arange(3)+columns.index(name) for name in batch]),ledger,2)
    values,names=store.read("aligned")
    assert names==columns and np.array_equal(values,np.column_stack([np.arange(3)+i for i in range(3)]))


def test_lazy_feature_and_overlapping_global_chunks_match_reference(tmp_path: Path):
    dates=pd.bdate_range("2025-01-02",periods=60); rows=[]
    for day_index,date in enumerate(dates):
        decision=pd.Timestamp(date,tz="UTC")+pd.Timedelta(hours=20)
        for security_index,security in enumerate(("a","b")):
            close=100+day_index*(1+security_index*.1)+security_index
            rows.append({"observation_id":len(rows),"security_id":security,"symbol":security,"session_date":date,
                         "decision_ts":decision,"decision_grid":"intraday_5m","price_basis":"split_consistent","emit":True,
                         "open":close-.2,"high":close+.5,"low":close-.5,"close":close,"volume":1000+day_index,
                         "benchmark_close":100+day_index,"benchmark_session_open":100+day_index,
                         "benchmark_prior_session_close":99+day_index,"session_open":close-.2,"prior_session_close":close-1})
    frame=pd.DataFrame(rows); panel=tmp_path/"panel.parquet"; frame.to_parquet(panel,index=False)
    spec=CompiledFeatureSpec("breadth","market_breadth_positive","market",TimeScale("sessions",5,"5d"),"raw",
                             "intraday_5m","causal",5,"breadth","market","split_consistent","hash")
    lazy=FeatureBuilder(frame.iloc[:20].copy()); lazy.build(spec)
    assert set(lazy._primitive_cache)=={("returns","security")}
    reference_builder=FeatureBuilder(frame); built=reference_builder.build_many([spec]).to_numpy()[:,0]
    expected=np.empty(len(frame)); expected[reference_builder.frame.observation_id.to_numpy(int)]=built
    output=np.lib.format.open_memmap(tmp_path/"output.npy",mode="w+",dtype=np.float32,shape=(len(frame),1))
    run=AlphaDiscoveryRun(AlphaDiscoveryConfig()); written,telemetry=run._build_global_feature_chunks(panel,[("breadth",[spec],output)])
    output.flush(); actual=np.asarray(output[:,0]).copy(); output._mmap.close()
    assert written==len(frame) and telemetry["emitted_sessions_per_chunk"]<=40
    assert np.allclose(actual,expected,equal_nan=True,atol=1e-6)


def test_exact_coverage_and_autopsy_pass_are_hard_freeze_gates(tmp_path: Path):
    audit=ExhaustivenessAudit(1,2,2,0,1,2,2,0,0,1,{},1,1,1,1,1,0,True,0,True)
    assert audit.status=="INCOMPLETE"
    with pytest.raises(RuntimeError,match="exhaustiveness"):
        freeze_candidates(tmp_path/"freeze.json",[],{"exhaustiveness_status":"INCOMPLETE"})
    with pytest.raises(RuntimeError,match="hard Edge Autopsy"):
        freeze_candidates(tmp_path/"freeze.json",[{"autopsy_complete":True,"autopsy_pass":False}],{"exhaustiveness_status":"PASS"})


def test_edge_autopsy_parallel_capacity_maxes_cpu_with_ram_headroom():
    compute=ComputeConfig(cpu_workers=16,host_memory_fraction=.95)
    gib=1<<30
    assert _edge_autopsy_parallel_capacity(compute,8,30*gib,32*gib,5*gib)==5
    assert _edge_autopsy_parallel_capacity(compute,3,30*gib,32*gib,5*gib)==3
    assert _edge_autopsy_parallel_capacity(compute,8,4*gib,32*gib,5*gib)==1


def test_parallel_placebo_matches_serial():
    rng=np.random.default_rng(12); score=rng.normal(size=120); target=rng.normal(size=120)
    groups=np.repeat(np.arange(12),10)
    serial=placebo_test(score,target,groups,runs=24,seed=91,workers=1)
    parallel=placebo_test(score,target,groups,runs=24,seed=91,workers=4)
    pd.testing.assert_frame_equal(serial,parallel)


def test_edge_autopsy_capacity_helper_is_process_spawn_safe():
    from concurrent.futures import ProcessPoolExecutor
    compute=ComputeConfig(cpu_workers=4,host_memory_fraction=.90); gib=1<<30
    with ProcessPoolExecutor(max_workers=1) as pool:
        assert pool.submit(_edge_autopsy_parallel_capacity,compute,3,12*gib,16*gib,3*gib).result()==3
