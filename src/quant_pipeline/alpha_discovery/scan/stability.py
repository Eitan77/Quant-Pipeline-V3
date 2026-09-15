from __future__ import annotations

import numpy as np
from pathlib import Path


def build_stability(root: Path, config: dict, resolutions=(3,5,10)) -> dict:
    """Disk-backed aggregation and one global BH adjustment for the selected scope."""
    import duckdb
    single_files=[str(p) for p in (root/'single_results').glob('*/*.parquet')]
    if not single_files: raise ValueError('No single results')
    tree={3:'dual_coarse_results',5:'dual_fine_results',10:'dual_exact_results'}[max(resolutions)]
    dual_files=[str(p) for p in (root/tree).glob('**/part-*.parquet')]
    destination=root/'stability'; destination.mkdir(parents=True,exist_ok=True)
    with duckdb.connect() as c:
        c.execute("SET memory_limit='2GB'")
        c.execute("SET temp_directory=?",[str(destination/'spill')])
        c.from_parquet(single_files,union_by_name=True).create_view('singles')
        c.execute("""CREATE TEMP TABLE single_summary AS
            WITH folds AS (SELECT feature_id,target_id,median(candidate_effect) median_effect,
                abs(avg(sign(candidate_effect))) fold_sign_consistency,count(candidate_effect) valid_folds
                FROM singles WHERE fold_id<>'all' GROUP BY feature_id,target_id)
            SELECT 'single' structure_type,s.feature_id,s.feature_id feature_a,NULL::VARCHAR feature_b,s.target_id,
                NULL::INTEGER resolution,NULL::INTEGER selected_cell,s.n_obs,s.candidate_effect effect,s.p_value,
                s.cluster_se,s.test_statistic,f.fold_sign_consistency,
                least(1.,abs(f.median_effect)/nullif(abs(s.candidate_effect),0)) fold_magnitude_ratio,
                f.valid_folds,s.neighbor_effect_retention,s.plateau_area,s.cell_min_count,s.outlier_cluster_share
            FROM singles s LEFT JOIN folds f USING(feature_id,target_id) WHERE s.fold_id='all'""")
        if dual_files:
            c.from_parquet(dual_files,union_by_name=True).create_view('duals')
            c.execute("""CREATE TEMP VIEW combined AS SELECT * FROM single_summary UNION ALL
                SELECT 'dual',feature_a,feature_a,feature_b,target_id,resolution,selected_cell,n_obs,candidate_effect,
                p_value,cluster_se,test_statistic,fold_sign_consistency,fold_magnitude_ratio,
                len(fold_effects),neighbor_effect_retention,plateau_area,cell_min_count,outlier_cluster_share FROM duals""")
        else: c.execute('CREATE TEMP VIEW combined AS SELECT * FROM single_summary')
        # Invalid tests receive p=1; they still count in the global family and fail gates.
        c.execute("""CREATE TEMP TABLE adjusted AS WITH ranked AS (
            SELECT *, CASE WHEN isfinite(p_value) AND p_value BETWEEN 0 AND 1 THEN p_value ELSE 1. END p,
                row_number() OVER(ORDER BY CASE WHEN isfinite(p_value) AND p_value BETWEEN 0 AND 1 THEN p_value ELSE 1. END,feature_id,target_id,feature_b) r,
                count(*) OVER() total FROM combined)
            SELECT * EXCLUDE(p,r,total),least(1.,min(p*total/r) OVER(ORDER BY r ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)) fdr_q FROM ranked""")
        gates=[f'fdr_q<={float(config.get("global_fdr_alpha",.05))}',
               f'valid_folds>={int(config.get("minimum_valid_folds",2))}',
               f'fold_sign_consistency>={float(config.get("minimum_fold_sign_consistency",.6))}',
               f'fold_magnitude_ratio>={float(config.get("minimum_fold_magnitude_ratio",.05))}',
               f'cell_min_count>={int(config.get("minimum_cell_count",20))}',
               f'outlier_cluster_share<={float(config.get("maximum_outlier_cluster_share",.25))}']
        if config.get('require_neighbor_analysis',True): gates.append(f'neighbor_effect_retention>={float(config.get("minimum_neighbor_retention",.25))}')
        if config.get('require_plateau_detection',True): gates.append(f'plateau_area>={int(config.get("minimum_plateau_area",2))}')
        c.execute('CREATE TEMP TABLE gated AS SELECT *,coalesce('+ ' AND '.join(gates)+',false) hard_gate_pass FROM adjusted')
        # Raw percentage effects are not comparable across minute and multi-month
        # targets. Rank magnitude only inside like-for-like structure/target groups.
        c.execute("""CREATE TEMP VIEW final AS WITH normalized AS (
            SELECT *,cume_dist() OVER(PARTITION BY structure_type,target_id ORDER BY abs(effect)) economic_rank
            FROM gated)
            SELECT *,CASE WHEN hard_gate_pass THEN
            economic_rank*-log10(greatest(fdr_q,1e-300))*fold_sign_consistency*fold_magnitude_ratio*greatest(neighbor_effect_retention,.01)*ln(1+n_obs)
            ELSE '-Infinity'::DOUBLE END stability_score FROM normalized""")
        c.execute('COPY final TO ? (FORMAT PARQUET)',[str(destination/'candidate_stability.parquet')])
        c.execute('COPY single_summary TO ? (FORMAT PARQUET)',[str(destination/'single_stability.parquet')])
        counts=c.execute("SELECT count(*) FILTER(WHERE structure_type='single'),count(*) FILTER(WHERE structure_type='dual'),count(*) FILTER(WHERE hard_gate_pass) FROM final").fetchone()
    return dict(zip(('single_structures','dual_structures','hard_gate_pass'),counts)) | {'inference_role':'discovery_screen','dual_resolution':max(resolutions)}

from .surfaces import connected_plateaus


def score_plateaus(effects: np.ndarray, coverage: np.ndarray, fold_sign: np.ndarray, economic_floor: float) -> list[dict]:
    components = connected_plateaus(effects, coverage > 0, economic_floor)
    rows = []
    for component in components:
        values = np.array([effects[index] for index in component]); best = float(np.max(np.abs(values)))
        retention = float(np.median(np.abs(values)) / best) if best else 0.0
        sign_consistency = float(abs(np.mean(np.sign(values))))
        fold_overlap = float(np.mean([fold_sign[index] for index in component]))
        roughness = float(np.median(np.abs(np.diff(np.sort(values))))) if len(values) > 1 else 0.0
        score = float(np.median(np.abs(values)) * np.sqrt(len(values)) * retention * sign_consistency * fold_overlap / (1 + roughness))
        rows.append({"cells": component, "area": len(component), "median_effect": float(np.median(values)),
                     "best_effect": best, "neighbor_effect_retention": retention,
                     "neighbor_sign_consistency": sign_consistency, "chronological_fold_overlap": fold_overlap,
                     "surface_roughness": roughness, "plateau_score": score})
    return sorted(rows, key=lambda row: (-row["plateau_score"], -row["area"]))
