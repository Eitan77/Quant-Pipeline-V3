from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from .config import AlphaDiscoveryConfig
from .eligibility import EligibilityMatrix
from .governance.exhaustiveness import ExhaustivenessAudit
from .models import ResearchState
from .registry import RegistryBundle, compile_registry
from .report.build import build_reports


STAGE_ORDER = (
    "validate-config", "snapshot", "build-panel", "compile-registry", "build-features", "build-targets",
    "scan-singles", "scan-duals-coarse", "scan-duals-fine", "exact-duals", "build-stability",
    "expand-context", "run-formula-factory", "run-ml", "distill-ml", "run-edge-autopsy",
    "audit-exhaustiveness", "freeze-discovery", "evaluate-replication", "freeze-replication",
    "build-alphas", "evaluate-alphas", "freeze-portfolio", "evaluate-final-holdout", "build-report",
)


def _alpha_feature_is_global(spec) -> bool:
    return spec.family in {"ranks", "statistical_factors"} or "cross_sectional" in spec.concept_id or "rank" in spec.concept_id or spec.concept_id.startswith("market_breadth") or spec.concept_id.startswith("breadth_") or spec.concept_id in {"average_pairwise_correlation", "beta_dispersion"}


def _dual_parent_scope(specs: list, dual_config: dict) -> tuple[list, dict[str, str]]:
    if dual_config.get("search_scope", "canonical_concepts") == "all_features": return specs, {}
    from .scan.pair_plan import canonical_concept_features
    return canonical_concept_features(specs, dual_config.get("canonical_scale_anchors"))


def _single_survivor_scope(specs: list, singles_dir: Path, dual_config: dict) -> list:
    limit=int(dual_config.get("max_parent_features",32)); alpha=float(dual_config.get("single_parent_p_value",0.05))
    frames=[pd.read_parquet(path,columns=["feature_id","fold_id","p_value","test_statistic"]) for path in singles_dir.glob("*.parquet")]
    if not frames: raise RuntimeError(f"No single results in {singles_dir}")
    scores=pd.concat(frames,ignore_index=True); ids={item.feature_id for item in specs}
    scores=scores[scores.fold_id.eq("all") & scores.feature_id.isin(ids)].copy(); scores["abs_stat"]=scores.test_statistic.abs()
    ranked=(scores.groupby("feature_id",as_index=False).agg(best_p=("p_value","min"),best_stat=("abs_stat","max"))
            .sort_values(["best_p","best_stat","feature_id"],ascending=[True,False,True]))
    chosen=ranked[ranked.best_p.le(alpha)].head(limit)
    if len(chosen)<2: chosen=ranked.head(min(limit,len(ranked)))
    keep=set(chosen.feature_id)
    return [item for item in specs if item.feature_id in keep]


def _initial_feature_scope(specs: list, config: AlphaDiscoveryConfig) -> tuple[list, dict[str, str]]:
    selection=config.feature_search
    if selection.get("feature_ids"): specs=[item for item in specs if item.feature_id in set(selection["feature_ids"])]
    if selection.get("families"): specs=[item for item in specs if item.family in set(selection["families"])]
    if selection.get("concepts"): specs=[item for item in specs if item.concept_id in set(selection["concepts"])]
    if selection.get("scales"): specs=[item for item in specs if item.scale.label in set(selection["scales"])]
    if selection.get("representations"): specs=[item for item in specs if item.representation in set(selection["representations"])]
    if not specs: raise ValueError("Feature selection produced no active specifications")
    if config.feature_search.get("initial_scope", "canonical_concepts") == "all_features": return specs, {}
    from .scan.pair_plan import canonical_concept_features
    return canonical_concept_features(specs, config.feature_search.get("canonical_scale_anchors"))


def _build_alpha_symbol_part(panel_path: str, specs: list, security_ids: list[str] | None, base_path: str) -> tuple[str, str]:
    from .features.base import FeatureBuilder
    filters=[("security_id", "in", security_ids)] if security_ids else None
    frame = pd.read_parquet(panel_path, filters=filters)
    for column in ("security_id", "symbol", "decision_grid", "price_basis"):
        if column in frame:
            frame[column] = frame[column].astype("category")
    for column in ("open", "high", "low", "close", "vwap", "research_open", "research_high", "research_low", "research_close", "split_factor"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], downcast="float")
    builder = FeatureBuilder(frame)
    emitted = builder.frame.emit.to_numpy(dtype=bool) if "emit" in builder.frame else np.ones(len(builder.frame), dtype=bool)
    emitted = emitted & ~builder.frame["observation_id"].duplicated().to_numpy()
    values = builder.build_many(specs).to_numpy(dtype=np.float32, na_value=np.nan)[emitted]
    ids_path = base_path + "_ids.npy"; values_path = base_path + "_values.npy"
    np.save(ids_path, builder.frame.loc[emitted, "observation_id"].to_numpy(dtype=np.int64), allow_pickle=False)
    np.save(values_path, values.astype(np.float32, copy=False), allow_pickle=False)
    return ids_path, values_path


def _build_alpha_security_lifecycle(panel_path: str, work: list[tuple[str, list]], security_id: str,
                                    base_root: str, host_memory_fraction: float) -> list[tuple[str, str, str]]:
    """Load one security once, reuse its primitive cache, emit bounded feature blocks."""
    from .features.base import FeatureBuilder
    frame=pd.read_parquet(panel_path,filters=[("security_id","=",security_id)])
    builder=FeatureBuilder(frame); emitted=builder.frame.emit.to_numpy(bool) if "emit" in builder.frame else np.ones(len(builder.frame),bool)
    emitted = emitted & ~builder.frame["observation_id"].duplicated().to_numpy()
    ids=builder.frame.loc[emitted,"observation_id"].to_numpy(np.int64); results=[]
    root=Path(base_root); root.mkdir(parents=True,exist_ok=True)
    for name,specs in work:
        # Active workers pause only while the machine is at its configured RAM
        # ceiling. They resume automatically as soon as memory is released.
        from .resources import _system_memory
        while True:
            available,total=_system_memory()
            reserved=max(1*(1<<30),int(total*(1-float(host_memory_fraction))))
            if available>reserved: break
            time.sleep(0.5)
        values=builder.build_many(specs).to_numpy(dtype=np.float32,na_value=np.nan)[emitted]
        stem=root/f"{security_id.replace(':','_')}__{name}"; ids_path=str(stem)+"_ids.npy"; values_path=str(stem)+"_values.npy"
        np.save(ids_path,ids,allow_pickle=False); np.save(values_path,values.astype(np.float32,copy=False),allow_pickle=False)
        results.append((name,ids_path,values_path))
    return results


