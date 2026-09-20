from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json

import duckdb
import pandas as pd
import yaml


RUN_ID = "v3_discovery_zoom_explicit_20260920"
SOURCE_RUN = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_discovery")
OUTPUT_CONFIG = Path("configs/research") / f"{RUN_ID}.yaml"
OUTPUT_TABLE = Path("configs/research") / f"{RUN_ID}.resolved_requests.parquet"
OUTPUT_JSON = OUTPUT_TABLE.with_suffix(".json")
GRID = "intraday_5m"


def feature(concept: str, window: str, representation: str = "raw") -> str:
    return f"{concept}__{window}__{representation}__{GRID}"


def target(horizon: str, basis: str) -> str:
    return f"target_{horizon.lower()}__{basis}__{GRID}"


def main() -> None:
    bundle = SOURCE_RUN / "analysis_bundle"
    con = duckdb.connect(str(bundle / "research.duckdb"), read_only=True)
    feature_rows = con.execute(
        "SELECT feature_id, concept_id, representation, decision_grid FROM feature_registry"
    ).fetchdf()
    target_rows = con.execute("SELECT target_id FROM target_registry").fetchdf()
    feature_ids = set(feature_rows.feature_id)
    target_ids = set(target_rows.target_id)
    concept_by_feature = dict(zip(feature_rows.feature_id, feature_rows.concept_id))

    raw: list[dict] = []

    def add(
        family: str,
        left: list[str],
        right: list[str],
        horizons: list[str],
        *,
        bases: tuple[str, ...] = ("benchmark_adjusted", "beta_residual"),
        role: str = "requested_exact",
    ) -> None:
        for a in left:
            for b in right:
                for horizon in horizons:
                    for basis in bases:
                        raw.append(
                            {
                                "request_kind": "variant_surface",
                                "family": family,
                                "role": role,
                                "requested_feature_a": a,
                                "requested_feature_b": b,
                                "target_id": target(horizon, basis),
                            }
                        )

    def fs(concept: str, windows: list[str], representation: str = "raw") -> list[str]:
        return [feature(concept, window, representation) for window in windows]

    w5 = ["15m", "30m", "60m", "120m", "240m"]
    w4 = ["30m", "60m", "120m", "240m"]
    session5 = ["30m", "60m", "120m", "240m", "session"]

    add("A1", fs("ema_distance", w5), fs("fast_slow_ema_gap", w5), ["120m", "240m"])
    add("A2", fs("ema_distance", w5), fs("range_position", session5), ["60m", "120m", "240m"])
    add("A3", fs("ema_distance", w5), fs("market_correlation", w5), ["60m", "120m", "240m"])
    add("A4", fs("ema_distance", w5), fs("ema_slope", w5), ["60m", "120m", "240m"])
    add("A5", fs("distance_from_low", session5), fs("ema_distance", w5), ["120m", "240m"])
    add("A6", fs("close_vs_vwap", w5), fs("ema_distance", w5), ["60m", "120m", "240m"])
    add(
        "A7",
        fs("down_up_vol_ratio", w5) + fs("down_up_vol_ratio", ["30m", "60m", "120m"], "own_history_percentile"),
        fs("ema_distance", w5),
        ["120m", "240m"],
    )
    add("A8", fs("semivariance_ratio", w4), fs("ema_distance", w5), ["120m", "240m"])
    add("A9", fs("ema_distance", w5), fs("vwap_drift", w5), ["60m", "120m", "240m"])
    add("A10", fs("ema_distance", w5), fs("window_max_drawdown", session5), ["120m", "240m"])
    add("A11", fs("ema_distance", w5), fs("money_flow_proxy", w5), ["120m", "240m"])
    add("A12", fs("ema_distance", w5), fs("price_to_sma", w5), ["60m", "120m", "240m"])
    add("A13", fs("ema_distance", w5), fs("market_gap", w5), ["30m", "60m", "120m", "240m"])
    add("A14", fs("bars_or_days_since_high", session5), fs("ema_distance", w5), ["60m", "120m"])

    add(
        "B1",
        fs("atr_pct", w5) + fs("atr_pct", ["30m", "60m", "120m"], "own_history_percentile"),
        fs("fast_slow_ema_gap", w5),
        ["240m"],
    )
    add(
        "B2",
        fs("benchmark_excess_return", ["15m", "30m", "60m", "120m"])
        + fs("benchmark_excess_return", ["30m", "60m", "120m"], "own_history_percentile"),
        fs("prior_low_reclaim_strength", w4),
        ["120m"],
    )
    add("B3", fs("breakout_distance", w4), fs("market_correlation", w5), ["120m"])
    add("B4", fs("market_correlation", w5), fs("prior_high_reclaim_strength", w4), ["120m"])
    add("B5", fs("breakout_distance", w4), fs("upside_beta", w4), ["120m"])
    add("B6", fs("prior_high_reclaim_strength", w4), fs("upside_beta", w4), ["120m"])
    add("B7", fs("failed_breakdown_strength", w4), fs("return_acceleration_thirds", w4), ["240m"])
    add("B8", fs("corwin_schultz_spread_proxy", w4), fs("failed_breakout_strength", w4), ["eod"])
    add("B9", fs("corwin_schultz_spread_proxy", w4), fs("min_subreturn", w4), ["eod"])

    jump = fs("positive_jump_fraction", w4)
    add("C1", jump, fs("fast_slow_ema_gap", ["15m", "30m", "60m", "120m"]), ["120m", "240m"])
    add("C2", jump, fs("trend_slope", w4), ["120m"])
    add("C3", jump, fs("fast_slow_sma_gap", ["15m", "30m", "60m", "120m"]), ["120m"])
    add("C4", jump, fs("close_vs_vwap", ["15m", "30m", "60m", "120m"]), ["120m"])
    add("C5", jump, fs("atr_band_z", ["15m", "30m", "60m", "120m"]), ["120m"])
    add("C6", jump, fs("ema_slope", ["15m", "30m", "60m", "120m"]), ["120m"])
    add("C7", jump, fs("close_vs_path_median", w4), ["120m"])
    add("C8", jump, fs("failed_breakout_strength", ["30m", "60m", "120m"]), ["30m"])
    add("C9", jump, fs("average_signed_run_length", ["30m", "60m", "120m"]), ["30m"])
    add(
        "C10",
        jump,
        fs("atr_pct", ["15m", "30m", "60m", "120m"])
        + fs("atr_pct", ["30m", "60m"], "own_history_percentile"),
        ["30m"],
    )
    add("C11", jump, fs("variance_ratio_2", ["60m", "120m", "240m"]), ["30m"])
    add("C12", jump, fs("return_entropy", ["60m", "120m", "240m"]), ["15m"])
    add("C13", jump, fs("same_bucket_return_mean10", ["5m", "30m"]), ["15m"])
    add("C14", jump, fs("new_low_count", w4), ["60m"])
    add(
        "C_canonical_comparisons",
        jump,
        [feature("log_return", "30m"), feature("benchmark_excess_return", "30m")],
        ["120m"],
        role="retained_canonical_comparison",
    )

    negative = fs("negative_jump_fraction", w4)
    add("D1", negative, fs("lower_wick_fraction", ["15m", "30m", "60m", "120m"]), ["120m"])
    add(
        "D_volatility_confirmations",
        negative,
        fs("rogers_satchell_vol", ["15m", "30m", "60m", "120m"])
        + fs("rogers_satchell_vol", ["30m", "60m", "120m"], "own_history_percentile"),
        ["120m"],
        role="correlated_confirmation_rogers_satchell",
    )
    add("D3", negative, fs("roll_spread_proxy", w4), ["120m"])
    add("D4", negative, fs("bars_or_days_since_low", session5), ["120m"])
    add(
        "D_volatility_confirmations",
        negative,
        fs("garman_klass_vol", ["15m", "30m", "60m", "120m"])
        + fs("garman_klass_vol", ["30m", "60m", "120m"], "own_history_percentile"),
        ["120m"],
        role="correlated_confirmation_garman_klass",
    )

    for position, row in enumerate(raw):
        row["request_position"] = position
        missing = []
        if row["requested_feature_a"] not in feature_ids:
            missing.append(row["requested_feature_a"])
        if row["requested_feature_b"] not in feature_ids:
            missing.append(row["requested_feature_b"])
        if row["target_id"] not in target_ids:
            missing.append(row["target_id"])
        row["preflight_status"] = "available" if not missing else "unavailable"
        row["unavailable_reason"] = None if not missing else "missing_registry_definition: " + ", ".join(missing)
        if not missing:
            row["feature_a"], row["feature_b"] = sorted((row["requested_feature_a"], row["requested_feature_b"]))
            row["concept_a"] = concept_by_feature[row["feature_a"]]
            row["concept_b"] = concept_by_feature[row["feature_b"]]

    available = pd.DataFrame([x for x in raw if x["preflight_status"] == "available"])
    unique_keys = available[["feature_a", "feature_b", "target_id"]].drop_duplicates()
    con.register("requested_keys", unique_keys)
    canonical = con.execute(
        """
        SELECT DISTINCT d.feature_a,d.feature_b,d.target_id,d.pair_id
        FROM read_parquet(?) d
        JOIN requested_keys r USING(feature_a,feature_b,target_id)
        WHERE d.v3_resolution=3
        """,
        [str(SOURCE_RUN / "v3_diagnostics" / "dual_resolution_summary.parquet")],
    ).fetchdf()
    canonical_keys = set(zip(canonical.feature_a, canonical.feature_b, canonical.target_id))

    concept_targets = available[["concept_a", "concept_b", "target_id"]].drop_duplicates()
    con.register("concept_targets", concept_targets)
    anchors = con.execute(
        """
        SELECT DISTINCT d.feature_a,d.feature_b,d.target_id,d.pair_id,
               fa.concept_id concept_a,fb.concept_id concept_b
        FROM read_parquet(?) d
        JOIN read_parquet(?) fa ON fa.feature_id=d.feature_a
        JOIN read_parquet(?) fb ON fb.feature_id=d.feature_b
        JOIN concept_targets c ON c.concept_a=fa.concept_id AND c.concept_b=fb.concept_id AND c.target_id=d.target_id
        WHERE d.v3_resolution=3
        """,
        [
            str(SOURCE_RUN / "v3_diagnostics" / "dual_resolution_summary.parquet"),
            str(bundle / "feature_registry.parquet"),
            str(bundle / "feature_registry.parquet"),
        ],
    ).fetchdf()
    anchor_map: dict[tuple[str, str, str], tuple[str, str]] = {}
    if len(anchors):
        anchors["preference"] = anchors.feature_a.str.contains("__30m__raw__").astype(int) + anchors.feature_b.str.contains("__30m__raw__").astype(int)
        anchors = anchors.sort_values(["preference", "feature_a", "feature_b"], ascending=[False, True, True], kind="stable")
        for row in anchors.to_dict("records"):
            anchor_map.setdefault((row["concept_a"], row["concept_b"], row["target_id"]), (row["feature_a"], row["feature_b"]))

    grouped: dict[tuple[str, str, str], dict] = {}
    for row in raw:
        if row["preflight_status"] != "available":
            continue
        key = (row["feature_a"], row["feature_b"], row["target_id"])
        entry = grouped.setdefault(
            key,
            {
                "feature_a": row["feature_a"],
                "feature_b": row["feature_b"],
                "target_id": row["target_id"],
                "families": set(),
                "roles": set(),
                "request_positions": [],
            },
        )
        entry["families"].add(row["family"])
        entry["roles"].add(row["role"])
        entry["request_positions"].append(row["request_position"])

    explicit_requests = []
    for key, entry in grouped.items():
        a, b, target_id = key
        is_canonical = key in canonical_keys
        source_a, source_b = (a, b) if is_canonical else anchor_map.get(
            (concept_by_feature[a], concept_by_feature[b], target_id), (a, b)
        )
        explicit_requests.append(
            {
                "source_feature_a": source_a,
                "source_feature_b": source_b,
                "feature_a": a,
                "feature_b": b,
                "target_id": target_id,
                "family": "|".join(sorted(entry["families"])),
                "role": "|".join(sorted(entry["roles"])),
            }
        )

    guaranteed = [
        ("E1", "variance_ratio_5__60m__raw__intraday_5m", "vwap_drift__30m__raw__intraday_5m", "target_240m__benchmark_adjusted__intraday_5m", 10, 70, "explicit", "descriptive"),
        ("E2", "average_trade_size__30m__raw__intraday_5m", "market_correlation__30m__raw__intraday_5m", "target_240m__benchmark_adjusted__intraday_5m", 5, 9, "explicit", "descriptive"),
        ("E3", "realized_kurtosis__30m__raw__intraday_5m", "volume_volatility__30m__raw__intraday_5m", "target_240m__benchmark_adjusted__intraday_5m", 5, 20, "explicit", "descriptive"),
        ("E4", "positive_bar_fraction__30m__raw__intraday_5m", "upside_semivariance__30m__raw__intraday_5m", "target_240m__beta_residual__intraday_5m", 5, 9, "explicit", "descriptive"),
        ("E5", "market_beta__30m__raw__intraday_5m", "stock_lead_market_response__30m__raw__intraday_5m", "target_240m__beta_residual__intraday_5m", 10, 69, "explicit", "descriptive"),
        ("E6", "raw_volume__30m__raw__intraday_5m", "return_autocorr_lag1__60m__raw__intraday_5m", "target_120m__beta_residual__intraday_5m", 5, 15, "explicit", "descriptive"),
        ("E7", "benchmark_excess_return__30m__raw__intraday_5m", "same_bucket_return_lag1__30m__raw__intraday_5m", "target_240m__beta_residual__intraday_5m", 10, 97, "explicit", "descriptive"),
        ("E8", "market_vol_percentile__30m__raw__intraday_5m", "sma_acceleration__30m__raw__intraday_5m", "target_240m__benchmark_adjusted__intraday_5m", 10, 30, "explicit", "descriptive"),
        ("E9", "atr_pct__30m__raw__intraday_5m", "top3_abs_return_share__30m__raw__intraday_5m", "target_240m__benchmark_adjusted__intraday_5m", 3, 8, "explicit", "descriptive"),
        ("E10", "momentum_sign_agreement__5m_30m__raw__intraday_5m", "positive_bar_fraction__30m__raw__intraday_5m", "target_240m__beta_residual__intraday_5m", 10, 20, "explicit", "descriptive"),
        ("F1", "jump_variance_share__30m__raw__intraday_5m", "prior_low_reclaim_strength__30m__raw__intraday_5m", "target_60m__benchmark_adjusted__intraday_5m", 10, 22, "explicit", "auto"),
        ("F1", "jump_variance_share__30m__raw__intraday_5m", "prior_low_reclaim_strength__30m__raw__intraday_5m", "target_60m__benchmark_adjusted__intraday_5m", 10, None, "scanner_selected", "auto"),
        ("F2", "breakdown_distance__30m__raw__intraday_5m", "p95_subreturn__30m__raw__intraday_5m", "target_60m__benchmark_adjusted__intraday_5m", 10, 70, "explicit", "auto"),
        ("F2", "breakdown_distance__30m__raw__intraday_5m", "p95_subreturn__30m__raw__intraday_5m", "target_60m__benchmark_adjusted__intraday_5m", 10, None, "scanner_selected", "auto"),
    ]
    guaranteed_keys = pd.DataFrame(
        [
            {"feature_a": min(a, b), "feature_b": max(a, b), "target_id": target_id}
            for _, a, b, target_id, *_ in guaranteed
        ]
    ).drop_duplicates()
    con.register("guaranteed_keys", guaranteed_keys)
    guaranteed_canonical = con.execute(
        """
        SELECT DISTINCT d.feature_a,d.feature_b,d.target_id
        FROM read_parquet(?) d
        JOIN guaranteed_keys g USING(feature_a,feature_b,target_id)
        WHERE d.v3_resolution=3
        """,
        [str(SOURCE_RUN / "v3_diagnostics" / "dual_resolution_summary.parquet")],
    ).fetchdf()
    guaranteed_canonical_keys = set(
        zip(guaranteed_canonical.feature_a, guaranteed_canonical.feature_b, guaranteed_canonical.target_id)
    )
    explicit_candidates = []
    for family, a0, b0, target_id, resolution, cell, cell_mode, direction_mode in guaranteed:
        a, b = sorted((a0, b0))
        missing = [x for x in (a, b) if x not in feature_ids]
        if target_id not in target_ids:
            missing.append(target_id)
        surface_exists = (a, b, target_id) in guaranteed_canonical_keys
        status = "available" if not missing and surface_exists else "unavailable"
        reason = None if status == "available" else (
            "missing_registry_definition: " + ", ".join(missing)
            if missing
            else "canonical_surface_unavailable"
        )
        raw.append(
            {
                "request_kind": "guaranteed_dossier",
                "family": family,
                "role": "requested_explicit_cell" if cell_mode == "explicit" else "scanner_selected_comparator",
                "requested_feature_a": a0,
                "requested_feature_b": b0,
                "feature_a": a,
                "feature_b": b,
                "target_id": target_id,
                "resolution": resolution,
                "cell_mode": cell_mode,
                "cell_index": cell,
                "direction_mode": direction_mode,
                "preflight_status": status,
                "unavailable_reason": reason,
                "request_position": len(raw),
            }
        )
        if status == "available":
            item = {
                "feature_a": a,
                "feature_b": b,
                "target_id": target_id,
                "resolution": resolution,
                "cell_mode": cell_mode,
                "direction_mode": direction_mode,
                "family": family,
                "role": "requested_explicit_cell" if cell_mode == "explicit" else "scanner_selected_comparator",
            }
            if cell_mode == "explicit":
                item["cell_index"] = cell
            explicit_candidates.append(item)

    config = yaml.safe_load(Path("configs/research/v3_discovery.yaml").read_text(encoding="utf-8"))
    config["run_name"] = RUN_ID
    config["variant_expansion"] = {
        "mode": "explicit",
        "parent_limit": None,
        "neighbors_per_side": 3,
        "rejected_audit_count": 0,
        "explicit_requests": explicit_requests,
    }
    config["forensics"]["explicit_candidates"] = explicit_candidates
    config["forensics"]["dossier_selection"] = {
        "enabled": True,
        "pre_specialist_per_family": 8,
        "max_dynamic_dossiers": 70,
    }
    config["zoom"] = {"enabled": True, "selection_mode": "explicit_plus_rules"}

    table = pd.DataFrame(raw)
    available_keys = set(grouped)
    if len(table):
        table["canonical_existing"] = [
            (row.get("feature_a"), row.get("feature_b"), row.get("target_id")) in canonical_keys
            if row.get("preflight_status") == "available"
            else False
            for row in table.to_dict("records")
        ]
        table["unique_exact_request"] = [
            (row.get("feature_a"), row.get("feature_b"), row.get("target_id")) in available_keys
            if row.get("request_kind") == "variant_surface"
            else True
            for row in table.to_dict("records")
        ]

    OUTPUT_CONFIG.write_text(yaml.safe_dump(config, sort_keys=False, width=100000), encoding="utf-8")
    table.to_parquet(OUTPUT_TABLE, index=False)
    OUTPUT_JSON.write_text(json.dumps(table.to_dict("records"), indent=2, default=str), encoding="utf-8")
    summary = {
        "run_id": RUN_ID,
        "raw_variant_requests": sum(x["request_kind"] == "variant_surface" for x in raw),
        "unique_variant_pair_targets": len(explicit_requests),
        "canonical_reuse_pair_targets": sum((x["feature_a"], x["feature_b"], x["target_id"]) in canonical_keys for x in explicit_requests),
        "noncanonical_pair_targets": sum((x["feature_a"], x["feature_b"], x["target_id"]) not in canonical_keys for x in explicit_requests),
        "guaranteed_dossier_requests": len(guaranteed),
        "unavailable_rows": int((table.preflight_status == "unavailable").sum()),
        "config": str(OUTPUT_CONFIG.resolve()),
        "resolved_table": str(OUTPUT_TABLE.resolve()),
    }
    print(json.dumps(summary, indent=2))
    con.close()


if __name__ == "__main__":
    main()
