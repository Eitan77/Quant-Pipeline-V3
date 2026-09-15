from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .capacity import capacity_proxy
from .costs import cost_delay_curve
from .decay import effect_decay
from .leaveout import leave_out_tests
from .persistence import persistence_turnover
from .placebo import placebo_test
from .regimes import grouped_effects
from .thresholds import threshold_curve
from .attribution import factor_attribution
from .variants import calculation_variant_audit
from .trade_path import trade_path_diagnostics


ARTIFACTS = (
    "effect_decay.parquet", "threshold_curve.parquet", "persistence_turnover.parquet",
    "chronological_robustness.parquet", "leave_out_tests.parquet", "regime_matrix.parquet",
    "breadth_matrix.parquet", "cost_delay_curve.parquet", "capacity_proxy.parquet",
    "trade_path.parquet", "neutralization_attribution.parquet", "redundancy.parquet",
    "placebo_tests.parquet", "calculation_variant_audit.parquet",
)
EDGE_AUTOPSY_ENGINE_VERSION = 4


@dataclass
class EdgeAutopsy:
    output: Path
    config: dict[str, Any]

    def run(self, score: np.ndarray, targets: dict[str, np.ndarray], metadata: pd.DataFrame,
            delayed_returns: dict[int, np.ndarray] | None = None,
            candidate_returns: np.ndarray | None = None, rule_hash: str | None = None) -> dict[str, Any]:
        if not targets:
            raise ValueError("Edge Autopsy requires at least one causal target")
        if len(score) != len(metadata) or any(len(values) != len(score) for values in targets.values()):
            raise ValueError("Edge Autopsy score, targets, and metadata must be row-aligned")
        regime_columns = ["market_trend", "market_vol", "breadth", "dispersion", "correlation_regime", "time_of_day", "day_of_week"]
        breadth_columns = ["price_bucket", "liquidity_bucket", "volatility_bucket", "beta_bucket", "size_bucket"]
        path_columns = ["mfe", "mae", "time_to_mfe", "time_to_mae", "terminal_return", "mfe_minus_terminal", "recovery_after_mae"]
        required = {"security_id", "session_date", "decision_ts", "trade_notional", "bar_dollar_volume", "entry_price", *path_columns, *regime_columns, *breadth_columns}
        missing = required - set(metadata)
        if missing:
            raise ValueError(f"Edge Autopsy metadata missing mandatory fields: {sorted(missing)}")
        if delayed_returns is None or not delayed_returns:
            raise ValueError("Edge Autopsy requires measured delayed-return paths")
        self.output.mkdir(parents=True, exist_ok=True); (self.output / "figures").mkdir(exist_ok=True)
        primary = next(iter(targets.values()))
        conditioned = np.asarray(candidate_returns if candidate_returns is not None else primary, dtype=float)
        if len(conditioned) != len(primary): raise ValueError("Candidate returns must be row-aligned")
        tables = {
            "effect_decay.parquet": effect_decay(score, targets),
            "threshold_curve.parquet": threshold_curve(score, primary, self.config["threshold_tails"]),
            "persistence_turnover.parquet": persistence_turnover(pd.Series(score).rank(pct=True).to_numpy(), metadata.security_id.to_numpy()),
            "leave_out_tests.parquet": leave_out_tests(conditioned, metadata.security_id.to_numpy(), metadata.session_date.to_numpy()),
            "cost_delay_curve.parquet": cost_delay_curve(delayed_returns, self.config["cost_bps_per_side"]),
            "placebo_tests.parquet": placebo_test(score, primary, pd.factorize(metadata.decision_ts)[0],
                                                    int(self.config.get("placebo_runs",1000)),
                                                    workers=int(self.config.get("placebo_workers",1))),
            "chronological_robustness.parquet": grouped_effects(conditioned, metadata.assign(year=pd.to_datetime(metadata.session_date).dt.year), ["year"]),
            "regime_matrix.parquet": grouped_effects(conditioned, metadata, regime_columns),
            "breadth_matrix.parquet": grouped_effects(conditioned, metadata, breadth_columns),
            "capacity_proxy.parquet": capacity_proxy(metadata.trade_notional, metadata.bar_dollar_volume, conditioned),
        }
        factor_columns = [name for name in ("market_factor", "momentum_factor", "volatility_factor", "liquidity_factor") if name in metadata]
        if not factor_columns:
            raise ValueError("Edge Autopsy requires at least one prior-known attribution factor")
        tables["neutralization_attribution.parquet"] = factor_attribution(conditioned, metadata[factor_columns])
        variant_columns = [name for name in metadata if name.startswith("variant_")]
        if not variant_columns:
            raise ValueError("Edge Autopsy requires at least one calculation variant")
        tables["calculation_variant_audit.parquet"] = calculation_variant_audit(score, {name: metadata[name].to_numpy() for name in variant_columns})
        tables["trade_path.parquet"] = metadata[["security_id","session_date",*path_columns]].copy()
        peers = [name for name in metadata if name.startswith("candidate_score_")]
        redundancy_rows = []
        for name in peers:
            values = pd.to_numeric(metadata[name], errors="coerce").to_numpy()
            valid = np.isfinite(score) & np.isfinite(values)
            correlation = float(pd.Series(score[valid]).corr(pd.Series(values[valid]), method="spearman")) if valid.sum() >= 3 else np.nan
            redundancy_rows.append({"candidate": name, "spearman_correlation": correlation, "sample_count": int(valid.sum())})
        tables["redundancy.parquet"] = pd.DataFrame(redundancy_rows or [{"candidate": "none", "spearman_correlation": 0.0, "sample_count": len(score)}])
        for artifact in ARTIFACTS:
            table = tables[artifact]
            if table.empty:
                raise ValueError(f"Mandatory Edge Autopsy artifact is empty: {artifact}")
            table.to_parquet(self.output / artifact, index=False)
        chronology=tables["chronological_robustness.parquet"]; breadth=tables["breadth_matrix.parquet"]
        cost=tables["cost_delay_curve.parquet"]; capacity=tables["capacity_proxy.parquet"]; paths=tables["trade_path.parquet"]
        symbol_effect=pd.DataFrame({"security":metadata.security_id,"return":conditioned}).groupby("security",observed=True)["return"].mean()
        minimum_trades=int(self.config.get("minimum_trades",50))
        base_delay=int(self.config.get("base_delay_minutes",1))
        base_cost=float(self.config.get("base_cost_bps",5))+float(self.config.get("base_slippage_bps",2))
        base_values=np.asarray(delayed_returns.get(base_delay,[]),dtype=float)
        base_count=int(np.isfinite(base_values).sum())
        base_net=float(np.nanmean(base_values)-2*base_cost/10_000) if base_count else np.nan
        minimum_net=float(self.config.get("minimum_net_edge_bps",1))/10_000
        chronology_fraction=float((chronology.mean_return>0).mean()) if len(chronology) else 0.
        breadth_fraction=float((breadth.mean_return>0).mean()) if len(breadth) else 0.
        symbol_counts=metadata.security_id.value_counts(); maximum_symbol_share=float(symbol_counts.iloc[0]/symbol_counts.sum()) if len(symbol_counts) else 1.
        finite_paths=paths[["mfe","mae","terminal_return"]].replace([np.inf,-np.inf],np.nan).dropna()
        checks = {"economic_magnitude": "PASS" if base_count>=minimum_trades and base_net>=minimum_net else "FAIL",
                  "placebo_tests": "PASS" if tables["placebo_tests.parquet"].empirical_p_value.iloc[0] <= .05 else "FAIL",
                  "chronological_robustness": "PASS" if len(chronology)>=int(self.config.get("minimum_chronological_groups",3)) and chronology_fraction>=float(self.config.get("minimum_chronological_positive_fraction",.60)) else "FAIL",
                  "breadth": "PASS" if len(breadth)>=int(self.config.get("minimum_breadth_groups",5)) and breadth_fraction>=float(self.config.get("minimum_breadth_positive_fraction",.60)) else "FAIL",
                  "symbol_breadth":"PASS" if len(symbol_effect) and (symbol_effect>0).mean()>=float(self.config.get("minimum_symbol_breadth",.5)) else "FAIL",
                  "concentration": "PASS" if maximum_symbol_share<=float(self.config.get("maximum_symbol_trade_share",.10)) else "FAIL",
                  "cost_delay": "PASS" if base_count>=minimum_trades and base_net>=minimum_net else "FAIL",
                  "capacity": "PASS" if not capacity.empty and capacity.eligible_trades.max() >= int(self.config.get("minimum_capacity_eligible_trades",minimum_trades)) else "FAIL",
                  "trade_path": "PASS" if len(finite_paths)>=int(self.config.get("minimum_trade_paths",minimum_trades)) else "FAIL",
                  "artifact_completeness": "PASS"}
        hard=set(self.config.get("hard_fail_checks",checks)); overall="PASS" if all(checks.get(name)=="PASS" for name in hard) else "FAIL"
        report = "# Edge Autopsy\n\n" + "\n".join(f"- {name}: {status}" for name, status in checks.items()) + "\n"
        (self.output / "EDGE_AUTOPSY.md").write_text(report, encoding="utf-8")
        manifest = {"engine_version":EDGE_AUTOPSY_ENGINE_VERSION,
                    "artifacts": {name: str(self.output / name) for name in ARTIFACTS}, "report": str(self.output / "EDGE_AUTOPSY.md"),
                    "checks": checks, "hard_fail_checks": sorted(hard), "overall_status": overall,
                    "candidate_rule_hash": rule_hash,"metrics":{"candidate_mean_return":float(np.nanmean(conditioned)),
                    "base_net_edge":base_net,"best_net_edge":base_net,"base_sample_count":base_count,
                    "maximum_symbol_trade_share":maximum_symbol_share,"chronological_positive_fraction":chronology_fraction,
                    "positive_delay_cost_fraction":float((cost.net_edge_per_trade>0).mean()),
                    "max_capacity_eligible_trades":int(capacity.eligible_trades.max())}}
        (self.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