def _edge_autopsy_parallel_capacity(compute, candidate_count: int, available_bytes: int,
                                     total_bytes: int, worker_budget_bytes: int) -> int:
    """Choose the largest CPU pool that fits the live host-RAM budget."""
    logical=max(1,os.cpu_count() or 1)
    cpu_limit=logical if compute.cpu_workers=="auto" else int(compute.cpu_workers)
    reserved=max(1*(1<<30),int(total_bytes*(1-float(compute.host_memory_fraction))))
    memory_limit=max(1,max(0,int(available_bytes)-reserved)//max(1,int(worker_budget_bytes)))
    return max(1,min(int(candidate_count),cpu_limit,memory_limit))


def _run_edge_autopsy_candidate_worker(config: AlphaDiscoveryConfig, candidate_index: int,
                                        row: dict, peer_feature_ids: tuple[str, ...],
                                        duckdb_memory_limit: str, threads_per_worker: int) -> dict | None:
    """Windows-spawn-safe entry point for one isolated candidate autopsy."""
    run=AlphaDiscoveryRun(config)
    run.initialize()
    return run._run_edge_autopsy_candidate(candidate_index,row,peer_feature_ids,
                                            duckdb_memory_limit,threads_per_worker)


class AlphaDiscoveryRun:
    def __init__(self, config: AlphaDiscoveryConfig) -> None:
        self.config = config
        self.root = Path(config.output_root) / config.run_name
        source_root = Path(__file__).resolve().parent
        digest = sha256()
        for path in sorted(source_root.rglob("*.py")):
            digest.update(path.relative_to(source_root).as_posix().encode()); digest.update(path.read_bytes())
        self.implementation_hash = digest.hexdigest()
        self._observation_cache: dict[str, pd.DataFrame] = {}
        self._feature_column_cache: dict[tuple[str, str], np.ndarray] = {}
        self.runtime_pair_cap = None
        self.runtime_worker_cap = None
        self.progress_callback = None
        self.abort_requested = None

    def _useful_progress(self,unit:str,completed:int=0,expected:int=0)->None:
        if self.abort_requested is not None and self.abort_requested.is_set(): raise TimeoutError(f"Stall watchdog aborted {unit}")
        if self.progress_callback is not None: self.progress_callback(unit,completed,expected)

    def initialize(self) -> None:
        for directory in ("single_results", "dual_trial_ledger", "dual_coarse_results", "dual_fine_results",
                          "dual_exact_results", "stability", "context_expansion", "formula_factory", "ml",
                          "edge_autopsy", "replication", "reports", "cache"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        manifest = self.root / "run_manifest.json"
        if manifest.exists():
            existing = json.loads(manifest.read_text(encoding="utf-8"))
            if existing.get("config_hash") != self.config.definition_hash or existing.get("implementation_hash") != self.implementation_hash:
                raise RuntimeError("Run directory belongs to a different configuration or implementation hash")
        else:
            self._atomic_json("run_manifest.json", {"run_name": self.config.run_name, "config_hash": self.config.definition_hash,
                                                    "implementation_hash": self.implementation_hash,
                                                    "created_at": datetime.now(timezone.utc).isoformat(), "standalone": True})
        if not (self.root / "research_state.json").exists():
            self._atomic_json("research_state.json", {"state": ResearchState.BUILD_ONLY.value})

    def execute(self, stage: str, dual_stage: str | None = None) -> dict:
        normalized = f"scan-duals-{dual_stage or 'coarse'}" if stage == "scan-duals" else stage
        if normalized not in STAGE_ORDER:
            raise ValueError(f"Unknown pipeline stage: {normalized}")
        self.initialize()
        marker = self.root / "checkpoints" / f"{normalized}.json"
        if marker.exists():
            payload = json.loads(marker.read_text(encoding="utf-8"))
            if payload.get("status") == "complete" and payload.get("config_hash") == self.config.definition_hash and payload.get("implementation_hash") == self.implementation_hash:
                return payload | {"resumed": True}
        started = datetime.now(timezone.utc).isoformat()
        self._atomic_json(f"checkpoints/{normalized}.json", {"stage": normalized, "status": "running", "started_at": started,
                                                             "config_hash": self.config.definition_hash, "implementation_hash": self.implementation_hash})
        handler = getattr(self, "_stage_" + normalized.replace("-", "_"))
        try:
            details = handler() or {}
        except Exception as error:
            self._atomic_json(f"checkpoints/{normalized}.json", {"stage": normalized, "status": "failed", "started_at": started,
                              "failed_at": datetime.now(timezone.utc).isoformat(), "config_hash": self.config.definition_hash,
                              "implementation_hash": self.implementation_hash,
                              "error_type": type(error).__name__, "error": str(error)})
            raise
        payload = {"stage": normalized, "status": "complete", "started_at": started,
                   "completed_at": datetime.now(timezone.utc).isoformat(), "config_hash": self.config.definition_hash,
                   "implementation_hash": self.implementation_hash} | details
        self._atomic_json(f"checkpoints/{normalized}.json", payload)
        return payload

    def _stage_validate_config(self) -> dict:
        self.config.validate()
        return {"project_root": str(Path(self.config.project_root).resolve())}

    def _stage_compile_registry(self) -> dict:
        bundle = self.compile_registry()
        return {"concepts": len(bundle.concepts), "features": len(bundle.features), "targets": len(bundle.targets)}

    def _symbol_filter(self, alias: str = "") -> str:
        symbols=[str(value).upper() for value in self.config.universe.get("symbols",[]) if str(value).strip()]
        benchmark=[str(value).upper() for value in self.config.source.benchmark_symbols]
        if symbols:
            literals=",".join("'"+value.replace("'","''")+"'" for value in sorted(set(symbols+benchmark)))
            return f" AND {alias}security_id IN (SELECT security_id FROM {self.config.source.security_master_table} WHERE upper(symbol) IN ({literals}))"
        smoke_limit=int(self.config.universe.get("smoke_symbol_limit",0) or 0)
        if not smoke_limit: return ""
        benchmark_sql=",".join(f"'{symbol}'" for symbol in self.config.source.benchmark_symbols)
        return (f" AND {alias}security_id IN (SELECT security_id FROM {self.config.source.security_master_table} WHERE symbol IN ({benchmark_sql}) "
                f"UNION SELECT security_id FROM (SELECT security_id FROM {self.config.source.security_master_table} "
                f"WHERE symbol NOT IN ({benchmark_sql}) ORDER BY symbol LIMIT {smoke_limit}))")

    def _snapshot_start(self) -> str:
        cached=getattr(self,"_derived_snapshot_start",None)
        if cached is not None: return cached
        if not self.config.warmup.get("auto_derive_transitive_history",True):
            start=str(self.config.warmup.get("snapshot_start",self.config.research_periods.discovery_start)); self._derived_snapshot_start=start; return start
        bundle=self.compile_registry(); scoped=[]
        for grid,enabled in self.config.decision_grids.items():
            if enabled: scoped.extend(_initial_feature_scope([item for item in bundle.features if item.decision_grid==grid],self.config)[0])
        required=max((int(item.minimum_history) for item in scoped),default=0)+int(self.config.warmup.get("safety_margin_sessions",5))
        import duckdb
        with duckdb.connect(self.config.source.duckdb_path,read_only=True) as connection:
            sessions=[row[0] for row in connection.execute(f"SELECT DISTINCT session_date FROM {self.config.source.bars_1m_raw_table} WHERE session_date < DATE '{self.config.research_periods.discovery_start}' ORDER BY session_date DESC LIMIT {required}").fetchall()]
        if len(sessions)<required and self.config.warmup.get("fail_if_full_coverage_warmup_missing",True):
            raise ValueError(f"Only {len(sessions)} prior sessions are available; canonical features require {required}")
        start=str(min(sessions)) if sessions else self.config.research_periods.discovery_start
        self._derived_snapshot_start=start
        return start

    def _stage_snapshot(self) -> dict:
        from .data.snapshot import RAW_COLUMNS, RESEARCH_COLUMNS, validate_snapshot
        from .data.source import DuckDBSource
        from .governance.access import AccessGate
        source_path = Path(self.config.source.duckdb_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Configured DuckDB catalog does not exist: {source_path}")
        import duckdb
        start = self._snapshot_start()
        end = self.config.research_periods.discovery_end
        from dataclasses import replace
        access_config=replace(self.config,warmup={**self.config.warmup,"snapshot_start":start})
        source = DuckDBSource(source_path, AccessGate(access_config, ResearchState.BUILD_ONLY))
        symbol_filter = self._symbol_filter()
        with duckdb.connect(str(source_path), read_only=True) as connection:
            row_count, symbols, sessions = connection.execute(
                f"SELECT count(*), count(DISTINCT security_id), count(DISTINCT session_date) "
                f"FROM {self.config.source.bars_1m_raw_table} "
                f"WHERE session_date BETWEEN DATE '{start}' AND DATE '{end}'{symbol_filter}"
            ).fetchone()
        if int(row_count) > 2_000_000:
            snapshot = self.root / "snapshot"; snapshot.mkdir(parents=True, exist_ok=True)
            validation_path = Path(self.config.project_root) / "data" / "DATA_VALIDATION.json"
            validation_hash = sha256(validation_path.read_bytes()).hexdigest() if validation_path.exists() else None
            payload = {
                "mode": "immutable_catalog_reference", "catalog": str(source_path.resolve()),
                "start": str(start), "end": str(end), "rows": int(row_count),
                "symbols": int(symbols), "sessions": int(sessions),
                "catalog_validation_sha256": validation_hash,
            }
            self._atomic_json("snapshot/source_reference.json", payload)
            return {"rows": int(row_count), "symbols": int(symbols), "sessions": int(sessions),
                    "snapshot_fingerprint": sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                    "snapshot_mode": "immutable_catalog_reference"}
        raw_available = source.table_columns(self.config.source.bars_1m_raw_table)
        raw_columns = tuple(sorted(RAW_COLUMNS | ({"vwap", "trade_count"} & raw_available)))
        where = symbol_filter.removeprefix(" AND ") or None
        raw = source.read_table(self.config.source.bars_1m_raw_table, raw_columns, where=where)
        research = source.read_table(self.config.source.bars_1m_research_table, tuple(sorted(RESEARCH_COLUMNS)), where=where)
        validation = validate_snapshot(raw, research, self.config.source.alpaca_feed_required,
                                       self.config.source.alpaca_execution_adjustment_required)
        selected_ids = tuple(sorted(raw.security_id.astype(str).unique()))
        membership_where = "security_id IN (" + ",".join("'" + value.replace("'", "''") + "'" for value in selected_ids) + ")"
        membership = source.read_table(self.config.source.membership_table,
                                       ("security_id", "session_date", "in_universe"), where=membership_where)
        security_columns = source.table_columns(self.config.source.security_master_table)
        required_security = {"security_id", "symbol"}
        if not required_security.issubset(security_columns):
            raise ValueError(f"Security master missing columns: {sorted(required_security - security_columns)}")
        security = source.read_dimension(self.config.source.security_master_table, tuple(sorted(required_security)))
        security = security[security.security_id.astype(str).isin(selected_ids)].copy()
        actions_path = Path(self.config.source.corporate_actions_path)
        if not actions_path.exists():
            raise FileNotFoundError(f"Corporate-action ledger does not exist: {actions_path}")
        actions = pd.read_parquet(actions_path)
        if not {"security_id", "session_date", "split_factor"}.issubset(actions):
            raise ValueError("Corporate-action ledger must contain security_id, session_date, and split_factor")
        snapshot = self.root / "snapshot"; snapshot.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(snapshot / "bars_1m_raw.parquet", index=False)
        research.to_parquet(snapshot / "bars_1m_research.parquet", index=False)
        membership.to_parquet(snapshot / "membership.parquet", index=False)
        security.to_parquet(snapshot / "security_master.parquet", index=False)
        actions.to_parquet(snapshot / "corporate_actions.parquet", index=False)
        validation.write(snapshot / "validation.json")
        return {"rows": validation.rows, "symbols": validation.symbols, "sessions": validation.sessions,
                "snapshot_fingerprint": validation.fingerprint}

    def _require(self, stage: str) -> dict:
        marker = self.root / "checkpoints" / f"{stage}.json"
        if not marker.exists():
            raise FileNotFoundError(f"Required stage has not completed: {stage}")
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if payload.get("status") != "complete" or payload.get("config_hash") != self.config.definition_hash or payload.get("implementation_hash") != self.implementation_hash:
            raise RuntimeError(f"Required stage is incomplete or incompatible: {stage}")
        return payload

    def _stage_build_panel(self) -> dict:
        from .data.panel import build_calculation_panel
        from .data.universe import apply_point_in_time_universe
        self._require("snapshot")
        snapshot = self.root / "snapshot"
        if not (snapshot / "bars_1m_raw.parquet").exists():
            return self._build_panels_out_of_core()
        raw = pd.read_parquet(snapshot / "bars_1m_raw.parquet")
        research = pd.read_parquet(snapshot / "bars_1m_research.parquet")
        membership = pd.read_parquet(snapshot / "membership.parquet")
        security = pd.read_parquet(snapshot / "security_master.parquet")
        research_columns = [column for column in research if column not in {"security_id", "bar_start_ts_utc"}]
        bars = raw.merge(research[["security_id", "bar_start_ts_utc", *research_columns]],
                         on=["security_id", "bar_start_ts_utc"], how="left", validate="one_to_one")
        eligible_bars = apply_point_in_time_universe(bars, membership, security)
        benchmark_ids = set(security.loc[security.symbol.isin(self.config.source.benchmark_symbols), "security_id"])
        benchmark_bars = bars[bars.security_id.isin(benchmark_ids)].copy(); benchmark_bars["in_universe"] = False
        eligible_bars = pd.concat([eligible_bars, benchmark_bars], ignore_index=True).drop_duplicates(["security_id", "bar_start_ts_utc"])
        panel_root = self.root / "cache" / "panels"; panel_root.mkdir(parents=True, exist_ok=True)
        calculation_root = self.root / "cache" / "calculation_panels"; calculation_root.mkdir(parents=True, exist_ok=True)
        rows = 0
        for grid, enabled in self.config.decision_grids.items():
            if not enabled: continue
            calculation, panel = build_calculation_panel(eligible_bars, grid, self.config.source.benchmark_symbols[0])
            calculation.loc[pd.to_datetime(calculation.session_date).lt(pd.Timestamp(self.config.research_periods.discovery_start)), "emit"] = False
            calculation["observation_id"] = -1
            order = calculation.loc[calculation.emit].sort_values(["decision_ts", "security_id"], kind="mergesort").index
            calculation.loc[order, "observation_id"] = np.arange(len(order), dtype=np.int64)
            panel = calculation.loc[calculation.emit].sort_values(["decision_ts", "security_id"], kind="mergesort").copy()
            calculation.to_parquet(calculation_root / f"{grid}.parquet", index=False)
            panel.to_parquet(panel_root / f"{grid}.parquet", index=False); rows += len(panel)
            self._write_reusable_indexes(grid,panel_root/f"{grid}.parquet")
        return {"panel_rows": rows, "enabled_grids": sum(bool(value) for value in self.config.decision_grids.values())}

    def _build_panels_out_of_core(self) -> dict:
        import duckdb
        source = self.config.source
        start = self._snapshot_start()
        end = self.config.research_periods.discovery_end
        from .resources import calibrated_resources
        workers,memory_limit,_=calibrated_resources(self.config.compute); workers=min(workers,self.runtime_worker_cap) if self.runtime_worker_cap else workers
        temp = Path(self.config.compute.duckdb_temp_directory); temp.mkdir(parents=True, exist_ok=True)
        panel_root = self.root / "cache" / "panels"; panel_root.mkdir(parents=True, exist_ok=True)
        calculation_root = self.root / "cache" / "calculation_panels"; calculation_root.mkdir(parents=True, exist_ok=True)
        benchmark_sql = ",".join(f"'{symbol}'" for symbol in self.config.source.benchmark_symbols)
        symbol_filter=self._symbol_filter("r.")
        total = 0; built = 0
        with duckdb.connect(source.duckdb_path, read_only=True) as connection:
            connection.execute(f"SET threads={workers}")
            connection.execute(f"SET memory_limit='{memory_limit}'")
            connection.execute(f"SET temp_directory='{temp.as_posix().replace(chr(39), chr(39)*2)}'")
            # The raw/research/PIT join is the dominant panel I/O. Materialize
            # it once and reuse it for every grid instead of scanning and
            # joining the 1m catalog three times.
            joined_path=self.root/"cache"/"panel_base_joined.parquet"; joined_sql=joined_path.as_posix().replace("'","''")
            if not joined_path.exists():
                joined_temp=joined_path.with_suffix(".tmp.parquet"); joined_temp_sql=joined_temp.as_posix().replace("'","''")
                connection.execute(f"""COPY (SELECT r.security_id,r.symbol,r.session_date,r.bar_start_ts_utc,r.bar_end_ts_utc,r.availability_ts_utc,
                    q.research_open AS open,q.research_high AS high,q.research_low AS low,q.research_close AS close,
                    r.open AS execution_open,r.high AS execution_high,r.low AS execution_low,r.close AS execution_close,
                    r.volume,r.vwap/coalesce(nullif(q.split_factor,0),1) AS vwap,r.trade_count,q.split_factor,q.price_basis,
                    coalesce(m.in_universe,false) AS in_universe
                    FROM {source.bars_1m_raw_table} r JOIN {source.bars_1m_research_table} q
                      ON q.security_id=r.security_id AND q.bar_start_ts_utc=r.bar_start_ts_utc
                    LEFT JOIN {source.membership_table} m ON m.security_id=r.security_id AND m.session_date=r.session_date
                    WHERE r.session_date BETWEEN DATE '{start}' AND DATE '{end}'
                      AND (coalesce(m.in_universe,false) OR r.symbol IN ({benchmark_sql})) {symbol_filter})
                    TO '{joined_temp_sql}' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 250000)""")
                joined_temp.replace(joined_path)
            for grid, enabled in self.config.decision_grids.items():
                if not enabled:
                    continue
                calculation_destination = (calculation_root / f"{grid}.parquet").as_posix().replace("'", "''")
                panel_destination = (panel_root / f"{grid}.parquet").as_posix().replace("'", "''")
                regular = "strftime(timezone('America/New_York', bar_start_ts_utc), '%H:%M') >= '09:30' AND strftime(timezone('America/New_York', bar_start_ts_utc), '%H:%M') < '16:00'"
                cutoff = "" if grid != "preclose_1555" else "WHERE strftime(timezone('America/New_York', availability_ts_utc), '%H:%M') <= '15:55'"
                base = f"""
                    WITH regular_bars AS (SELECT * FROM read_parquet('{joined_sql}') WHERE {regular}),
                    session_schedule AS (
                      SELECT session_date,max(availability_ts_utc) AS canonical_close_ts FROM regular_bars
                      WHERE symbol='{self.config.source.benchmark_symbols[0]}' GROUP BY session_date
                    ), joined AS (SELECT * FROM regular_bars {cutoff}), daily_close AS (
                      SELECT r.security_id,r.session_date,
                        CASE WHEN max(r.availability_ts_utc)=s.canonical_close_ts THEN last(r.close ORDER BY r.availability_ts_utc) END AS session_final_close
                      FROM regular_bars r JOIN session_schedule s USING(session_date)
                      GROUP BY r.security_id,r.session_date,s.canonical_close_ts
                    ), close_history AS (
                      SELECT *,lag(session_final_close) OVER(PARTITION BY security_id ORDER BY session_date) AS prior_session_close
                      FROM daily_close
                    )
                """
                if grid.startswith("intraday"):
                    step = 5 if grid == "intraday_5m" else 1
                    calculation_query = base + f"""
                      , staged AS (SELECT j.*,
                         first_value(close) OVER(PARTITION BY j.security_id,j.session_date ORDER BY availability_ts_utc) AS session_open,
                         h.prior_session_close,availability_ts_utc AS decision_ts,'{grid}' AS decision_grid,
                         ((extract(minute FROM timezone('America/New_York',availability_ts_utc)) % {step}=0) AND session_date>=DATE '{self.config.research_periods.discovery_start}') AS emit,
                         close/lag(close,{step}) OVER(PARTITION BY j.security_id,j.session_date ORDER BY availability_ts_utc)-1 AS bucket_return,
                         -1::BIGINT AS observation_id
                       FROM joined j JOIN close_history h USING(security_id,session_date))
                      SELECT staged.*,
                         max(CASE WHEN symbol='{self.config.source.benchmark_symbols[0]}' THEN close END) OVER(PARTITION BY decision_ts) AS benchmark_close,
                         max(CASE WHEN symbol='{self.config.source.benchmark_symbols[0]}' THEN bucket_return END) OVER(PARTITION BY decision_ts) AS benchmark_bucket_return,
                         max(CASE WHEN symbol='{self.config.source.benchmark_symbols[0]}' THEN session_open END) OVER(PARTITION BY decision_ts) AS benchmark_session_open,
                         max(CASE WHEN symbol='{self.config.source.benchmark_symbols[0]}' THEN prior_session_close END) OVER(PARTITION BY decision_ts) AS benchmark_prior_session_close
                      FROM staged
                    """
                else:
                    required_decision = ("a.availability_ts_utc=ss.canonical_close_ts" if grid == "daily_close" else
                                         "strftime(timezone('America/New_York',a.availability_ts_utc),'%H:%M')='15:55'")
                    calculation_query = base + f"""
                      , enriched AS (
                        SELECT *,first_value(open) OVER(PARTITION BY security_id,session_date ORDER BY availability_ts_utc) AS open0,
                         min(availability_ts_utc) OVER(PARTITION BY security_id,session_date) AS first_ts,
                         max(availability_ts_utc) OVER(PARTITION BY security_id,session_date) AS last_ts,
                         lag(sign(close-vwap)) OVER(PARTITION BY security_id,session_date ORDER BY availability_ts_utc) AS prior_vwap_sign,
                         sum(volume) OVER(PARTITION BY security_id,session_date ORDER BY availability_ts_utc ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS volume_5m
                        FROM joined
                      ), aggregated AS (
                        SELECT security_id,symbol,session_date,min(bar_start_ts_utc) AS bar_start_ts_utc,max(bar_end_ts_utc) AS bar_end_ts_utc,
                         max(availability_ts_utc) AS availability_ts_utc,first(open ORDER BY availability_ts_utc) AS open,max(high) AS high,min(low) AS low,
                         last(close ORDER BY availability_ts_utc) AS close,sum(volume) AS volume,
                         sum(vwap*volume)/nullif(sum(volume),0) AS vwap,sum(trade_count) AS trade_count,last(split_factor ORDER BY availability_ts_utc) AS split_factor,
                         last(price_basis ORDER BY availability_ts_utc) AS price_basis,bool_or(in_universe) AS in_universe,
                         first(open ORDER BY availability_ts_utc) AS session_open,last(close ORDER BY availability_ts_utc) AS session_close,
                         max(high) AS session_high,min(low) AS session_low,sum(vwap*volume)/nullif(sum(volume),0) AS session_vwap,
                         max(volume)/nullif(sum(volume),0) AS largest_1m_volume_share_session,
                         max(volume_5m)/nullif(sum(volume),0) AS largest_5m_volume_share_session,
                         sum(CASE WHEN prior_vwap_sign IS NOT NULL AND sign(close-vwap)<>prior_vwap_sign THEN 1 ELSE 0 END)::DOUBLE/nullif(count(*)-1,0) AS vwap_cross_count,
                         avg((close>vwap)::INT) AS time_above_vwap,
                         arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 5 MINUTE)/open0-1 AS opening_return_5m,
                         arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 10 MINUTE)/open0-1 AS opening_return_10m,
                         arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 15 MINUTE)/open0-1 AS opening_return_15m,
                         arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 30 MINUTE)/open0-1 AS opening_return_30m,
                         arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 60 MINUTE)/open0-1 AS opening_return_60m,
                         last(close ORDER BY availability_ts_utc)/arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=last_ts-INTERVAL 5 MINUTE)-1 AS closing_return_5m,
                         last(close ORDER BY availability_ts_utc)/arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=last_ts-INTERVAL 10 MINUTE)-1 AS closing_return_10m,
                         last(close ORDER BY availability_ts_utc)/arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=last_ts-INTERVAL 15 MINUTE)-1 AS closing_return_15m,
                         last(close ORDER BY availability_ts_utc)/arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=last_ts-INTERVAL 30 MINUTE)-1 AS closing_return_30m,
                         last(close ORDER BY availability_ts_utc)/arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=last_ts-INTERVAL 60 MINUTE)-1 AS closing_return_60m,
                         (max(high) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 15 MINUTE)-min(low) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 15 MINUTE))/open0 AS opening_range_pct_15m,
                         (max(high) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 30 MINUTE)-min(low) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 30 MINUTE))/open0 AS opening_range_pct_30m,
                         (max(high) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 60 MINUTE)-min(low) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 60 MINUTE))/open0 AS opening_range_pct_60m,
                         sum(volume) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 15 MINUTE) AS opening_volume_15m,
                         sum(volume) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 30 MINUTE) AS opening_volume_30m,
                         sum(volume) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 60 MINUTE) AS opening_volume_60m,
                         arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 15 MINUTE) AS gap_fill_price_15m,
                         arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 30 MINUTE) AS gap_fill_price_30m,
                         arg_max(close,availability_ts_utc) FILTER(WHERE availability_ts_utc<=first_ts+INTERVAL 60 MINUTE) AS gap_fill_price_60m,
                         sum(volume) FILTER(WHERE availability_ts_utc>last_ts-INTERVAL 15 MINUTE)/nullif(sum(volume),0) AS closing_volume_share_15m,
                         sum(volume) FILTER(WHERE availability_ts_utc>last_ts-INTERVAL 30 MINUTE)/nullif(sum(volume),0) AS closing_volume_share_30m,
                         sum(volume) FILTER(WHERE availability_ts_utc>last_ts-INTERVAL 60 MINUTE)/nullif(sum(volume),0) AS closing_volume_share_60m,
                         arg_max(close,availability_ts_utc) FILTER(WHERE strftime(timezone('America/New_York',availability_ts_utc),'%H:%M')<='12:00')/open0-1 AS open_to_midday_return,
                         last(close ORDER BY availability_ts_utc)/arg_max(close,availability_ts_utc) FILTER(WHERE strftime(timezone('America/New_York',availability_ts_utc),'%H:%M')<='12:00')-1 AS midday_to_close_return
                        FROM enriched GROUP BY security_id,symbol,session_date,open0
                      )
                      SELECT a.*,h.prior_session_close,availability_ts_utc AS decision_ts,'{grid}' AS decision_grid,(a.session_date>=DATE '{self.config.research_periods.discovery_start}') AS emit,
                        close/lag(close) OVER(PARTITION BY a.security_id ORDER BY session_date)-1 AS bucket_return,
                        max(CASE WHEN symbol='{self.config.source.benchmark_symbols[0]}' THEN close END) OVER(PARTITION BY availability_ts_utc) AS benchmark_close,
                        NULL::DOUBLE AS benchmark_bucket_return,
                        max(CASE WHEN symbol='{self.config.source.benchmark_symbols[0]}' THEN session_open END) OVER(PARTITION BY availability_ts_utc) AS benchmark_session_open,
                        max(CASE WHEN symbol='{self.config.source.benchmark_symbols[0]}' THEN h.prior_session_close END) OVER(PARTITION BY availability_ts_utc) AS benchmark_prior_session_close,
                        -1::BIGINT AS observation_id
                      FROM aggregated a JOIN close_history h USING(security_id,session_date)
                      JOIN session_schedule ss USING(session_date)
                      WHERE {required_decision}
                    """
                connection.execute(f"COPY ({calculation_query}) TO '{calculation_destination}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)")
                selector = "emit"
                panel_query = f"SELECT row_number() OVER(ORDER BY decision_ts,security_id)-1 AS new_id,* EXCLUDE(observation_id) FROM read_parquet('{calculation_destination}') WHERE {selector}"
                connection.execute(f"COPY (SELECT new_id AS observation_id,* EXCLUDE(new_id) FROM ({panel_query})) TO '{panel_destination}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)")
                connection.execute(f"CREATE OR REPLACE TEMP TABLE observation_map AS SELECT security_id,decision_ts,observation_id FROM read_parquet('{panel_destination}')")
                remapped = calculation_destination + ".remapped"
                connection.execute(f"COPY (SELECT c.* EXCLUDE(observation_id),coalesce(m.observation_id,-1) AS observation_id FROM read_parquet('{calculation_destination}') c LEFT JOIN observation_map m USING(security_id,decision_ts)) TO '{remapped}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)")
                Path(remapped).replace(Path(calculation_destination))
                count = int(connection.execute(f"SELECT count(*) FROM read_parquet('{panel_destination}')").fetchone()[0])
                total += count; built += 1; self._useful_progress(f"panel:{grid}",built,sum(bool(x) for x in self.config.decision_grids.values()))
                self._write_reusable_indexes(grid,Path(panel_destination))
            joined_path.unlink(missing_ok=True)
        return {"panel_rows": total, "enabled_grids": built, "mode": "duckdb_out_of_core",
                "cpu_workers": workers, "memory_limit": memory_limit}

    def _write_reusable_indexes(self,grid: str,panel_path: Path) -> None:
        import duckdb
        destination=self.root/"cache"/"indexes"/f"{grid}.parquet"; destination.parent.mkdir(parents=True,exist_ok=True)
        source=panel_path.as_posix().replace("'","''"); target=destination.as_posix().replace("'","''")
        with duckdb.connect() as connection:
            connection.execute(f"""COPY (SELECT observation_id,security_id,session_date,decision_ts,
                row_number() OVER(PARTITION BY security_id,session_date ORDER BY decision_ts)-1 AS security_session_row,
                dense_rank() OVER(ORDER BY session_date)-1 AS session_index
                FROM read_parquet('{source}') ORDER BY observation_id) TO '{target}'
                (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 250000)""")

    def _stage_build_features(self) -> dict:
        from collections import deque
        from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
        from .cache.feature_store import ArrayStore
        from .features.base import FeatureBuilder
        started=time.perf_counter(); self._require("build-panel"); bundle = self.compile_registry(); blocks = 0; columns = 0; resumed_blocks = 0
        global_telemetry=[]
        panel_root = self.root / "cache" / "panels"; feature_root = self.root / "cache" / "features"
        from .resources import calibrated_resources, host_memory_headroom
        workers,memory_limit,resource_telemetry=calibrated_resources(self.config.compute); workers=min(workers,self.runtime_worker_cap) if self.runtime_worker_cap else workers
        configured_block = self.config.compute.feature_block_size
        block_size = min(8,workers) if configured_block == "auto" else int(configured_block)
        for grid, enabled in self.config.decision_grids.items():
            if not enabled: continue
            import duckdb
            import pyarrow.parquet as pq
            calculation_path = self.root / "cache" / "calculation_panels" / f"{grid}.parquet"
            emitted_path = panel_root / f"{grid}.parquet"
            observation_count = int(pq.ParquetFile(emitted_path).metadata.num_rows)
            if observation_count <= 0:
                raise ValueError(f"Emitted feature panel is empty: {emitted_path}")
            with duckdb.connect() as connection:
                minimum, maximum, distinct_count = connection.execute(
                    "SELECT min(observation_id),max(observation_id),count(DISTINCT observation_id) FROM read_parquet(?)",
                    [str(emitted_path)],
                ).fetchone()
                security_ids = [str(row[0]) for row in connection.execute(
                    "SELECT DISTINCT security_id FROM read_parquet(?) ORDER BY security_id", [str(calculation_path)]
                ).fetchall()]
            if int(minimum) != 0 or int(maximum) != observation_count - 1 or int(distinct_count) != observation_count:
                raise ValueError(f"Observation IDs are not dense and unique for {grid}")
            # Partition once by security. The old path made every worker scan the
            # complete multi-gigabyte panel for every feature block.
            local_panel = self._ensure_local_feature_panel(grid, calculation_path, workers)
            groups: list[list[str]] = [[security_id] for security_id in security_ids]
            store = ArrayStore(feature_root / grid)
            registered_specs = [item for item in bundle.features if item.decision_grid == grid]
            all_specs, _ = _initial_feature_scope(registered_specs, self.config)
            work: list[tuple[str, list, bool]] = []
            for family in sorted({item.family for item in all_specs}):
                family_specs = [item for item in all_specs if item.family == family]
                for global_flag in (False, True):
                    selected = [item for item in family_specs if _alpha_feature_is_global(item) == global_flag]
                    for part, offset in enumerate(range(0, len(selected), block_size)):
                        batch = selected[offset:offset + block_size]
                        if batch:
                            work.append((f"{family}__{'global' if global_flag else 'local'}__{part:03d}", batch, global_flag))
            local_work = [item for item in work if not item[2]]
            global_work = [item for item in work if item[2]]
            panel = None; builder = None
            pending=[]
            for name,batch,_ in local_work:
                expected=[item.feature_id for item in batch]
                try:
                    existing,existing_columns=store.read(name)
                    if existing.shape[0]==observation_count and existing_columns==expected:
                        blocks+=1; columns+=len(batch); resumed_blocks+=1; continue
                except (FileNotFoundError,ValueError,KeyError): pass
                pending.append((name,batch))
            if pending:
                part_root=store.root/".parts"/"security_lifecycle"; part_root.mkdir(parents=True,exist_ok=True)
                wave_size=8
                with ProcessPoolExecutor(max_workers=workers) as process_pool:
                    for wave_index,wave_start in enumerate(range(0,len(pending),wave_size)):
                        self._useful_progress(f"feature:{grid}",wave_start,len(pending))
                        wave=pending[wave_start:wave_start+wave_size]; outputs={}
                        progress_path=part_root/f"progress-{wave_index:04d}.json"
                        progress_key={"blocks":[name for name,_ in wave],"observation_count":observation_count}; completed_security={}
                        if progress_path.exists():
                            saved=json.loads(progress_path.read_text(encoding="utf-8"))
                            if saved.get("key")==progress_key: completed_security={str(k):int(v) for k,v in saved.get("completed_security",{}).items()}
                        for name,batch in wave:
                            temporary=store.root/f"{name}.tmp.npy"; mode="r+" if temporary.exists() else "w+"
                            values=np.lib.format.open_memmap(temporary,mode=mode,dtype=np.float32,shape=(observation_count,len(batch)))
                            if values.shape!=(observation_count,len(batch)): raise ValueError(f"Partial feature block shape mismatch: {temporary}")
                            outputs[name]=(values,temporary,store.root/f"{name}.npy",batch)
                        written={name:sum(completed_security.values()) for name,_ in wave}; uncommitted={}
                        def commit_progress() -> None:
                            if not uncommitted: return
                            for values,_,_,_ in outputs.values(): values.flush()
                            completed_security.update(uncommitted); uncommitted.clear()
                            pending_progress=progress_path.with_suffix(".tmp.json")
                            pending_progress.write_text(json.dumps({"key":progress_key,"completed_security":completed_security},indent=2),encoding="utf-8")
                            pending_progress.replace(progress_path)
                        queued=deque(security_id for security_id in security_ids if security_id not in completed_security)
                        futures={}; last_submit=0.0
                        while queued or futures:
                            available,reserved,_=host_memory_headroom(self.config.compute)
                            if queued and len(futures)<workers and (not futures or available>reserved) and time.monotonic()-last_submit>=0.1:
                                security_id=queued.popleft()
                                future=process_pool.submit(_build_alpha_security_lifecycle,str(local_panel),wave,security_id,
                                                           str(part_root),float(self.config.compute.host_memory_fraction))
                                futures[future]=security_id; last_submit=time.monotonic()
                            done,_=wait(futures,timeout=0.1,return_when=FIRST_COMPLETED) if futures else (set(),set())
                            for future in done:
                                security_id=futures.pop(future); row_count=None
                                for name,ids_path,values_path in future.result():
                                    ids=np.load(ids_path,mmap_mode="r"); part_values=np.load(values_path,mmap_mode="r"); dense_ids=np.array(ids,dtype=np.int64,copy=True)
                                    if len(dense_ids) and (dense_ids.min()<0 or dense_ids.max()>=observation_count): raise ValueError(f"Worker returned out-of-range observation IDs for {grid}")
                                    if row_count is None: row_count=len(dense_ids)
                                    elif row_count!=len(dense_ids): raise ValueError(f"Worker block row counts disagree for {security_id}")
                                    outputs[name][0][dense_ids,:]=part_values; written[name]+=len(dense_ids)
                                    del ids,part_values; Path(ids_path).unlink(); Path(values_path).unlink()
                                uncommitted[security_id]=int(row_count or 0)
                                self._useful_progress(f"feature:{grid}:security",len(completed_security)+len(uncommitted),len(security_ids))
                                if len(uncommitted)>=8: commit_progress()
                        commit_progress()
                        for name,(values,temporary,target,batch) in outputs.items():
                            if written[name]!=observation_count: raise ValueError(f"Local feature block {name} wrote {written[name]:,}/{observation_count:,} rows")
                            values.flush(); values._mmap.close(); temporary.replace(target)
                            meta=target.with_suffix(".json"); tmp_meta=meta.with_suffix(".tmp.json")
                            tmp_meta.write_text(json.dumps({"shape":[observation_count,len(batch)],"dtype":"float32","columns":[item.feature_id for item in batch]},indent=2),encoding="utf-8"); tmp_meta.replace(meta)
                            blocks+=1; columns+=len(batch)
                        progress_path.unlink(missing_ok=True)
            # Global/cross-sectional families need the combined panel. Run them
            # only after the process pool exits so idle workers cannot retain RAM.
            pending_global=[]
            for name, batch, _ in global_work:
                expected_columns = [item.feature_id for item in batch]
                try:
                    existing, existing_columns = store.read(name)
                    if existing.shape[0] == observation_count and existing_columns == expected_columns:
                        blocks += 1; columns += len(batch); resumed_blocks += 1
                        continue
                except (FileNotFoundError, ValueError, KeyError):
                    pass
                target = store.root / f"{name}.npy"; temporary = store.root / f"{name}.tmp.npy"
                values = np.lib.format.open_memmap(temporary, mode="w+", dtype=np.float32,
                                                   shape=(observation_count, len(batch)))
                pending_global.append((name,batch,values,temporary,target,expected_columns))
            if pending_global and grid.startswith("intraday"):
                emitted_count,telemetry=self._build_global_feature_chunks(calculation_path,[(name,batch,values) for name,batch,values,_,_,_ in pending_global])
                global_telemetry.append({"grid":grid}|telemetry)
                if emitted_count!=observation_count: raise ValueError(f"Chunked global panel emitted {emitted_count:,}/{observation_count:,} rows")
            if pending_global and not grid.startswith("intraday"):
                panel = pd.read_parquet(calculation_path)
                self._compact_feature_frame(panel); builder = FeatureBuilder(panel)
                emitted = builder.frame.emit.to_numpy(dtype=bool) if "emit" in builder.frame else np.ones(len(builder.frame), dtype=bool)
                emitted = emitted & ~builder.frame["observation_id"].duplicated().to_numpy()
                emitted_ids = builder.frame.loc[emitted, "observation_id"].to_numpy(dtype=np.int64)
                if len(emitted_ids) != observation_count: raise ValueError(f"Global feature panel emitted {len(emitted_ids):,}/{observation_count:,} rows")
                for _,batch,values,_,_,_ in pending_global:
                    values[emitted_ids,:]=builder.build_many(batch).to_numpy(dtype=np.float32,na_value=np.nan)[emitted]
                    builder._direct_cache.clear()
            for _,batch,values,temporary,target,expected_columns in pending_global:
                values.flush(); values._mmap.close(); temporary.replace(target)
                meta=target.with_suffix(".json"); tmp_meta=meta.with_suffix(".tmp.json")
                tmp_meta.write_text(json.dumps({"shape":[observation_count,len(batch)],"dtype":"float32","columns":expected_columns},indent=2),encoding="utf-8"); tmp_meta.replace(meta)
                blocks+=1; columns+=len(batch)
            observation_destination = feature_root / grid / "observations.parquet"
            escaped_source = emitted_path.as_posix().replace("'", "''")
            escaped_destination = observation_destination.as_posix().replace("'", "''")
            with duckdb.connect() as connection:
                connection.execute(
                    f"COPY (SELECT observation_id,security_id,session_date,decision_ts,decision_grid "
                    f"FROM read_parquet('{escaped_source}') ORDER BY observation_id) TO '{escaped_destination}' "
                    "(FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 250000)"
                )
        self._atomic_json("cache/feature_build_resources.json", {
            "cpu_workers": workers, "host_memory_fraction": self.config.compute.host_memory_fraction,
            "duckdb_memory_limit": memory_limit,"calibration":resource_telemetry,
            "feature_block_size": block_size,"local_wave_size":8,"global_chunks":global_telemetry,
            "storage": str(feature_root.resolve()),
        })
        elapsed=time.perf_counter()-started
        return {"feature_blocks":blocks,"feature_columns":columns,"resumed_blocks":resumed_blocks,
                "cpu_workers":workers,"host_memory_fraction":self.config.compute.host_memory_fraction,
                "wall_seconds":elapsed,"features_per_second":columns/max(elapsed,1e-9)}

    @staticmethod
    def _compact_feature_frame(frame: pd.DataFrame) -> None:
        for column in ("security_id","symbol","decision_grid","price_basis"):
            if column in frame: frame[column]=frame[column].astype("category")
        for column in ("open","high","low","close","vwap","research_open","research_high","research_low","research_close","split_factor"):
            if column in frame: frame[column]=pd.to_numeric(frame[column],downcast="float")

    def _build_global_feature_chunks(self,calculation_path: Path,work: list[tuple[str,list,np.memmap]]) -> tuple[int,dict]:
        """Build intraday cross-sectional features with bounded chronological history."""
        import duckdb
        with duckdb.connect() as connection:
            all_sessions=[pd.Timestamp(row[0]) for row in connection.execute("SELECT DISTINCT session_date FROM read_parquet(?) ORDER BY session_date",[str(calculation_path)]).fetchall()]
            sessions=[pd.Timestamp(row[0]) for row in connection.execute("SELECT DISTINCT session_date FROM read_parquet(?) WHERE emit ORDER BY session_date",[str(calculation_path)]).fetchall()]
        positions={session:index for index,session in enumerate(all_sessions)}
        history=max(25,max((int(item.minimum_history) for _,batch,_ in work for item in batch),default=0)); written=0
        from .features.base import FeatureBuilder
        sample=pd.read_parquet(calculation_path,filters=[("session_date","=",sessions[0].date())]); self._compact_feature_frame(sample)
        sample_bytes=max(1,int(sample.memory_usage(index=True,deep=True).sum())); sample_rows=max(1,len(sample))
        try:
            import psutil
            vm=psutil.virtual_memory(); rss_process=psutil.Process(); available=int(vm.available); total=int(vm.total)
        except ImportError:
            rss_process=None; available=total=32*(1<<30)
        reserve=max(4*(1<<30),int(total*(1-float(self.config.compute.host_memory_fraction))))
        budget=max(512*(1<<20),min(available-reserve,int(total*.60)))
        feature_count=sum(len(batch) for _,batch,_ in work)
        per_session=max(sample_bytes*3,sample_bytes+sample_rows*8*(feature_count+16))
        included_capacity=max(1,budget//max(per_session,1)); chunk_size=max(1,min(40,int(included_capacity)-history))
        retained=None; loaded_end=None; peak_rss=0
        for offset in range(0,len(sessions),chunk_size):
            current=sessions[offset:offset+chunk_size]; first=max(0,positions[current[0]]-history); included=all_sessions[first:positions[current[-1]]+1]
            if retained is None:
                retained=pd.read_parquet(calculation_path,filters=[("session_date",">=",included[0].date()),("session_date","<=",included[-1].date())])
            else:
                retained=retained[pd.to_datetime(retained.session_date).ge(included[0])]
                if loaded_end<included[-1]:
                    appended=pd.read_parquet(calculation_path,filters=[("session_date",">",loaded_end.date()),("session_date","<=",included[-1].date())])
                    retained=pd.concat([retained,appended],ignore_index=True)
            loaded_end=included[-1]; self._compact_feature_frame(retained)
            builder=FeatureBuilder(retained); dates=pd.to_datetime(builder.frame.session_date)
            emit=builder.frame.emit.to_numpy(bool)&dates.isin(current).to_numpy()
            emit = emit & ~builder.frame["observation_id"].duplicated().to_numpy()
            ids=builder.frame.loc[emit,"observation_id"].to_numpy(np.int64)
            for _,batch,values in work:
                if len(ids): values[ids,:]=builder.build_many(batch).to_numpy(dtype=np.float32,na_value=np.nan)[emit]
                builder._direct_cache.clear()
            written+=len(ids)
            for _,_,values in work: values.flush()
            if rss_process is not None: peak_rss=max(peak_rss,int(rss_process.memory_info().rss))
        return written,{"emitted_sessions_per_chunk":chunk_size,"history_sessions":history,"budget_bytes":budget,
                        "sample_session_bytes":sample_bytes,"estimated_bytes_per_session":per_session,"peak_process_rss_bytes":peak_rss}

    def _ensure_local_feature_panel(self, grid: str, calculation_path: Path, workers: int) -> Path:
        """Create a resume-safe, security-partitioned panel for local workers."""
        import duckdb
        destination = self.root / "cache" / "local_feature_panels" / grid
        manifest = self.root / "cache" / "local_feature_panels" / f"{grid}.json"
        source = {"size": calculation_path.stat().st_size, "mtime_ns": calculation_path.stat().st_mtime_ns}
        if destination.exists() and manifest.exists():
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if payload.get("source") == source and payload.get("config_hash") == self.config.definition_hash:
                return destination
            raise RuntimeError(f"Incompatible local feature panel already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{grid}.{uuid4().hex}.building"
        source_sql = calculation_path.as_posix().replace("'", "''")
        temporary_sql = temporary.as_posix().replace("'", "''")
        temp_directory = Path(self.config.compute.duckdb_temp_directory)
        temp_directory.mkdir(parents=True, exist_ok=True)
        with duckdb.connect() as connection:
            connection.execute(f"SET threads={workers}")
            from .resources import calibrated_resources
            _,memory_limit,_=calibrated_resources(self.config.compute)
            connection.execute(f"SET memory_limit='{memory_limit}'")
            connection.execute(f"SET temp_directory='{temp_directory.as_posix().replace(chr(39), chr(39)*2)}'")
            connection.execute(
                f"COPY (SELECT * FROM read_parquet('{source_sql}')) TO '{temporary_sql}' "
                "(FORMAT PARQUET,PARTITION_BY (security_id),COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)"
            )
        temporary.replace(destination)
        self._atomic_json(f"cache/local_feature_panels/{grid}.json", {
            "grid": grid, "source": source, "config_hash": self.config.definition_hash,
            "partition_key": "security_id", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return destination

    def _stage_build_targets(self) -> dict:
        from .targets.builder import build_daily_targets, build_intraday_targets, build_overnight_targets, flag_corporate_action_crossings
        self._require("build-panel")
        if not (self.root / "snapshot" / "bars_1m_raw.parquet").exists():
            return self._build_targets_out_of_core()
        raw = pd.read_parquet(self.root / "snapshot" / "bars_1m_raw.parquet")
        actions = pd.read_parquet(self.root / "snapshot" / "corporate_actions.parquet")
        output = self.root / "cache" / "targets"; output.mkdir(parents=True, exist_ok=True)
        rows = 0; target_ids: set[str] = set()
        for grid, enabled in self.config.decision_grids.items():
            if not enabled: continue
            panel = pd.read_parquet(self.root / "cache" / "panels" / f"{grid}.parquet")
            if grid.startswith("intraday"):
                table = build_intraday_targets(panel, raw, tuple(int(x[:-1]) for x in self.config.targets["intraday"] if str(x).endswith("m")), "EOD" in self.config.targets["intraday"])
            elif grid == "daily_close":
                table = build_daily_targets(panel, raw, tuple(int(x[:-1]) for x in self.config.targets["interday"]), int(self.config.targets["daily_entry_delay_minutes"]))
            else:
                table = build_overnight_targets(panel, raw)
            if not table.empty:
                table = flag_corporate_action_crossings(table, actions)
                annotations = panel[[column for column in ("observation_id", "symbol", "beta_prior") if column in panel]].drop_duplicates("observation_id")
                table = table.merge(annotations, on="observation_id", how="left", validate="many_to_one")
                benchmark_symbol = self.config.source.benchmark_symbols[0]
                benchmark_key = "decision_ts" if grid.startswith("intraday") else "session_date"
                benchmark = table[table.symbol.eq(benchmark_symbol)][[benchmark_key, "target_id", "target"]].rename(columns={"target": "benchmark_target"})
                benchmark = benchmark.drop_duplicates([benchmark_key, "target_id"])
                enriched = table.merge(benchmark, on=[benchmark_key, "target_id"], how="left", validate="many_to_one")
                bases = [enriched]
                if "benchmark_adjusted" in self.config.targets["bases"]:
                    adjusted = enriched.copy(); adjusted["target"] = adjusted.target - adjusted.benchmark_target
                    adjusted["target_basis"] = "benchmark_adjusted"; adjusted["target_id"] = adjusted.target_id.str.replace("__raw__", "__benchmark_adjusted__", regex=False); bases.append(adjusted)
                if "beta_residual" in self.config.targets["bases"]:
                    residual = enriched.copy(); beta = residual.get("beta_prior", pd.Series(1.0, index=residual.index)).fillna(1.0)
                    residual["target"] = residual.target - beta * residual.benchmark_target
                    residual["target_basis"] = "beta_residual"; residual["target_id"] = residual.target_id.str.replace("__raw__", "__beta_residual__", regex=False); bases.append(residual)
                table = pd.concat(bases, ignore_index=True).drop(columns=["benchmark_target"], errors="ignore")
            table.to_parquet(output / f"{grid}.parquet", index=False); rows += len(table); target_ids.update(table.get("target_id", []))
        return {"target_rows": rows, "target_ids": len(target_ids)}

    def _build_targets_out_of_core(self) -> dict:
        """Build the large target ledger in DuckDB without materializing source bars."""
        import duckdb
        source = self.config.source
        output = self.root / "cache" / "targets"; output.mkdir(parents=True, exist_ok=True)
        from .resources import calibrated_resources
        workers,memory_limit,_=calibrated_resources(self.config.compute); workers=min(workers,self.runtime_worker_cap) if self.runtime_worker_cap else workers
        total_rows = 0; target_ids: set[str] = set(); benchmark_symbol = source.benchmark_symbols[0]
        temp_directory = Path(self.config.compute.duckdb_temp_directory)
        temp_directory.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(source.duckdb_path, read_only=True) as connection:
            connection.execute(f"SET threads={workers}")
            connection.execute(f"SET memory_limit='{memory_limit}'")
            connection.execute(f"SET temp_directory='{temp_directory.as_posix().replace(chr(39), chr(39)*2)}'")
            snapshot_start=self._snapshot_start()
            connection.execute(f"""CREATE TEMP TABLE source_sessions AS
                SELECT session_date,row_number() OVER(ORDER BY session_date) sn
                FROM (SELECT DISTINCT session_date FROM {source.bars_1m_raw_table}
                      WHERE session_date BETWEEN DATE '{snapshot_start}' AND DATE '{self.config.research_periods.discovery_end}')""")
            for grid, enabled in self.config.decision_grids.items():
                if not enabled: continue
                panel = (self.root / "cache" / "panels" / f"{grid}.parquet").as_posix().replace("'", "''")
                destination = (output / f"{grid}.parquet").as_posix().replace("'", "''")
                beta_window = 1560 if grid == "intraday_5m" else 7800 if grid == "intraday_1m" else 63
                beta_minimum = 780 if grid == "intraday_5m" else 3900 if grid == "intraday_1m" else 40
                raw_table = f"(SELECT * FROM {source.bars_1m_raw_table} WHERE session_date BETWEEN DATE '{snapshot_start}' AND DATE '{self.config.research_periods.discovery_end}' AND strftime(timezone('America/New_York',bar_start_ts_utc),'%H:%M')>='09:30' AND strftime(timezone('America/New_York',bar_start_ts_utc),'%H:%M')<'16:00')"
                decisions = f"""
                  decisions0 AS (SELECT * FROM read_parquet('{panel}')),
                  decisions AS (SELECT *,CASE WHEN count(benchmark_bucket_return) OVER(PARTITION BY security_id ORDER BY decision_ts ROWS BETWEEN {beta_window} PRECEDING AND 1 PRECEDING)>={beta_minimum}
                    THEN covar_samp(bucket_return,benchmark_bucket_return) OVER(PARTITION BY security_id ORDER BY decision_ts ROWS BETWEEN {beta_window} PRECEDING AND 1 PRECEDING)
                    /nullif(var_samp(benchmark_bucket_return) OVER(PARTITION BY security_id ORDER BY decision_ts ROWS BETWEEN {beta_window} PRECEDING AND 1 PRECEDING),0) END AS beta_prior FROM decisions0)
                """
                if grid.startswith("intraday"):
                    horizons = [int(x[:-1]) for x in self.config.targets["intraday"] if str(x).endswith("m")]
                    values = ",".join(f"({h})" for h in horizons)
                    eod_union = "" if "EOD" not in self.config.targets["intraday"] else """
                      UNION ALL SELECT d.observation_id,d.security_id,d.symbol,d.session_date,d.decision_ts,d.beta_prior,e.bar_start_ts_utc,e.open,
                        'eod' AS target_label,z.bar_end_ts_utc,z.exit_close,z.exit_close/e.open-1 AS target
                      FROM decisions d JOIN bars e ON e.security_id=d.security_id AND e.session_date=d.session_date AND e.bar_start_ts_utc=d.decision_ts+INTERVAL 1 MINUTE
                      JOIN session_end z ON z.security_id=d.security_id AND z.session_date=d.session_date
                    """
                    raw_query = f"""
                      WITH {decisions}, bars AS (SELECT *,row_number() OVER(PARTITION BY security_id,session_date ORDER BY bar_start_ts_utc) rn FROM {raw_table}),
                      session_end AS (SELECT security_id,session_date,last(bar_end_ts_utc ORDER BY bar_start_ts_utc) AS bar_end_ts_utc,last(close ORDER BY bar_start_ts_utc) AS exit_close FROM bars GROUP BY security_id,session_date),
                      raw_targets AS (
                        SELECT d.observation_id,d.security_id,d.symbol,d.session_date,d.decision_ts,d.beta_prior,e.bar_start_ts_utc,e.open,
                          cast(h.h AS VARCHAR)||'m' AS target_label,z.bar_end_ts_utc,z.close,z.close/e.open-1 AS target
                        FROM decisions d JOIN bars e ON e.security_id=d.security_id AND e.session_date=d.session_date AND e.bar_start_ts_utc=d.decision_ts+INTERVAL 1 MINUTE
                        CROSS JOIN (VALUES {values}) h(h) JOIN bars z ON z.security_id=e.security_id AND z.session_date=e.session_date AND z.rn=e.rn+h.h-1
                        {eod_union}
                      )
                    """
                elif grid == "daily_close":
                    values = ",".join(f"({int(x[:-1])})" for x in self.config.targets["interday"])
                    entry_clock=(pd.Timestamp("2000-01-01 09:30")+pd.Timedelta(minutes=int(self.config.targets["daily_entry_delay_minutes"]))).strftime("%H:%M")
                    raw_query = f"""
                      WITH {decisions}, sessions AS (SELECT * FROM source_sessions),
                      bars AS (SELECT * FROM {raw_table}),
                      session_schedule AS (SELECT session_date,max(bar_end_ts_utc) canonical_close_ts FROM bars WHERE symbol='{benchmark_symbol}' GROUP BY session_date),
                      raw_targets AS (SELECT d.observation_id,d.security_id,d.symbol,d.session_date,d.decision_ts,d.beta_prior,e.bar_start_ts_utc,e.open,
                        cast(h.h AS VARCHAR)||'d' AS target_label,z.bar_end_ts_utc,z.close,z.close/e.open-1 AS target
                        FROM decisions d JOIN sessions s ON s.session_date=d.session_date CROSS JOIN (VALUES {values}) h(h)
                        JOIN sessions se ON se.sn=s.sn+1 JOIN bars e ON e.security_id=d.security_id AND e.session_date=se.session_date AND strftime(timezone('America/New_York',e.bar_start_ts_utc),'%H:%M')='{entry_clock}'
                        JOIN sessions sx ON sx.sn=s.sn+h.h JOIN session_schedule ss ON ss.session_date=sx.session_date
                        JOIN bars z ON z.security_id=d.security_id AND z.session_date=sx.session_date AND z.bar_end_ts_utc=ss.canonical_close_ts)
                    """
                else:
                    raw_query = f"""
                      WITH {decisions}, sessions AS (SELECT * FROM source_sessions),
                      bars AS (SELECT * FROM {raw_table}),
                      raw_targets AS (SELECT d.observation_id,d.security_id,d.symbol,d.session_date,d.decision_ts,d.beta_prior,e.bar_start_ts_utc,e.open,
                        'overnight' AS target_label,z.bar_start_ts_utc AS bar_end_ts_utc,z.open AS close,z.open/e.open-1 AS target
                        FROM decisions d JOIN sessions s ON s.session_date=d.session_date JOIN bars e ON e.security_id=d.security_id AND e.session_date=d.session_date AND e.bar_start_ts_utc=d.decision_ts+INTERVAL 1 MINUTE
                        JOIN sessions sx ON sx.sn=s.sn+1 JOIN bars z ON z.security_id=d.security_id AND z.session_date=sx.session_date AND strftime(timezone('America/New_York',z.bar_start_ts_utc),'%H:%M')='09:31')
                    """
                bases = ["raw"] + (["benchmark_adjusted"] if "benchmark_adjusted" in self.config.targets["bases"] else []) + (["beta_residual"] if "beta_residual" in self.config.targets["bases"] else [])
                basis_values = ",".join(f"('{basis}')" for basis in bases)
                actions_path = Path(source.corporate_actions_path).as_posix().replace("'", "''")
                split_cross = f"EXISTS(SELECT 1 FROM read_parquet('{actions_path}') a WHERE a.security_id=enriched.security_id AND a.session_date>CAST(enriched.bar_start_ts_utc AS DATE) AND a.session_date<=CAST(enriched.bar_end_ts_utc AS DATE) AND lower(a.action_type) LIKE '%split%')"
                cash_cross = f"EXISTS(SELECT 1 FROM read_parquet('{actions_path}') a WHERE a.security_id=enriched.security_id AND a.session_date>CAST(enriched.bar_start_ts_utc AS DATE) AND a.session_date<=CAST(enriched.bar_end_ts_utc AS DATE) AND (lower(a.action_type) LIKE '%cash%' OR lower(a.action_type) LIKE '%dividend%'))"
                benchmark_key = "decision_ts" if grid.startswith("intraday") else "session_date"
                query = raw_query + f"""
                  , benchmark AS (SELECT {benchmark_key},target_label,target AS benchmark_target FROM raw_targets WHERE symbol='{benchmark_symbol}'),
                  enriched AS (SELECT r.*,b.benchmark_target FROM raw_targets r LEFT JOIN benchmark b USING({benchmark_key},target_label))
                  SELECT observation_id,security_id,session_date,decision_ts,bar_start_ts_utc entry_ts,open entry_price,bar_end_ts_utc exit_ts,close exit_price,
                    CASE WHEN {split_cross} OR {cash_cross} THEN NULL ELSE CASE basis WHEN 'raw' THEN target WHEN 'benchmark_adjusted' THEN target-benchmark_target ELSE target-beta_prior*benchmark_target END END AS "target",
                    basis AS target_basis,'target_'||target_label||'__'||basis||'__{grid}' AS target_id,beta_prior,
                    {split_cross} AS crosses_split,{cash_cross} AS crosses_cash_dividend
                  FROM enriched CROSS JOIN (VALUES {basis_values}) q(basis)
                  WHERE basis='raw' OR benchmark_target IS NOT NULL AND (basis<>'beta_residual' OR beta_prior IS NOT NULL)
                """
                connection.execute(f"COPY ({query}) TO '{destination}' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 250000)")
                count, ids = connection.execute(f"SELECT count(*),list(DISTINCT target_id) FROM read_parquet('{destination}')").fetchone()
                total_rows += int(count); target_ids.update(ids or [])
                self._useful_progress(f"targets:{grid}",total_rows,total_rows)
        return {"target_rows": total_rows, "target_ids": len(target_ids), "mode": "duckdb_out_of_core", "cpu_workers": workers}

    def _target_ids_and_vector(self, grid: str, observations: pd.DataFrame, target_id: str | None = None):
        """Read aligned target columns from the canonical memory-mapped store."""
        from .cache.target_store import TargetStore
        store = TargetStore(self.root / "cache" / "target_store" / grid)
        matrix_path = store.root / "aligned.npy"
        if not matrix_path.exists():
            self._build_aligned_target_store(grid, observations, store)
        matrix, columns = store.read("aligned")
        if target_id is None: return columns
        try: index = columns.index(target_id)
        except ValueError as error: raise KeyError(f"Unknown target: {target_id}") from error
        return matrix[:, index]

    def _target_matrix(self, grid: str, observations: pd.DataFrame):
        from .cache.target_store import TargetStore
        store = TargetStore(self.root / "cache" / "target_store" / grid)
        if not (store.root / "aligned.npy").exists(): self._build_aligned_target_store(grid, observations, store)
        return store.read("aligned")

    def _build_aligned_target_store(self, grid: str, observations: pd.DataFrame, store) -> None:
        """Create the target matrix one column at a time from the auditable long ledger."""
        import duckdb
        ledger = self.root / "cache" / "targets" / f"{grid}.parquet"
        path = ledger.as_posix().replace("'", "''")
        ids = observations.observation_id.to_numpy(np.int64)
        with duckdb.connect() as connection:
            connection.register("observation_order", pd.DataFrame({"position": np.arange(len(ids)), "observation_id": ids}))
            columns = [row[0] for row in connection.execute(f"SELECT DISTINCT target_id FROM read_parquet('{path}') ORDER BY target_id").fetchall()]
            duplicate=connection.execute(f"""SELECT 1 FROM read_parquet('{path}') t JOIN observation_order o USING(observation_id)
                GROUP BY t.observation_id,t.target_id HAVING count(*)>1 LIMIT 1""").fetchone()
            if duplicate: raise ValueError("Target ledger contains duplicate observation_id/target_id rows")
            def loader(batch):
                connection.register("target_batch",pd.DataFrame({"target_index":np.arange(len(batch),dtype=np.int32),"target_id":batch}))
                frame=connection.execute(f"""SELECT o.position,b.target_index,t.target
                    FROM observation_order o CROSS JOIN target_batch b
                    LEFT JOIN read_parquet('{path}') t ON t.observation_id=o.observation_id AND t.target_id=b.target_id
                    ORDER BY o.position,b.target_index""").fetchdf()
                return frame.target.to_numpy(dtype=np.float32,na_value=np.nan).reshape(len(ids),len(batch))
            configured=self.config.compute.target_block_size
            batch_size=8 if configured=="auto" else int(configured)
            store.build_batches("aligned",ids,columns,loader,ledger,batch_size)

    def _stage_scan_singles(self) -> dict:
        from .cache.bin_store import PackedBinStore
        from .cache.feature_store import ArrayStore
        from .cache.rank_store import build_packed_bins
        from .scan.singles import scan_singles, single_backend
        self._require("build-features"); self._require("build-targets")
        chunks = 0; tests = 0
        for grid, enabled in self.config.decision_grids.items():
            if not enabled: continue
            observations = pd.read_parquet(self.root / "cache" / "features" / grid / "observations.parquet")
            clusters = pd.factorize(observations.session_date, sort=True)[0]
            target_matrix, target_ids = self._target_matrix(grid, observations)
            if not target_ids: continue
            target_vectors={target_id:target_matrix[:,index] for index,target_id in enumerate(target_ids)}
            feature_store=ArrayStore(self.root/"cache"/"features"/grid)
            packed_store=PackedBinStore(self.root/"cache"/"bins"/"packed"/grid)
            decision_codes=pd.factorize(observations.decision_ts,sort=True)[0]
            stems=sorted({path.stem for path in feature_store.root.glob("*.json")} | {path.stem for path in packed_store.root.glob("*.json")})
            destination = self.root / "single_results" / grid; destination.mkdir(parents=True, exist_ok=True)
            for stem in stems:
                result_path=destination/f"{stem}.parquet"
                try: packed,packed_columns=packed_store.read(stem)
                except (FileNotFoundError,ValueError,KeyError): packed=None; packed_columns=None
                if result_path.exists() and packed is not None:
                    prior=pd.read_parquet(result_path,columns=["fold_id"]); chunks+=1; tests+=int(prior.fold_id.eq("all").sum()); continue
                try: values, feature_ids = feature_store.read(stem)
                except (FileNotFoundError,ValueError,KeyError) as error:
                    raise RuntimeError(f"Single scan cannot resume incomplete block {grid}/{stem} without raw features") from error
                result=scan_singles(np.asarray(values),target_matrix,feature_ids,target_ids,clusters,observations.decision_ts,
                                    prefer_cuda=self.config.compute.prefer_cuda, device_name=self.config.compute.gpu_device)
                result["fold_id"] = "all"
                sessions = pd.to_datetime(observations.session_date)
                fold_rows = []
                for fold_id, dates in enumerate(np.array_split(np.sort(sessions.unique()), int(self.config.stability["chronological_folds"]))):
                    mask = sessions.isin(dates).to_numpy()
                    if mask.sum() < 3: continue
                    fold=scan_singles(np.asarray(values)[mask],target_matrix[mask],feature_ids,target_ids,clusters[mask],observations.decision_ts.to_numpy()[mask],
                                      prefer_cuda=self.config.compute.prefer_cuda, device_name=self.config.compute.gpu_device)
                    fold["fold_id"] = str(fold_id); fold_rows.append(fold)
                if fold_rows:
                    result = pd.concat([result, *fold_rows], ignore_index=True)
                if packed is None:
                    packed=build_packed_bins(np.asarray(values),decision_codes); packed_store.write(stem,packed,feature_ids)
                elif packed_columns!=feature_ids: raise ValueError(f"Packed feature columns disagree for {grid}/{stem}")
                temporary=result_path.with_suffix(".tmp.parquet"); result.to_parquet(temporary,index=False); temporary.replace(result_path)
                del values,packed
                if "__global__" not in stem:
                    (feature_store.root/f"{stem}.npy").unlink(missing_ok=True); (feature_store.root/f"{stem}.json").unlink(missing_ok=True)
                chunks += 1; tests += int(result.fold_id.eq("all").sum())
        return {"result_chunks": chunks, "attempted_single_tests": tests,
                "backend": single_backend(self.config.compute.prefer_cuda, self.config.compute.gpu_device)}

    def _ensure_bin_cache(self, grid: str, observations: pd.DataFrame) -> tuple[dict[str, tuple[str, int]], dict[str, str]]:
        from .cache.bin_store import PackedBinStore
        from hashlib import sha256
        if {int(self.config.duals["coarse_bins"]), 5, int(self.config.duals["exact_bins"])} != {3, 5, 10}:
            raise ValueError("Packed rank cache requires the governed 3/5/10 resolutions")
        feature_bins: dict[str, tuple[str, int]] = {}; alias_hashes = {}
        store = PackedBinStore(self.root / "cache" / "bins" / "packed" / grid)
        metadata_files=sorted(store.root.glob("*.json"))
        if not metadata_files: raise RuntimeError(f"Packed bin cache is missing for {grid}; scan-singles must complete first")
        for metadata in metadata_files:
            packed, feature_ids = store.read(metadata.stem)
            path = str(store.root / f"{metadata.stem}.npy")
            feature_bins.update({name: (path, index) for index, name in enumerate(feature_ids)})
            for index, name in enumerate(feature_ids):
                alias_hashes[name] = sha256(np.ascontiguousarray(packed[:, index]).tobytes()).hexdigest()
        alias_path = self.root / "cache" / "bins" / grid / "aliases.json"; alias_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_json(str(alias_path.relative_to(self.root)), {"realized_hashes": alias_hashes})
        return feature_bins, alias_hashes

    def _dual_scan(self, bins: int, stage_name: str) -> dict:
        from .scan.pair_plan import PairPlan
        from .scan.dual_coarse import DualTileScanner
        started=time.perf_counter(); self._require("build-features"); self._require("build-targets"); bundle = self.compile_registry()
        eligibility = EligibilityMatrix.build(bundle.features, bundle.targets)
        attempted = 0; excluded = 0; chunks = 0; backend = None
        output_root = self.root / ("dual_coarse_results" if bins == 3 else "dual_fine_results" if bins == 5 else "dual_exact_results")
        ledger_root = self.root / "dual_trial_ledger" / stage_name; ledger_root.mkdir(parents=True, exist_ok=True)
        for grid, enabled in self.config.decision_grids.items():
            if not enabled: continue
            observations = pd.read_parquet(self.root / "cache" / "features" / grid / "observations.parquet")
            cluster_codes = pd.factorize(observations.session_date, sort=True)[0].astype(np.int32)
            ordered_sessions = np.sort(pd.unique(pd.to_datetime(observations.session_date)))
            fold_lookup = {session: fold for fold, group in enumerate(np.array_split(ordered_sessions, int(self.config.stability["chronological_folds"]))) for session in group}
            fold_codes = pd.to_datetime(observations.session_date).map(fold_lookup).to_numpy(np.int16)
            feature_bins, alias_hashes = self._ensure_bin_cache(grid, observations)
            target_matrix, target_ids = self._target_matrix(grid, observations)
            all_specs = [item for item in bundle.features if item.decision_grid == grid and item.feature_id in feature_bins]
            specs, structural_aliases = _dual_parent_scope(all_specs, self.config.duals)
            plan = PairPlan.compile([item.feature_id for item in specs], alias_hashes)
            plan.write(self.root / "cache" / "pair_plans" / f"{grid}.npz")
            scanner = DualTileScanner(bins=bins, device_name=self.config.compute.gpu_device,
                                      prefer_cuda=self.config.compute.prefer_cuda, memory_fraction=self.config.compute.dynamic_memory_fraction)
            backend = scanner.backend
            block = scanner.recommended_shape(len(observations), targets=max(1, len(target_ids)))[1]
            exclusions = [{"pair_id": None, "feature_a": alias, "feature_b": canonical,
                           "target_id": None, "eligible": False, "reason": "noncanonical_concept_variant"}
                          for alias, canonical in structural_aliases.items()] + [{"pair_id": None, "feature_a": alias, "feature_b": canonical,
                           "target_id": None, "eligible": False, "reason": "realized_exact_alias"}
                          for alias, canonical in plan.alias_of.items()]
            full_pairs=len(all_specs)*(len(all_specs)-1)//2; canonical_pairs=len(specs)*(len(specs)-1)//2
            excluded += ((full_pairs-canonical_pairs)+(canonical_pairs-len(plan.left)))*len(target_ids)
            batch=[]; part=0
            for index, (left_index, right_index) in enumerate(zip(plan.left, plan.right)):
                left, right = plan.feature_ids[left_index], plan.feature_ids[right_index]
                batch.append((plan.pair_ids[index], left, right))
                if len(batch) < block: continue
                chunks += self._write_dual_tile_multi(scanner, batch, feature_bins, target_matrix, output_root / grid,
                                                       part, cluster_codes, fold_codes, target_ids)
                attempted += len(batch) * len(target_ids); part += 1; batch=[]
            if batch:
                chunks += self._write_dual_tile_multi(scanner, batch, feature_bins, target_matrix, output_root / grid,
                                                       part, cluster_codes, fold_codes, target_ids)
                attempted += len(batch) * len(target_ids)
            pd.DataFrame(exclusions, columns=["pair_id", "feature_a", "feature_b", "target_id", "eligible", "reason"]).to_parquet(ledger_root / f"{grid}_exclusions.parquet", index=False)
        elapsed=time.perf_counter()-started
        peak=None
        try:
            import torch
            if backend and "cuda" in backend: peak=int(torch.cuda.max_memory_allocated(self.config.compute.gpu_device))
        except Exception: pass
        return {"bins":bins,"backend":backend,"attempted_pair_target_tests":attempted,"excluded_pair_target_tests":excluded,
                "result_chunks":chunks,"wall_seconds":elapsed,"tests_per_second":attempted/max(elapsed,1e-9),"gpu_peak_allocated_bytes":peak}

    def _dual_scan_fused(self) -> dict:
        from .scan.pair_plan import PairPlan
        from .scan.dual_coarse import DualTileScanner
        started=time.perf_counter(); self._require("build-features"); self._require("build-targets")
        bundle=self.compile_registry(); resolutions=tuple(self.config.duals.get("resolutions",(3,5,10))); attempted=excluded=chunks=0; backend=None
        output_roots={r:self.root/{3:"dual_coarse_results",5:"dual_fine_results",10:"dual_exact_results"}[r] for r in resolutions}
        for grid,enabled in self.config.decision_grids.items():
            if not enabled: continue
            observations=pd.read_parquet(self.root/"cache"/"features"/grid/"observations.parquet")
            cluster_codes=pd.factorize(observations.session_date,sort=True)[0].astype(np.int32)
            sessions=np.sort(pd.unique(pd.to_datetime(observations.session_date)))
            fold_lookup={session:fold for fold,group in enumerate(np.array_split(sessions,int(self.config.stability["chronological_folds"]))) for session in group}
            fold_codes=pd.to_datetime(observations.session_date).map(fold_lookup).to_numpy(np.int16)
            feature_bins,alias_hashes=self._ensure_bin_cache(grid,observations); target_matrix,target_ids=self._target_matrix(grid,observations)
            all_specs=[item for item in bundle.features if item.decision_grid==grid and item.feature_id in feature_bins]
            specs,structural_aliases=_dual_parent_scope(all_specs,self.config.duals)
            if self.config.duals.get("parent_filter")=="single_survivors":
                specs=_single_survivor_scope(specs,self.root/"single_results"/grid,self.config.duals)
            plan=PairPlan.compile([item.feature_id for item in specs],alias_hashes); plan.write(self.root/"cache"/"pair_plans"/f"{grid}.npz")
            scanner=DualTileScanner(bins=10,device_name=self.config.compute.gpu_device,prefer_cuda=self.config.compute.prefer_cuda,
                                    memory_fraction=self.config.compute.dynamic_memory_fraction)
            backend=scanner.backend; maximum_pairs=self.runtime_pair_cap or 8192; block=scanner.recommended_shape(len(observations),targets=max(1,len(target_ids)),maximum_pairs=maximum_pairs)[1]
            full_pairs=len(all_specs)*(len(all_specs)-1)//2; canonical_pairs=len(specs)*(len(specs)-1)//2
            excluded+=((full_pairs-canonical_pairs)+(canonical_pairs-len(plan.left)))*len(target_ids)
            exclusions=[{"pair_id":None,"feature_a":alias,"feature_b":canonical,"target_id":None,"eligible":False,"reason":"noncanonical_concept_variant"} for alias,canonical in structural_aliases.items()]
            exclusions += [{"pair_id":None,"feature_a":alias,"feature_b":canonical,"target_id":None,"eligible":False,"reason":"realized_exact_alias"} for alias,canonical in plan.alias_of.items()]
            for stage_name in ("coarse","fine","exact"):
                ledger=self.root/"dual_trial_ledger"/stage_name; ledger.mkdir(parents=True,exist_ok=True)
                pd.DataFrame(exclusions,columns=["pair_id","feature_a","feature_b","target_id","eligible","reason"]).to_parquet(ledger/f"{grid}_exclusions.parquet",index=False)
            batch=[]; part=0
            for index,(left_index,right_index) in enumerate(zip(plan.left,plan.right)):
                batch.append((plan.pair_ids[index],plan.feature_ids[left_index],plan.feature_ids[right_index]))
                if len(batch)<block: continue
                chunks+=self._write_fused_dual_tile(scanner,batch,feature_bins,target_matrix,output_roots,grid,part,cluster_codes,fold_codes,target_ids)
                attempted+=len(batch)*len(target_ids); part+=1; self._useful_progress(f"duals:{grid}",attempted,len(plan.left)*len(target_ids)); batch=[]
            if batch:
                chunks+=self._write_fused_dual_tile(scanner,batch,feature_bins,target_matrix,output_roots,grid,part,cluster_codes,fold_codes,target_ids)
                attempted+=len(batch)*len(target_ids)
                self._useful_progress(f"duals:{grid}",attempted,len(plan.left)*len(target_ids))
        elapsed=time.perf_counter()-started
        manifest={"config_hash":self.config.definition_hash,"implementation_hash":self.implementation_hash,"resolutions":list(resolutions),
                  "search_scope":self.config.duals.get("search_scope","canonical_concepts"),
                  "attempted_pair_target_tests_per_resolution":attempted,"excluded_pair_target_tests_per_resolution":excluded,
                  "wall_seconds":elapsed,"backend":backend}
        self._atomic_json("cache/fused_dual_scan.json",manifest)
        return {"bins":3,"fused_resolutions":list(resolutions),"backend":backend,"attempted_pair_target_tests":attempted,
                "excluded_pair_target_tests":excluded,"result_chunks":chunks,"wall_seconds":elapsed,
                "pair_targets_per_second":attempted/max(elapsed,1e-9),
                "resolution_tests_per_second":attempted*len(resolutions)/max(elapsed,1e-9)}

    @staticmethod
    def _write_fused_dual_tile(scanner,batch,feature_bins,targets,output_roots,grid,part,cluster_codes,fold_codes,target_ids) -> int:
        destinations={(resolution,target_index):output_roots[resolution]/grid/target_id/f"part-{part:08d}.parquet"
                      for resolution in output_roots for target_index,target_id in enumerate(target_ids)}
        if all(path.exists() for path in destinations.values()): return 0
        arrays={}; unique=list(dict.fromkeys([value for _,left,right in batch for value in (left,right)])); lookup={name:index for index,name in enumerate(unique)}
        left_index=np.asarray([lookup[left] for _,left,_ in batch]); right_index=np.asarray([lookup[right] for _,_,right in batch])
        def reader(start,end):
            matrix=np.empty((end-start,len(unique)),dtype=np.uint8)
            for out_index,name in enumerate(unique):
                path,index=feature_bins[name]
                if path not in arrays: arrays[path]=np.load(path,mmap_mode="r",allow_pickle=False)
                matrix[:,out_index]=arrays[path][start:end,index]
            return matrix,left_index,right_index,targets[start:end]
        results=scanner.scan_packed_resolutions(len(targets),len(batch),reader,resolutions=tuple(output_roots),target_count=len(target_ids),cluster_codes=cluster_codes,fold_codes=fold_codes)
        written=0
        for resolution,result in results.items():
            pair_index=result.pair_index.to_numpy(int); result.insert(0,"pair_id",[batch[index][0] for index in pair_index])
            result.insert(1,"feature_a",[batch[index][1] for index in pair_index]); result.insert(2,"feature_b",[batch[index][2] for index in pair_index]); result["resolution"]=resolution
            for target_index,target_id in enumerate(target_ids):
                destination=destinations[(resolution,target_index)]
                if destination.exists(): continue
                table=result[result.target_index.eq(target_index)].drop(columns="target_index").copy(); table["target_id"]=target_id
                destination.parent.mkdir(parents=True,exist_ok=True); temporary=destination.with_suffix(".tmp.parquet")
                table.to_parquet(temporary,index=False); temporary.replace(destination); written+=1
        return written

    @staticmethod
    def _write_dual_tile(scanner, batch: list[tuple], feature_bins: dict[str, tuple[str, int]], target: np.ndarray, output: Path, part: int, cluster_codes: np.ndarray, fold_codes: np.ndarray, target_id: str) -> int:
        destination = output / f"part-{part:08d}.parquet"
        if destination.exists(): return 0
        arrays: dict[str, np.memmap] = {}; unique = list(dict.fromkeys([x for _, a, b in batch for x in (a, b)])); lookup={name:i for i,name in enumerate(unique)}
        left_index=np.asarray([lookup[left] for _,left,_ in batch]); right_index=np.asarray([lookup[right] for _,_,right in batch])
        def reader(start, end):
            from .cache.rank_store import unpack_bins
            matrix=np.empty((end-start,len(unique)),dtype=np.int8)
            for out_index,name in enumerate(unique):
                path,index=feature_bins[name]
                if path not in arrays: arrays[path]=np.load(path,mmap_mode="r",allow_pickle=False)
                matrix[:,out_index]=unpack_bins(arrays[path][start:end,index],scanner.bins)
            return matrix[:,left_index],matrix[:,right_index],target[start:end],None,None
        result = scanner.scan_reader(len(target), len(batch), reader, cluster_codes=cluster_codes, fold_codes=fold_codes)
        result["resolution"] = scanner.bins
        result["target_id"] = target_id
        result.insert(0, "pair_id", [item[0] for item in batch]); result.insert(1, "feature_a", [item[1] for item in batch]); result.insert(2, "feature_b", [item[2] for item in batch])
        output.mkdir(parents=True, exist_ok=True); temporary = destination.with_suffix(".tmp.parquet"); result.to_parquet(temporary, index=False); temporary.replace(destination)
        return 1

    @staticmethod
    def _write_dual_tile_multi(scanner, batch: list[tuple], feature_bins: dict[str, tuple[str, int]],
                               targets: np.ndarray, output: Path, part: int, cluster_codes: np.ndarray,
                               fold_codes: np.ndarray, target_ids: list[str]) -> int:
        destinations = [output / target_id / f"part-{part:08d}.parquet" for target_id in target_ids]
        missing = [index for index, destination in enumerate(destinations) if not destination.exists()]
        if not missing: return 0
        selected_targets = targets if missing == list(range(len(target_ids))) else targets[:, missing]
        selected_ids = [target_ids[index] for index in missing]
        arrays: dict[str, np.memmap] = {}
        unique = list(dict.fromkeys([value for _, left, right in batch for value in (left, right)]))
        lookup = {name: index for index, name in enumerate(unique)}
        left_index = np.asarray([lookup[left] for _, left, _ in batch])
        right_index = np.asarray([lookup[right] for _, _, right in batch])
        def reader(start, end):
            from .cache.rank_store import unpack_bins
            matrix = np.empty((end - start, len(unique)), dtype=np.int8)
            for out_index, name in enumerate(unique):
                path, index = feature_bins[name]
                if path not in arrays: arrays[path] = np.load(path, mmap_mode="r", allow_pickle=False)
                matrix[:, out_index] = unpack_bins(arrays[path][start:end, index], scanner.bins)
            return matrix[:, left_index], matrix[:, right_index], selected_targets[start:end], None, None
        result = scanner.scan_reader(len(targets), len(batch), reader, cluster_codes=cluster_codes,
                                     fold_codes=fold_codes, target_count=len(selected_ids))
        pair_index = result.pair_index.to_numpy(int)
        result.insert(0, "pair_id", [batch[index][0] for index in pair_index])
        result.insert(1, "feature_a", [batch[index][1] for index in pair_index])
        result.insert(2, "feature_b", [batch[index][2] for index in pair_index])
        result["resolution"] = scanner.bins
        written = 0
        for target_index, target_id in enumerate(selected_ids):
            target_result = result[result.target_index.eq(target_index)].drop(columns="target_index").copy()
            target_result["target_id"] = target_id
            destination = output / target_id / f"part-{part:08d}.parquet"; destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp.parquet"); target_result.to_parquet(temporary, index=False); temporary.replace(destination); written += 1
        return written

    def _stage_scan_duals_coarse(self) -> dict: return self._dual_scan_fused()
    def _fused_resolution_status(self,bins: int) -> dict:
        self._require("scan-duals-coarse"); manifest=json.loads((self.root/"cache"/"fused_dual_scan.json").read_text(encoding="utf-8"))
        if manifest.get("config_hash")!=self.config.definition_hash or manifest.get("implementation_hash")!=self.implementation_hash:
            raise RuntimeError("Fused dual scan manifest is incompatible")
        if bins not in manifest["resolutions"]: return {"bins":bins,"skipped":"outside_declared_resolution_scope"}
        tree="dual_fine_results" if bins==5 else "dual_exact_results"
        import pyarrow.parquet as pq
        completed=sum(pq.ParquetFile(path).metadata.num_rows for path in (self.root/tree).glob("**/part-*.parquet"))
        expected=int(manifest["attempted_pair_target_tests_per_resolution"])
        if completed!=expected: raise RuntimeError(f"Fused {bins}-bin output is incomplete: {completed:,}/{expected:,}")
        return {"bins":bins,"backend":manifest["backend"],"attempted_pair_target_tests":expected,"result_chunks":len(list((self.root/tree).glob("**/part-*.parquet"))),"fused_reuse":True}
    def _stage_scan_duals_fine(self) -> dict: return self._fused_resolution_status(5)
    def _stage_exact_duals(self) -> dict: return self._fused_resolution_status(10)

    def _stage_build_stability(self) -> dict:
        from .scan.stability import build_stability
        self._require("scan-singles"); self._require("scan-duals-coarse")
        return build_stability(self.root,self.config.stability,tuple(self.config.duals.get("resolutions",(3,5,10))))

    def _stable_rows(self, limit: int = 64) -> pd.DataFrame:
        path=self.root/"stability"/"candidate_stability.parquet"
        import duckdb
        with duckdb.connect() as connection:
            return connection.execute("""WITH eligible AS (
                SELECT *,regexp_extract(target_id,'__(intraday_1m|intraday_5m|daily_close|preclose_1555)$',1) target_grid
                FROM read_parquet(?) WHERE hard_gate_pass AND isfinite(stability_score)
                  AND (structure_type<>'dual' OR effect>0)
              ), ranked AS (
                SELECT *,row_number() OVER(PARTITION BY structure_type,target_grid ORDER BY stability_score DESC,feature_id,target_id) group_rank
                FROM eligible)
              SELECT * EXCLUDE(target_grid,group_rank) FROM ranked
              ORDER BY CASE WHEN group_rank=1 THEN 0 ELSE 1 END,stability_score DESC,feature_id,target_id LIMIT ?""",
              [str(path),int(limit)]).fetchdf()

    def _stage_expand_context(self) -> dict:
        from .interactions.context_expand import expand_contexts
        self._require("build-stability"); bundle = self.compile_registry(); stable = self._stable_rows()
        structures = [{"source_id": f"single:{row.feature_id}:{row.target_id}", "feature_ids": (row.feature_a,row.feature_b) if row.structure_type=="dual" else (row.feature_a,)} for row in stable.itertuples()]
        contexts = [item.feature_id for item in bundle.features if item.family in {"calendar", "market", "session"}]
        rows = expand_contexts(structures, contexts); destination = self.root / "context_expansion" / "registry.parquet"; destination.parent.mkdir(parents=True, exist_ok=True)
        context_table=pd.DataFrame(rows) if rows else pd.DataFrame(columns=["source_id","feature_ids","context_feature_id"])
        context_table.to_parquet(destination, index=False)
        # Variant-level duals are generated only around concept pairs that
        # passed the locked stability gates; they are never part of the broad
        # canonical search or counted as already confirmed evidence.
        feature_map={item.feature_id:item for item in bundle.features}; limit=int(self.config.context_expansion.get("variant_neighbors_per_side",3)); variants=[]
        for row in stable[stable.structure_type.eq("dual")].itertuples():
            parents=[feature_map[row.feature_a],feature_map[row.feature_b]]; neighborhoods=[]
            for parent in parents:
                candidates=[item for item in bundle.features if item.concept_id==parent.concept_id and item.decision_grid==parent.decision_grid]
                candidates=sorted(candidates,key=lambda item:(item.feature_id!=parent.feature_id,item.representation!="raw",abs(item.minimum_history-parent.minimum_history),item.feature_id))[:limit+1]
                neighborhoods.append(candidates)
            for left in neighborhoods[0]:
                for right in neighborhoods[1]:
                    if left.feature_id==parents[0].feature_id and right.feature_id==parents[1].feature_id: continue
                    a,b=sorted((left.feature_id,right.feature_id)); variants.append({"source_feature_a":row.feature_a,"source_feature_b":row.feature_b,"feature_a":a,"feature_b":b,"target_id":row.target_id,"selection_role":"requires_new_chronological_confirmation"})
        variant_table=pd.DataFrame(variants).drop_duplicates(["feature_a","feature_b","target_id"]) if variants else pd.DataFrame(columns=["source_feature_a","source_feature_b","feature_a","feature_b","target_id","selection_role"])
        variant_table.to_parquet(self.root/"context_expansion"/"variant_dual_registry.parquet",index=False)
        return {"generated_context_interactions": len(rows),"generated_gated_variant_duals":len(variant_table),"evaluated_expressions":0,"coverage_status":"GENERATED_ONLY"}

    def _stage_run_formula_factory(self) -> dict:
        from .interactions.formula_factory import FormulaFactory
        self._require("build-stability"); features = self._stable_rows()["feature_id"].drop_duplicates().head(64).tolist()
        factory = FormulaFactory(int(self.config.formula_factory["max_expression_depth"]), int(self.config.formula_factory["max_binary_operators"]))
        formulas = factory.generate(features); rows = [{"expression": item.expression, "expression_hash": item.expression_hash, "depth": item.depth, "binary_operators": item.binary_operators} for item in formulas]
        destination = self.root / "formula_factory" / "registry.parquet"; destination.parent.mkdir(parents=True, exist_ok=True)
        formula_table=pd.DataFrame(rows) if rows else pd.DataFrame(columns=["expression","expression_hash","depth","binary_operators"])
        formula_table.to_parquet(destination, index=False)
        return {"generated_formulas": len(rows),"evaluated_expressions":0,"coverage_status":"GENERATED_ONLY"}

    def _stage_run_ml(self) -> dict:
        from .ml.folds import purged_walk_forward_folds
        from .ml.models import fit_predict_models
        from .ml.selection import training_feature_selection
        self._require("build-features"); self._require("build-targets")
        # Unsupervised, deterministic pool and explicit target, never full-sample winners.
        bundle=self.compile_registry(); target_id=self.config.ml.get("target_id")
        if not target_id:
            return {"ml_predictions":0,"skipped":"set ml.target_id explicitly; no outcome-driven target choice"}
        target_spec=next((item for item in bundle.targets if item.target_id==target_id),None)
        if target_spec is None: raise ValueError("ML target is not in the registry")
        grid=target_spec.decision_grid
        specs,_=_initial_feature_scope([item for item in bundle.features if item.decision_grid==grid],self.config)
        requested=self.config.ml.get("feature_ids")
        feature_ids=requested or [item.feature_id for item in specs if not _alpha_feature_is_global(item)][:int(self.config.ml.get("pool_size",32))]
        observations,x=self._load_features(grid,feature_ids)
        target=pd.read_parquet(self.root/"cache"/"targets"/f"{grid}.parquet",filters=[("target_id","=",target_id)],columns=["observation_id","target","exit_ts"])
        aligned=observations.merge(target,on="observation_id",how="left",validate="one_to_one")
        valid=np.isfinite(aligned.target)&aligned.exit_ts.notna(); x=x[valid]; aligned=aligned.loc[valid].reset_index(drop=True); y=aligned.target.to_numpy(float)
        predictions=[]; audit=[]
        folds=purged_walk_forward_folds(aligned.decision_ts,aligned.exit_ts,int(self.config.stability["chronological_folds"]),str(self.config.ml.get("embargo","0s")))
        for fold,(train,validation) in enumerate(folds):
            selected=training_feature_selection(x,y,train,int(self.config.ml.get("selected_features",16)))
            audit.append({"fold":fold,"training_rows":len(train),"validation_rows":len(validation),"selected_features":[feature_ids[i] for i in selected],"train_label_max":str(aligned.exit_ts.iloc[train].max()),"validation_start":str(aligned.decision_ts.iloc[validation].min())})
            if not len(selected): continue
            for model,values in fit_predict_models(x[:,selected],y,train,validation).items():
                predictions.extend({"fold":fold,"model":model,"row":int(row),"prediction":float(value),"actual":float(y[row])} for row,value in zip(validation,values))
        self._atomic_json("ml/folds.json",{"folds":audit,"input_rows":len(observations),"valid_label_rows":len(aligned)})
        self._atomic_json("ml/dataset.json",{"grid":grid,"target_id":target_id,"feature_ids":feature_ids})
        if not predictions: return {"ml_predictions":0,"skipped":"insufficient purged training data"}
        pd.DataFrame(predictions).to_parquet(self.root/"ml"/"predictions.parquet",index=False)
        return {"ml_predictions":len(predictions),"features":len(feature_ids),"selection_policy":"training_only"}

    def _load_features(self, grid: str, requested: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
        from .cache.feature_store import ArrayStore
        if grid not in self._observation_cache:
            self._observation_cache[grid] = pd.read_parquet(self.root / "cache" / "features" / grid / "observations.parquet")
        observations = self._observation_cache[grid]
        columns = {name: self._feature_column_cache[(grid, name)] for name in requested
                   if (grid, name) in self._feature_column_cache}
        needed = set(requested).difference(columns)
        for metadata in (self.root / "cache" / "features" / grid).glob("*.json"):
            names=json.loads(metadata.read_text(encoding="utf-8")).get("columns",[])
            if not set(names).intersection(needed): continue
            values, names = ArrayStore(metadata.parent).read(metadata.stem)
            for index, name in enumerate(names):
                if name in needed:
                    columns[name] = np.asarray(values[:, index])
                    self._feature_column_cache[(grid, name)] = columns[name]
                    needed.discard(name)
            if not needed: break
        missing = [name for name in requested if name not in columns]
        if missing:
            self._materialize_missing_feature_columns(grid,missing)
            cache_name=sha256(json.dumps(sorted(missing)).encode()).hexdigest()[:20]; finalist_store=ArrayStore(self.root/"cache"/"finalist_features"/grid)
            recomputed,names=finalist_store.read(cache_name)
            for index,name in enumerate(names):
                columns[name]=np.asarray(recomputed[:,index])
                self._feature_column_cache[(grid, name)] = columns[name]
        matrix = columns[requested[0]].reshape(-1, 1) if len(requested) == 1 else np.column_stack([columns[name] for name in requested])
        return observations, matrix

    def _materialize_missing_feature_columns(self,grid:str,feature_ids:list[str])->None:
        """Build only requested compiled features, including global variants."""
        from .cache.feature_store import ArrayStore
        from .features.base import FeatureBuilder
        names=sorted(set(feature_ids)); cache_name=sha256(json.dumps(names).encode()).hexdigest()[:20]; store=ArrayStore(self.root/"cache"/"finalist_features"/grid)
        try: store.read(cache_name); return
        except (FileNotFoundError,ValueError,KeyError): pass
        feature_map={item.feature_id:item for item in self.compile_registry().features}; specs=[feature_map[name] for name in names]
        observations=self._observation_cache.get(grid)
        if observations is None: observations=pd.read_parquet(self.root/"cache"/"features"/grid/"observations.parquet")
        output=np.full((len(observations),len(specs)),np.nan,dtype=np.float32); calculation=self.root/"cache"/"calculation_panels"/f"{grid}.parquet"
        local=[(i,s) for i,s in enumerate(specs) if not _alpha_feature_is_global(s)]; global_specs=[(i,s) for i,s in enumerate(specs) if _alpha_feature_is_global(s)]
        if local:
            worker_cap=min(16,self.runtime_worker_cap) if self.runtime_worker_cap else 16; partitions=self._ensure_finalist_partitions(grid,calculation,worker_cap)
            from concurrent.futures import ProcessPoolExecutor,as_completed
            part_root=store.root/".parts"/cache_name; part_root.mkdir(parents=True,exist_ok=True); selected=[s for _,s in local]
            with ProcessPoolExecutor(max_workers=min(worker_cap,len(partitions))) as pool:
                futures=[pool.submit(_build_alpha_symbol_part,str(partition),selected,None,str(part_root/f"part-{index:05d}")) for index,partition in enumerate(partitions)]
                for future in as_completed(futures):
                    ids_path,values_path=future.result(); ids=np.load(ids_path,mmap_mode="r"); values=np.load(values_path,mmap_mode="r"); output[np.asarray(ids,dtype=np.int64)[:,None],[i for i,_ in local]]=values; del ids,values; Path(ids_path).unlink(); Path(values_path).unlink()
        if global_specs:
            indexes=[i for i,_ in global_specs]; selected=[s for _,s in global_specs]
            if grid.startswith("intraday"):
                temp=store.root/f".{cache_name}.global.npy"; values=np.lib.format.open_memmap(temp,mode="w+",dtype=np.float32,shape=(len(observations),len(selected))); values[:]=np.nan
                self._build_global_feature_chunks(calculation,[(cache_name,selected,values)]); output[:,indexes]=values; del values; temp.unlink(missing_ok=True)
            else:
                frame=pd.read_parquet(calculation); self._compact_feature_frame(frame); builder=FeatureBuilder(frame); emit=builder.frame.emit.to_numpy(bool)&~builder.frame.observation_id.duplicated().to_numpy(); ids=builder.frame.loc[emit,"observation_id"].to_numpy(np.int64); output[np.asarray(ids,dtype=np.int64)[:,None],indexes]=builder.build_many(selected).to_numpy(dtype=np.float32,na_value=np.nan)[emit]
        store.write(cache_name,output,names)

    def _ensure_finalist_partitions(self, grid: str, calculation: Path, buckets: int) -> list[Path]:
        """Scan the large calculation panel once and persist 16 independent worker buckets."""
        import duckdb
        import shutil
        root=self.root/"cache"/"finalist_partitions_v1"/grid
        marker=root/"_SUCCESS.json"; source=calculation.stat()
        expected={"source_size":source.st_size,"source_mtime_ns":source.st_mtime_ns,"buckets":int(buckets)}
        if marker.exists() and json.loads(marker.read_text(encoding="utf-8"))==expected:
            parts=sorted(path for path in root.glob("worker_bucket=*") if path.is_dir())
            if len(parts)==buckets: return parts
        cache_root=(self.root/"cache"/"finalist_partitions_v1").resolve()
        resolved=root.resolve()
        if not resolved.is_relative_to(cache_root): raise RuntimeError("Unsafe finalist partition cache path")
        if root.exists(): shutil.rmtree(root)
        root.mkdir(parents=True,exist_ok=True)
        destination=root.as_posix().replace("'","''")
        temp=Path(self.config.compute.duckdb_temp_directory); temp.mkdir(parents=True,exist_ok=True)
        with duckdb.connect() as connection:
            connection.execute(f"SET temp_directory='{temp.as_posix().replace(chr(39),chr(39)*2)}'")
            connection.execute(f"SET memory_limit='{self.config.compute.duckdb_memory_limit}'")
            connection.execute(f"SET threads={buckets}")
            connection.execute(f"""COPY (SELECT *,hash(security_id)%{buckets} AS worker_bucket
                FROM read_parquet(?)) TO '{destination}'
                (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(worker_bucket),ROW_GROUP_SIZE 250000)""",[str(calculation)])
        temporary=marker.with_suffix(".tmp.json")
        temporary.write_text(json.dumps(expected,indent=2),encoding="utf-8"); temporary.replace(marker)
        parts=sorted(path for path in root.glob("worker_bucket=*") if path.is_dir())
        if len(parts)!=buckets: raise RuntimeError(f"Expected {buckets} finalist partitions, found {len(parts)}")
        return parts

    def _stage_distill_ml(self) -> dict:
        marker=self._require("run-ml")
        if marker.get("skipped"):
            return {"distilled_models":0,"skipped":marker["skipped"]}
        predictions = pd.read_parquet(self.root / "ml" / "predictions.parquet")
        if predictions.empty: raise ValueError("ML produced no out-of-fold predictions")
        summary = predictions.groupby("model", observed=True).apply(lambda x: pd.Series({"oof_correlation": x.prediction.corr(x.actual, method="spearman"), "mse": np.mean((x.prediction-x.actual)**2), "rows": len(x)}), include_groups=False).reset_index()
        summary.to_parquet(self.root / "ml" / "distillation.parquet", index=False)
        return {"distilled_models": len(summary)}

    @staticmethod
    def _bucket(values: pd.Series, bins: int = 5) -> pd.Series:
        numeric = pd.to_numeric(values, errors="coerce")
        try: return pd.qcut(numeric.rank(method="first"), bins, labels=False, duplicates="drop").astype("Int64").astype(str)
        except ValueError: return pd.Series("single", index=values.index)

    def _actual_trade_path_diagnostics(self, windows: pd.DataFrame, memory_limit: str = "512MB",
                                       temp_directory: Path | None = None) -> pd.DataFrame:
        """Compute exact finalist paths in DuckDB and return one row per window."""
        from .targets.excursions import actual_trade_path_diagnostics
        return actual_trade_path_diagnostics(windows,duckdb_path=self.config.source.duckdb_path,
            bars_table=self.config.source.bars_1m_raw_table,discovery_end=self.config.research_periods.discovery_end,
            temp_directory=Path(temp_directory or self.config.compute.duckdb_temp_directory),memory_limit=memory_limit)

    def _edge_autopsy_worker_budget(self, grids: set[str]) -> int:
        largest=0
        for grid in grids:
            panel=self.root/"cache"/"panels"/f"{grid}.parquet"
            targets=self.root/"cache"/"targets"/f"{grid}.parquet"
            largest=max(largest,(panel.stat().st_size if panel.exists() else 0)+(targets.stat().st_size if targets.exists() else 0))
        minimum_gb=float(self.config.edge_autopsy.get("parallel_worker_min_gb",4.0))
        expansion=float(self.config.edge_autopsy.get("parallel_memory_expansion",1.10))
        return max(int(minimum_gb*(1<<30)),int(largest*expansion))

    def _ensure_autopsy_context(self, grid: str, memory_limit: str, threads: int,
                                 temp_directory: Path) -> Path:
        """Materialize candidate-independent regime inputs once per decision grid."""
        import duckdb
        root=self.root/"cache"/"autopsy_context_v1"; root.mkdir(parents=True,exist_ok=True)
        target=root/f"{grid}.parquet"
        if target.exists(): return target
        temporary=root/f"{grid}.tmp.parquet"; temporary.unlink(missing_ok=True)
        panel=self.root/"cache"/"panels"/f"{grid}.parquet"
        destination=temporary.as_posix().replace("'","''")
        with duckdb.connect() as connection:
            connection.execute(f"SET temp_directory='{temp_directory.as_posix().replace(chr(39),chr(39)*2)}'")
            connection.execute(f"SET memory_limit='{memory_limit}'")
            connection.execute(f"SET threads={max(1,int(threads))}")
            connection.execute(f"""COPY (WITH returns AS (
                  SELECT observation_id,security_id,decision_ts,close::DOUBLE AS close,volume::DOUBLE AS volume,
                         close::DOUBLE/lag(close::DOUBLE) OVER(
                           PARTITION BY security_id ORDER BY decision_ts,observation_id)-1 AS simple_return
                  FROM read_parquet(?)
                ), regimes AS (
                  SELECT *,avg(CASE WHEN simple_return>0 THEN 1.0 ELSE 0.0 END) OVER(
                           PARTITION BY decision_ts) AS breadth_value,
                         stddev_samp(simple_return) OVER(PARTITION BY decision_ts) AS dispersion_value,
                         CASE WHEN count(simple_return) OVER(PARTITION BY security_id ORDER BY decision_ts,observation_id
                                  ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)>=3
                              THEN stddev_samp(simple_return) OVER(PARTITION BY security_id ORDER BY decision_ts,observation_id
                                  ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) END AS volatility_value
                  FROM returns
                ) SELECT observation_id,close,volume,breadth_value,dispersion_value,volatility_value
                  FROM regimes) TO '{destination}' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 250000)""",[str(panel)])
        temporary.replace(target)
        return target

    def _run_edge_autopsy_candidate(self, candidate_index: int, row_payload: dict,
                                    peer_feature_ids: tuple[str, ...], duckdb_memory_limit: str="512MB",
                                    threads_per_worker: int=1) -> dict | None:
        from .autopsy.run import EDGE_AUTOPSY_ENGINE_VERSION, EdgeAutopsy
        from .candidates import CandidateRule, dual_positions, single_positions
        from types import SimpleNamespace
        row=SimpleNamespace(**row_payload)
        feature_ids=[row.feature_a] if row.structure_type=="single" else [row.feature_a,row.feature_b]
        direction=1 if float(row.effect)>=0 else -1
        rule=(CandidateRule.create("single",tuple(feature_ids),row.target_id,direction) if row.structure_type=="single" else
              CandidateRule.create("dual",tuple(feature_ids),row.target_id,direction,int(row.resolution),(int(row.selected_cell),)))
        autopsy_id=f"candidate-{candidate_index:04d}"; candidate_root=self.root/"edge_autopsy"/autopsy_id
        worker_temp=Path(self.config.compute.duckdb_temp_directory)/"edge_autopsy"/f"{autopsy_id}-{os.getpid()}"
        worker_temp.mkdir(parents=True,exist_ok=True)
        manifest_path=candidate_root/"manifest.json"; execution_path=candidate_root/"execution.json"
        if manifest_path.exists() and execution_path.exists():
            prior_manifest=json.loads(manifest_path.read_text(encoding="utf-8")); prior_execution=json.loads(execution_path.read_text(encoding="utf-8"))
            if (prior_manifest.get("candidate_rule_hash")==rule.definition_hash and
                    prior_manifest.get("engine_version")==EDGE_AUTOPSY_ENGINE_VERSION):
                metrics=prior_manifest["metrics"]; selection_score=float(row.stability_score)*max(metrics["best_net_edge"],0)*metrics["positive_delay_cost_fraction"]*np.log1p(metrics["max_capacity_eligible_trades"])
                return {"candidate_id":autopsy_id,"rule":rule.to_dict(),"feature_ids":feature_ids,"target_id":row.target_id,"autopsy_complete":True,"execution_validated":False,"execution_status":prior_execution["execution_status"],"autopsy_pass":prior_manifest["overall_status"]=="PASS","autopsy_checks":prior_manifest["checks"],"stability_score":row.stability_score,"selection_score":selection_score,"selection_components":metrics}
        feature_map={item.feature_id:item for item in self.compile_registry().features}
        feature=feature_map[feature_ids[0]]
        same_grid_peers=[peer for peer in peer_feature_ids
                         if peer in feature_map and feature_map[peer].decision_grid==feature.decision_grid]
        load_ids=list(dict.fromkeys([*feature_ids,*same_grid_peers]))
        observations, loaded_matrix = self._load_features(feature.decision_grid, load_ids)
        matrix=loaded_matrix[:,:len(feature_ids)]
        loaded_columns={name:loaded_matrix[:,index] for index,name in enumerate(load_ids)}
        primary = self._target_ids_and_vector(feature.decision_grid,observations,row.target_id)
        if row.structure_type=="single":
            score=matrix[:,0]*direction
            positions=np.maximum(single_positions(matrix[:,0],direction,rule.tail_fraction,decision_ts=observations.decision_ts),0)
        else:
            all_bins,_=self._ensure_bin_cache(feature.decision_grid,observations); resolution=int(row.resolution)
            mapping=all_bins
            def bin_column(name):
                from .cache.rank_store import unpack_bins
                path,index=mapping[name]; return unpack_bins(np.load(path,mmap_mode="r")[:,index],resolution)
            positions=dual_positions(bin_column(feature_ids[0]),bin_column(feature_ids[1]),rule); score=positions.astype(float)
        active=np.isfinite(primary)&(positions!=0)
        base=observations.loc[active].reset_index(drop=True); score=score[active]; primary=np.asarray(primary[active],dtype=float); positions=positions[active]
        import duckdb
        target_path=self.root / "cache" / "targets" / f"{feature.decision_grid}.parquet"
        context_path=self._ensure_autopsy_context(feature.decision_grid,duckdb_memory_limit,
                                                  threads_per_worker,worker_temp)
        active_context=base[["observation_id","security_id","decision_ts"]].copy()
        active_context.insert(0,"candidate_row_id",np.arange(len(active_context),dtype=np.int64))
        with duckdb.connect() as input_connection:
            input_connection.execute(f"SET temp_directory='{worker_temp.as_posix().replace(chr(39),chr(39)*2)}'")
            input_connection.execute(f"SET memory_limit='{duckdb_memory_limit}'")
            input_connection.execute(f"SET threads={max(1,int(threads_per_worker))}")
            input_connection.register("active_context",active_context)
            target_rows=input_connection.execute("""SELECT a.candidate_row_id,t.observation_id,t.entry_price,t.exit_price,t.entry_ts,t.exit_ts
                FROM active_context a JOIN read_parquet(?) t USING(observation_id)
                WHERE t.target_id=? ORDER BY a.candidate_row_id""",
                [str(target_path),row.target_id]).fetchdf()
            panel_rows=input_connection.execute("""SELECT a.candidate_row_id,c.*
                FROM active_context a JOIN read_parquet(?) c USING(observation_id)
                ORDER BY a.candidate_row_id""",[str(context_path)]).fetchdf()
        if len(target_rows)!=len(base) or len(panel_rows)!=len(base):
            raise RuntimeError(f"Autopsy input alignment failed: base={len(base)}, targets={len(target_rows)}, panel={len(panel_rows)}")
        expected_ids=base.observation_id.to_numpy()
        if not (np.array_equal(target_rows.observation_id.to_numpy(),expected_ids) and
                np.array_equal(panel_rows.observation_id.to_numpy(),expected_ids)):
            raise RuntimeError("Autopsy input observation order mismatch")
        aligned=base.copy()
        for name in ("entry_price","exit_price","entry_ts","exit_ts"):
            aligned[name]=target_rows[name].to_numpy()
        for name in ("close","volume"):
            aligned[name]=panel_rows[name].to_numpy()
        close = pd.to_numeric(aligned.close, errors="coerce"); volume = pd.to_numeric(aligned.volume, errors="coerce")
        market = pd.to_numeric(aligned.get("benchmark_return", pd.Series(0.0, index=aligned.index)), errors="coerce").fillna(0)
        aligned["market_trend"] = np.sign(market.rolling(20, min_periods=1).sum()).astype(str)
        aligned["market_vol"] = self._bucket(market.rolling(20, min_periods=2).std())
        aligned["breadth"] = self._bucket(panel_rows.breadth_value)
        aligned["dispersion"] = self._bucket(panel_rows.dispersion_value)
        aligned["correlation_regime"] = self._bucket(market.rolling(20, min_periods=3).std())
        local = pd.to_datetime(aligned.decision_ts, utc=True).dt.tz_convert("America/New_York")
        aligned["time_of_day"] = local.dt.strftime("%H:%M"); aligned["day_of_week"] = local.dt.dayofweek.astype(str)
        aligned["price_bucket"] = self._bucket(close); aligned["liquidity_bucket"] = self._bucket(close * volume)
        aligned["volatility_bucket"] = self._bucket(panel_rows.volatility_value)
        aligned["beta_bucket"] = self._bucket(aligned.get("beta_prior", pd.Series(1.0, index=aligned.index)))
        aligned["size_bucket"] = self._bucket(close * volume)
        aligned["trade_notional"] = 10_000.0; aligned["bar_dollar_volume"] = close * volume
        aligned["market_factor"] = market
        aligned["variant_winsorized"] = pd.Series(score).clip(pd.Series(score).quantile(.01), pd.Series(score).quantile(.99))
        for peer_index, peer in enumerate(peer_feature_ids):
            if peer == row.feature_id or peer not in loaded_columns: continue
            aligned[f"candidate_score_{peer_index}"] = loaded_columns[peer][active]
        aligned["position"]=positions
        delay_root=self.root/"edge_autopsy"/f"candidate-{candidate_index:04d}"
        delay_root.mkdir(parents=True,exist_ok=True)
        from .execution.portfolio_replay import replay_portfolio
        trades,rejections,execution_metrics=replay_portfolio(aligned,max_positions=int(self.config.edge_autopsy.get("max_positions",20)),
            cost_bps=float(self.config.edge_autopsy.get("base_cost_bps",5)),slippage_bps=float(self.config.edge_autopsy.get("base_slippage_bps",2)))
        trades.to_parquet(delay_root/"portfolio_trades.parquet",index=False); rejections.to_parquet(delay_root/"portfolio_rejections.parquet",index=False)
        self._atomic_json(f"edge_autopsy/candidate-{candidate_index:04d}/execution.json",execution_metrics)
        path_columns=["mfe","mae","time_to_mfe","time_to_mae","terminal_return","mfe_minus_terminal","recovery_after_mae"]
        aligned["path_count"]=0
        for name in path_columns: aligned[name]=np.nan
        executed_ids=trades.source_row.to_numpy(dtype=np.int64) if not trades.empty else np.empty(0,dtype=np.int64)
        executed=aligned.iloc[executed_ids].copy()
        if len(executed):
            diagnostics=self._actual_trade_path_diagnostics(executed,duckdb_memory_limit,worker_temp)
            aligned.loc[executed_ids,["path_count",*path_columns]]=diagnostics[["path_count",*path_columns]].to_numpy()
        from .execution.delays import measured_entry_delays
        with duckdb.connect(self.config.source.duckdb_path,read_only=True) as connection:
            connection.execute(f"SET temp_directory='{worker_temp.as_posix().replace(chr(39),chr(39)*2)}'")
            connection.execute(f"SET memory_limit='{duckdb_memory_limit}'")
            connection.execute(f"SET threads={max(1,int(threads_per_worker))}")
            delayed,delay_attrition=measured_entry_delays(executed,connection,self.config.source.bars_1m_raw_table,
                self.config.research_periods.discovery_end,self.config.edge_autopsy["entry_delay_minutes"])
        delay_root.mkdir(parents=True,exist_ok=True); delay_attrition.to_parquet(delay_root/"delay_attrition.parquet",index=False)
        metadata = aligned[["security_id", "session_date", "decision_ts", "trade_notional", "bar_dollar_volume", "entry_price", "path_count",
                            "mfe", "mae", "time_to_mfe", "time_to_mae", "terminal_return", "mfe_minus_terminal", "recovery_after_mae",
                            "market_trend", "market_vol", "breadth", "dispersion", "correlation_regime", "time_of_day", "day_of_week",
                            "price_bucket", "liquidity_bucket", "volatility_bucket", "beta_bucket", "size_bucket", "market_factor", "variant_winsorized",
                            *[column for column in aligned if column.startswith("candidate_score_")]]]
        valid = np.isfinite(score) & np.isfinite(primary)
        if valid.sum() < 20: return None
        autopsy_config={**self.config.edge_autopsy,"placebo_workers":max(1,int(threads_per_worker))}
        manifest=EdgeAutopsy(candidate_root,autopsy_config).run(score[valid], {row.target_id: primary[valid]}, metadata.loc[valid].reset_index(drop=True), delayed, positions[valid]*primary[valid],rule.definition_hash)
        metrics=manifest["metrics"]; selection_score=float(row.stability_score)*max(metrics["best_net_edge"],0)*metrics["positive_delay_cost_fraction"]*np.log1p(metrics["max_capacity_eligible_trades"])
        return {"candidate_id":autopsy_id,"rule":rule.to_dict(),"feature_ids":feature_ids,"target_id":row.target_id,"autopsy_complete":True,"execution_validated":False,"execution_status":execution_metrics["execution_status"],"autopsy_pass":manifest["overall_status"]=="PASS","autopsy_checks":manifest["checks"],"stability_score":row.stability_score,"selection_score":selection_score,"selection_components":metrics}

    def _stage_run_edge_autopsy(self) -> dict:
        from .resources import calibrated_resources, host_memory_headroom
        self._require("build-stability"); stable = self._stable_rows(int(self.config.edge_autopsy.get("max_candidates",16)))
        if stable.empty:
            self._atomic_json("edge_autopsy/candidates.json", {"candidates":[],"rejected":0,"reason":"no_stable_structures"})
            return {"completed_autopsies":0,"passed_autopsies":0,"skipped":"no_stable_structures"}
        records=stable.to_dict("records"); peers=tuple(stable.feature_id.head(4).astype(str))
        bundle=compile_registry(self.config); feature_grid={item.feature_id:item.decision_grid for item in bundle.features}
        grids={feature_grid[str(row["feature_a"])] for row in records}
        worker_budget=self._edge_autopsy_worker_budget(grids)
        available,_,total=host_memory_headroom(self.config.compute)
        configured_workers,_,_=calibrated_resources(self.config.compute)
        parallel_workers=1
        duckdb_memory_limit=str(self.config.compute.duckdb_memory_limit)
        threads_per_worker=configured_workers
        completed=[]
        for index,row in enumerate(records):
            result=self._run_edge_autopsy_candidate(index,row,peers,duckdb_memory_limit,threads_per_worker)
            if result is not None: completed.append(result)
            self._atomic_json("edge_autopsy/candidates.partial.json",{
                "completed":completed,"processed_candidates":index+1,"total_candidates":len(records)})
        if not completed:
            self._atomic_json("edge_autopsy/candidates.json", {"candidates":[],"rejected":0,"reason":"insufficient_aligned_observations"})
            return {"completed_autopsies":0,"passed_autopsies":0,"skipped":"insufficient_aligned_observations",
                    "parallel_workers":parallel_workers,"worker_memory_budget_bytes":worker_budget}
        passed=sorted([candidate for candidate in completed if candidate["autopsy_pass"]],key=lambda item:(-item["selection_score"],item["candidate_id"]))[:8]
        self._atomic_json("edge_autopsy/candidates.json", {"candidates": passed,"rejected":len(completed)-len(passed)})
        return {"completed_autopsies":len(completed),"passed_autopsies":len(passed),"parallel_workers":parallel_workers,
                "worker_memory_budget_bytes":worker_budget,"host_memory_fraction":self.config.compute.host_memory_fraction,
                "cpu_workers":configured_workers,"threads_per_worker":threads_per_worker,
                "duckdb_memory_limit_per_worker":duckdb_memory_limit,"parallel_backend":"processes"}

    def _stage_audit_exhaustiveness(self) -> dict:
        from .scan.pair_plan import PairPlan
        bundle = self.compile_registry(); initial_specs=[]; expected_singles=0; unavailable_singles=0; realized_targets={}
        for grid in {item.decision_grid for item in bundle.features}:
            registered=[item for item in bundle.features if item.decision_grid==grid]; scoped,_=_initial_feature_scope(registered,self.config)
            registered_target_ids={item.target_id for item in bundle.targets if item.decision_grid==grid}
            target_meta=self.root/"cache"/"target_store"/grid/"aligned.json"
            realized_targets[grid]=set(json.loads(target_meta.read_text(encoding="utf-8")).get("columns",[])) if target_meta.exists() else set()
            missing_targets=registered_target_ids-realized_targets[grid]
            initial_specs.extend(scoped); expected_singles+=len(scoped)*len(registered_target_ids); unavailable_singles+=len(scoped)*len(missing_targets)
        single_files = list((self.root / "single_results").glob("*/*.parquet"))
        attempted_singles = sum(int(pd.read_parquet(path, columns=["fold_id"]).fold_id.eq("all").sum()) for path in single_files)
        raw_pairs = 0; expected_pairs = 0; structural_exclusions = 0; alias_exclusions = 0; unavailable_target_pairs=0
        for grid in {item.decision_grid for item in bundle.features}:
            registered = [item for item in bundle.features if item.decision_grid == grid]; specs,_=_initial_feature_scope(registered,self.config)
            raw_pairs += len(registered) * (len(registered)-1)//2
            alias_file=self.root/"cache"/"bins"/grid/"aliases.json"
            alias_hashes=json.loads(alias_file.read_text(encoding="utf-8")).get("realized_hashes",{}) if alias_file.exists() else {}
            scoped,_=_dual_parent_scope(specs,self.config.duals)
            if self.config.duals.get("parent_filter")=="single_survivors":
                scoped=_single_survivor_scope(scoped,self.root/"single_results"/grid,self.config.duals)
            total=len(registered)*(len(registered)-1)//2; canonical_total=len(scoped)*(len(scoped)-1)//2
            plan=PairPlan.compile([item.feature_id for item in scoped],alias_hashes)
            registered_target_count=sum(item.decision_grid==grid for item in bundle.targets)
            realized_target_count=len(realized_targets.get(grid,set())); missing_target_count=registered_target_count-realized_target_count
            structural_exclusions+=(total-canonical_total)*realized_target_count
            alias_exclusions+=(canonical_total-len(plan.left))*realized_target_count
            unavailable_target_pairs+=len(plan.left)*missing_target_count
            expected_pairs+=len(plan.left)*realized_target_count
        def count_tree(name: str) -> int:
            return sum(len(pd.read_parquet(path, columns=["pair_id"])) for path in (self.root / name).glob("**/part-*.parquet"))
        coarse, fine, exact = count_tree("dual_coarse_results"), count_tree("dual_fine_results"), count_tree("dual_exact_results")
        resolutions=tuple(self.config.duals.get("resolutions",(3,5,10)))
        counts={3:coarse,5:fine,10:exact}; scoped_complete=all(counts[r]==expected_pairs for r in resolutions)
        primary_count=counts[min(resolutions)]
        audit = ExhaustivenessAudit(len(bundle.concepts), len(bundle.features), len(initial_specs), len(bundle.unavailable), len(bundle.targets),
            expected_singles, attempted_singles, unavailable_singles, 0, raw_pairs, {"noncanonical_concept_variant":structural_exclusions,"exact_alias":alias_exclusions,"unavailable_target":unavailable_target_pairs}, expected_pairs,
            expected_pairs, primary_count, primary_count, fine, int(not scoped_complete), 5 in resolutions,exact,10 in resolutions)
        audit.write(self.root / "exhaustiveness_manifest.json")
        payload=json.loads((self.root/"exhaustiveness_manifest.json").read_text())
        payload.update(scope="declared_base_features_and_resolutions",resolutions=list(resolutions),generated_expressions_count_as_tested=False)
        self._atomic_json("exhaustiveness_manifest.json",payload)
        return {"exhaustiveness_status": audit.status, "expected_single_tests": expected_singles, "attempted_single_tests": attempted_singles,
                "unavailable_single_tests":unavailable_singles,"expected_pair_target_tests": expected_pairs,
                "unavailable_pair_target_tests":unavailable_target_pairs,"coarse_completed": coarse, "fine_completed": fine,"exact_completed":exact}

    def _stage_freeze_discovery(self) -> dict:
        from .governance.freeze import freeze_candidates
        from .governance.state import ResearchStateMachine
        self._require("run-edge-autopsy"); self._require("audit-exhaustiveness")
        audit = json.loads((self.root / "exhaustiveness_manifest.json").read_text(encoding="utf-8")); candidates = json.loads((self.root / "edge_autopsy" / "candidates.json").read_text(encoding="utf-8"))["candidates"]
        digest = freeze_candidates(self.root / "candidate_freeze.json", candidates, audit)
        machine = ResearchStateMachine.load(self.root / "research_state.json")
        if machine.state == ResearchState.BUILD_ONLY: machine.transition(ResearchState.DISCOVERY_OPEN)
        machine.transition(ResearchState.DISCOVERY_FROZEN, {"exhaustiveness": audit.get("exhaustiveness_status") == "PASS", "autopsy": bool(candidates)})
        return {"candidate_count": len(candidates), "freeze_sha256": digest}

    def _stage_evaluate_replication(self) -> dict:
        from .governance.freeze import verify_manifest
        from .governance.state import ResearchStateMachine
        self._require("freeze-discovery"); manifest = verify_manifest(self.root / "candidate_freeze.json")
        if not self.config.research_periods.allow_replication_access: raise PermissionError("Replication remains sealed; set allow_replication_access only when the campaign is authorized")
        machine = ResearchStateMachine.load(self.root / "research_state.json")
        machine.transition(ResearchState.REPLICATION_OPEN, {"candidate_freeze": bool(manifest["candidates"])})
        results = self._evaluate_period(ResearchState.REPLICATION_OPEN, manifest["candidates"])
        results.to_parquet(self.root / "replication" / "evaluation.parquet", index=False)
        return {"replication_candidates": len(results)}

    def _stage_freeze_replication(self) -> dict:
        from .governance.freeze import _write_frozen
        from .governance.state import ResearchStateMachine
        self._require("evaluate-replication"); results = pd.read_parquet(self.root / "replication" / "evaluation.parquet")
        digest = _write_frozen(self.root / "replication_freeze.json", {"kind": "replication_freeze", "results": results.to_dict("records")})
        machine = ResearchStateMachine.load(self.root / "research_state.json"); machine.transition(ResearchState.REPLICATION_FROZEN)
        return {"replication_freeze_sha256": digest, "candidates": len(results)}

    def _evaluate_period(self, state: ResearchState, candidates: list[dict]) -> pd.DataFrame:
        from .cache.rank_store import build_rank_bins
        from .candidates import CandidateRule, dual_positions, single_positions
        from .data.panel import build_decision_panel
        from .data.source import DuckDBSource
        from .data.universe import apply_point_in_time_universe
        from .features.base import FeatureBuilder
        from .governance.access import AccessGate
        from .scan.statistics import pairwise_rank_ic, quantile_spread
        from .targets.builder import build_daily_targets, build_intraday_targets, build_overnight_targets
        source = DuckDBSource(Path(self.config.source.duckdb_path), AccessGate(self.config, state))
        raw_columns = tuple(sorted(source.table_columns(self.config.source.bars_1m_raw_table) & {"security_id","symbol","bar_start_ts_utc","bar_end_ts_utc","availability_ts_utc","session_date","open","high","low","close","volume","vwap","trade_count","feed","adjustment","ingest_batch_id"}))
        raw = source.read_table(self.config.source.bars_1m_raw_table, raw_columns)
        research_columns = tuple(sorted(source.table_columns(self.config.source.bars_1m_research_table) & {"security_id","bar_start_ts_utc","research_open","research_high","research_low","research_close","split_factor","price_basis"}))
        research = source.read_table(self.config.source.bars_1m_research_table, research_columns)
        membership = source.read_table(self.config.source.membership_table, ("security_id","session_date","in_universe"))
        security = source.read_dimension(self.config.source.security_master_table, ("security_id","symbol"))
        bars = raw.merge(research, on=["security_id","bar_start_ts_utc"], how="left", validate="one_to_one")
        bundle = compile_registry(self.config); feature_map = {item.feature_id:item for item in bundle.features}; results=[]
        for grid in sorted({feature_map[candidate["feature_ids"][0]].decision_grid for candidate in candidates}):
            decision_rows = build_decision_panel(bars, grid, self.config.source.benchmark_symbols[0]); panel = apply_point_in_time_universe(decision_rows, membership, security)
            benchmark_ids=set(security.loc[security.symbol.isin(self.config.source.benchmark_symbols),"security_id"]); benchmark=decision_rows[decision_rows.security_id.isin(benchmark_ids)].copy(); benchmark["in_universe"]=False
            panel=pd.concat([panel,benchmark],ignore_index=True).drop_duplicates("observation_id").sort_values(["security_id","decision_ts"],kind="mergesort")
            if grid.startswith("intraday"): targets=build_intraday_targets(panel,raw,tuple(int(x[:-1]) for x in self.config.targets["intraday"] if str(x).endswith("m")),"EOD" in self.config.targets["intraday"])
            elif grid=="daily_close": targets=build_daily_targets(panel,raw,tuple(int(x[:-1]) for x in self.config.targets["interday"]),int(self.config.targets["daily_entry_delay_minutes"]))
            else: targets=build_overnight_targets(panel,raw)
            targets=targets.merge(panel[["observation_id","symbol",*[column for column in ("beta_prior",) if column in panel]]].drop_duplicates("observation_id"),on="observation_id",how="left",validate="many_to_one")
            benchmark_key="decision_ts" if grid.startswith("intraday") else "session_date"
            bench=targets[targets.symbol.eq(self.config.source.benchmark_symbols[0])][[benchmark_key,"target_id","target"]].rename(columns={"target":"benchmark_target"}).drop_duplicates([benchmark_key,"target_id"])
            enriched=targets.merge(bench,on=[benchmark_key,"target_id"],how="left",validate="many_to_one"); variants=[enriched]
            adjusted=enriched.copy(); adjusted["target"]-=adjusted.benchmark_target; adjusted["target_id"]=adjusted.target_id.str.replace("__raw__","__benchmark_adjusted__",regex=False); variants.append(adjusted)
            residual=enriched.copy(); residual["target"]-=residual.get("beta_prior",pd.Series(1.0,index=residual.index)).fillna(1)*residual.benchmark_target; residual["target_id"]=residual.target_id.str.replace("__raw__","__beta_residual__",regex=False); variants.append(residual)
            target_table=pd.concat(variants,ignore_index=True)
            builder=FeatureBuilder(panel)
            for candidate in [item for item in candidates if feature_map[item["feature_ids"][0]].decision_grid==grid]:
                values=[builder.build(feature_map[feature_id]).to_numpy(float) for feature_id in candidate["feature_ids"]]
                rule_payload=candidate.get("rule")
                if rule_payload:
                    rule_payload=dict(rule_payload); rule_payload["feature_ids"]=tuple(rule_payload["feature_ids"]); rule_payload["active_cells"]=tuple(rule_payload.get("active_cells",()))
                    rule=CandidateRule(**rule_payload)
                    if rule.structure_type=="dual":
                        labels,_=build_rank_bins(np.column_stack(values),pd.factorize(panel.decision_ts,sort=True)[0],int(rule.resolution))
                        score=np.maximum(dual_positions(labels[:,0],labels[:,1],rule),0)
                    else: score=np.maximum(single_positions(values[0],rule.direction,rule.tail_fraction,decision_ts=panel.decision_ts),0)
                else: score=np.nanmean(np.column_stack(values),axis=1)
                selected=target_table[target_table.target_id.eq(candidate["target_id"])][["observation_id","target"]]
                y=panel[["observation_id"]].merge(selected,on="observation_id",how="left").target.to_numpy(float); ic,count=pairwise_rank_ic(score,y)
                active=np.isfinite(y)&(score!=0); candidate_return=score[active]*y[active]
                results.append({"candidate_id":candidate.get("candidate_id"),"feature_ids":candidate["feature_ids"],"target_id":candidate["target_id"],"rule":rule_payload,"rule_hash":rule_payload.get("definition_hash") if rule_payload else None,"n_obs":count,"active_observations":int(active.sum()),"rank_ic":ic,"top_bottom_spread":quantile_spread(score,y),"candidate_mean_return":float(np.mean(candidate_return)) if len(candidate_return) else np.nan,"period":state.value})
        return pd.DataFrame(results)

    def _stage_build_alphas(self) -> dict:
        from .alpha.registry import AlphaRegistry
        from .governance.freeze import verify_manifest
        from .models import AlphaSpec, stable_hash
        self._require("freeze-replication"); frozen=verify_manifest(self.root/"replication_freeze.json"); registry=AlphaRegistry()
        for index,row in enumerate(frozen["results"]):
            direction=1 if float(row.get("rank_ic") or 0)>=0 else -1; alpha_id=f"alpha-{index:04d}"
            rule=row.get("rule") or {}; payload={"alpha_id":alpha_id,"features":row["feature_ids"],"target":row["target_id"],"direction":direction,"rule":rule}
            registry.add(AlphaSpec(alpha_id,"single" if len(row["feature_ids"])==1 else "dual",tuple(row["feature_ids"]),row["target_id"],"frozen_candidate_rule",direction,{"source":"replication_locked","rule":rule},next(item.decision_grid for item in compile_registry(self.config).targets if item.target_id==row["target_id"]),row["target_id"].split("__")[0],stable_hash(payload)))
        destination=self.root/"alpha_repository.parquet"; registry.write(destination); return {"alphas":len(registry.specs)}

    def _stage_evaluate_alphas(self) -> dict:
        self._require("build-alphas"); alphas=pd.read_parquet(self.root/"alpha_repository.parquet"); replication=pd.read_parquet(self.root/"replication"/"evaluation.parquet")
        evaluated=alphas.merge(replication[["target_id","rank_ic","top_bottom_spread","n_obs"]],on="target_id",how="left")
        evaluated["directional_replication_effect"]=evaluated.direction*evaluated.top_bottom_spread; evaluated.to_parquet(self.root/"replication"/"alpha_evaluation.parquet",index=False)
        return {"evaluated_alphas":len(evaluated)}

    def _stage_freeze_portfolio(self) -> dict:
        from .governance.freeze import freeze_portfolio
        from .governance.state import ResearchStateMachine
        self._require("evaluate-alphas"); evaluated=pd.read_parquet(self.root/"replication"/"alpha_evaluation.parquet").sort_values("directional_replication_effect",ascending=False)
        included=evaluated[evaluated.directional_replication_effect.gt(0)].alpha_id.tolist()
        if not included: raise RuntimeError("No alpha passed the predeclared positive replication-direction gate")
        portfolio={"included_alphas":included,"allocation_rule":"equal_weight","rebalance_rule":"at_each_alpha_decision","risk_limits":{"gross_leverage":1.0,"max_alpha_weight":min(0.35,1/len(included))},"cost_model":{"per_side_bps":[0,1,3,5]},"entry_exit_mappings":evaluated[evaluated.alpha_id.isin(included)][["alpha_id","target_id"]].to_dict("records")}
        digest=freeze_portfolio(self.root/"portfolio_freeze.json",portfolio); machine=ResearchStateMachine.load(self.root/"research_state.json"); machine.transition(ResearchState.PORTFOLIO_FROZEN)
        return {"portfolio_freeze_sha256":digest,"included_alphas":len(included)}

    def _stage_evaluate_final_holdout(self) -> dict:
        from .governance.freeze import verify_manifest
        from .governance.state import ResearchStateMachine
        self._require("freeze-portfolio")
        if not self.config.research_periods.allow_final_holdout_access: raise PermissionError("Final holdout remains sealed; enable it only for the one-way confirmation")
        portfolio=verify_manifest(self.root/"portfolio_freeze.json")["portfolio"]; alphas=pd.read_parquet(self.root/"alpha_repository.parquet"); selected=alphas[alphas.alpha_id.isin(portfolio["included_alphas"])]
        candidates=[{"candidate_id":row.alpha_id,"feature_ids":list(row.feature_ids),"target_id":row.target_id,"rule":row.plateau_definition.get("rule") if isinstance(row.plateau_definition,dict) else None} for row in selected.itertuples()]
        machine=ResearchStateMachine.load(self.root/"research_state.json"); machine.transition(ResearchState.FINAL_HOLDOUT_OPEN)
        results=self._evaluate_period(ResearchState.FINAL_HOLDOUT_OPEN,candidates); results.to_parquet(self.root/"final_holdout_results.parquet",index=False); machine.transition(ResearchState.FINAL_COMPLETE)
        return {"final_candidates":len(results)}

    def _stage_build_report(self) -> dict:
        self.build_report_shells(); markers=[]
        for path in (self.root/"checkpoints").glob("*.json"):
            payload=json.loads(path.read_text(encoding="utf-8")); markers.append({"stage":payload.get("stage"),"status":payload.get("status")})
        pd.DataFrame(markers).to_parquet(self.root/"reports"/"stage_status.parquet",index=False)
        return {"reports":len(list((self.root/"reports").glob("*.md")))}

    def compile_registry(self) -> RegistryBundle:
        if getattr(self,"_registry_bundle",None) is not None: return self._registry_bundle
        self.initialize(); bundle = compile_registry(self.config); eligibility = EligibilityMatrix.build(bundle.features, bundle.targets)
        self._registry_bundle=bundle
        bundle.feature_frame().to_parquet(self.root / "feature_registry.parquet", index=False)
        bundle.target_frame().to_parquet(self.root / "target_registry.parquet", index=False)
        eligibility.frame.to_parquet(self.root / "eligibility_matrix.parquet", index=False)
        self._atomic_json("registry_summary.json", {"concepts": len(bundle.concepts), "features": len(bundle.features),
                                                    "targets": len(bundle.targets), "unavailable": len(bundle.unavailable),
                                                    "required_warmup_sessions": bundle.required_warmup_sessions})
        return bundle

    def initial_audit(self) -> ExhaustivenessAudit:
        bundle = self.compile_registry(); eligibility = EligibilityMatrix.build(bundle.features, bundle.targets)
        expected_singles = int(eligibility.frame.active.sum())
        features_by_grid: dict[str, int] = {}
        for feature in bundle.features: features_by_grid[feature.decision_grid] = features_by_grid.get(feature.decision_grid, 0) + 1
        raw_pairs = sum(count * (count - 1) // 2 for count in features_by_grid.values())
        audit = ExhaustivenessAudit(len(bundle.concepts), len(bundle.features), len(bundle.features), len(bundle.unavailable),
            len(bundle.targets), expected_singles, 0, 0, 0, raw_pairs, {}, 0, 0, 0, 0, 0, 0,
            bool(self.config.duals["exhaustive_5x5_all_pairs"]))
        audit.write(self.root / "exhaustiveness_manifest.json")
        payload=json.loads((self.root/"exhaustiveness_manifest.json").read_text())
        payload.update(scope="declared_base_features_and_resolutions",resolutions=list(self.config.duals.get("resolutions",(3,5,10))),generated_expressions_count_as_tested=False)
        self._atomic_json("exhaustiveness_manifest.json",payload)
        return audit

    def build_report_shells(self) -> None:
        bundle = self.compile_registry()
        build_reports(self.root / "reports", {"run_name": self.config.run_name, "config_hash": self.config.definition_hash,
                      "compiled_concepts": len(bundle.concepts), "compiled_features": len(bundle.features),
                      "compiled_targets": len(bundle.targets), "required_warmup_sessions": bundle.required_warmup_sessions,
                      "research_state": ResearchState.BUILD_ONLY.value})

    def _atomic_json(self, relative: str, payload: dict) -> None:
        target = self.root / relative; target.parent.mkdir(parents=True, exist_ok=True); temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"); temporary.replace(target)
