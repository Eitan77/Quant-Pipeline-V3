import numpy as np,pandas as pd
import duckdb
from quant_pipeline.alpha_discovery.cache.rank_store import build_packed_bins,unpack_bins
from quant_pipeline.alpha_discovery.scan.dual_coarse import DualTileScanner
from quant_pipeline.production.cell_specialist import _summaries
from quant_pipeline.production.cell_temporal import _reduce
from quant_pipeline.production.surface_math import reconstruct_surface
from quant_pipeline.production.bundle import build_v3_analysis_bundle

def test_full_surface_packed_parity_all_resolutions():
    rng=np.random.default_rng(91); n=600; values=rng.normal(size=(n,2)); codes=np.repeat(np.arange(60),10); packed=build_packed_bins(values,codes); y=rng.normal(0,.01,n); fused=DualTileScanner(bins=10,prefer_cuda=False).scan_packed_resolutions(n,1,lambda start,end:(packed[start:end,:1],packed[start:end,1:2],y[start:end]),resolutions=(3,5,10))
    for resolution in (3,5,10):
        a=unpack_bins(packed[:,0],resolution)[:,None]; b=unpack_bins(packed[:,1],resolution)[:,None]; direct=DualTileScanner(bins=resolution,prefer_cuda=False).scan(a,b,y).iloc[0]; row=fused[resolution].iloc[0]
        for field in ("surface_counts","surface_sums","surface_sumsq"): np.testing.assert_allclose(row[field],direct[field])
        left=reconstruct_surface(counts=row.surface_counts,sums=row.surface_sums,sumsq=row.surface_sumsq,resolution=resolution); right=reconstruct_surface(counts=direct.surface_counts,sums=direct.surface_sums,sumsq=direct.surface_sumsq,resolution=resolution)
        np.testing.assert_allclose(left["mean"],right["mean"],equal_nan=True); np.testing.assert_allclose(left["interaction"],right["interaction"],equal_nan=True); assert row.selected_cell==direct.selected_cell
        selected=int(row.selected_cell); np.testing.assert_allclose(left["mean"][selected]*1e4,row.selected_state_bps); np.testing.assert_allclose(left["interaction"][selected]*1e4,row.selected_interaction_lift_bps)

def test_hidden_cells_receive_specialist_and_temporal_metrics():
    counts=np.zeros((1,4,4),int); sums=np.zeros((1,4,4),float); counts[0,:,0]=20; sums[0,:,0]=np.array([.2,.2,-.2,-.2]); counts[0,:,3]=20; sums[0,:,3]=.4
    specialist=_summaries(counts,sums,20)[0]; assert specialist["eligible_symbol_count"][0]==4 and specialist["positive_symbol_fraction"][0]==.5 and specialist["negative_symbol_fraction"][0]==.5
    fold_counts=np.full((1,5,4),10); fold_sums=np.zeros((1,5,4)); fold_sums[0,:,1]=.01; temporal=_reduce(fold_counts,fold_sums)[0]; assert temporal["fold_positive_fraction"][1]==1.0

def test_bundle_cell_evidence_view_covers_every_cell(tmp_path):
    run=tmp_path/"run"; (run/"v3_diagnostics").mkdir(parents=True)
    pd.DataFrame([{"pair_id":"p","feature_a":"a","feature_b":"b","target_id":"t","v3_resolution":3,"surface_counts":[10]*9,"surface_sums":[.01]*9,"surface_sumsq":[.00002]*9}]).to_parquet(run/"v3_diagnostics/dual_resolution_summary.parquet",index=False)
    specialist={"pair_id":"p","target_id":"t","resolution":3,"eligible_symbol_count":[1]*9,"positive_symbol_fraction":[1.]*9,"negative_symbol_fraction":[0.]*9,"symbol_effect_dispersion_bps":[0.]*9,"best_positive_local_bps":[10.]*9,"best_negative_local_bps":[np.nan]*9,"top_symbol_contribution_share":[1.]*9,"top5_symbol_contribution_share":[1.]*9,"cancellation_score":[1.]*9}
    temporal={"pair_id":"p","target_id":"t","resolution":3,"fold_positive_fraction":[1.]*9,"fold_negative_fraction":[0.]*9,"worst_fold_bps":[8.]*9,"best_fold_bps":[12.]*9,"median_fold_bps":[10.]*9,"fold_dispersion_bps":[1.]*9,"minimum_fold_n":[2]*9}
    pd.DataFrame([specialist]).to_parquet(run/"cell_specialist_summary.parquet",index=False); pd.DataFrame([temporal]).to_parquet(run/"cell_temporal_summary.parquet",index=False)
    for name in ("feature_registry","target_registry","single_summary","trial_ledger"): pd.DataFrame({"id":[]}).to_parquet(run/f"{name}.parquet",index=False)
    research={"zoom":{"enabled":False},"periods":{"discovery":{"start":"2025-05-01","end":"2026-04-30"}},"resolutions":[3]}; out=build_v3_analysis_bundle(run_root=run,research=research,source_manifest_hash="x",trial_coverage={})
    with duckdb.connect(str(out/"research.duckdb"),read_only=True) as con:
        count,edge=con.execute("select count(*),min(raw_edge_bps) from cell_evidence").fetchone()
    assert count==9 and edge==10.0
