from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

JsonValue = str|int|float|bool|None|list["JsonValue"]|dict[str,"JsonValue"]
class RunMode(StrEnum): INCREMENTAL="incremental"; FULL_CANONICAL="full-canonical"
class TrialStatus(StrEnum): EXPECTED="expected"; EXECUTED="executed"; REUSED="reused"; STRUCTURALLY_EXCLUDED="structurally_excluded"; UNAVAILABLE="unavailable"; FAILED="failed"

@dataclass(frozen=True, slots=True)
class FeatureSpec:
    feature_id:str; concept_id:str; family:str; grid:str; canonical:bool
    required_inputs:tuple[str,...]; required_history_bars:int; availability_rule:str; price_basis:str
    parameters:Mapping[str,JsonValue]=field(default_factory=dict); dependencies:tuple[str,...]=()
    implementation_id:str=""; output_dtype:str="float32"; definition_hash:str=""

@dataclass(frozen=True, slots=True)
class TargetSpec:
    target_id:str; family:str; grid:str; horizon_minutes:int|None; return_basis:str
    entry_rule:str; exit_rule:str; same_day_requirement:bool; validity_rule:str
    benchmark_definition:str|None=None; residual_definition:str|None=None
    implementation_id:str=""; output_dtype:str="float32"; definition_hash:str=""

@dataclass(frozen=True, slots=True)
class ArtifactKey: artifact_type:str; semantic_id:str; content_hash:str; schema_version:int=1

@dataclass(frozen=True, slots=True)
class CandidateDefinition:
    candidate_id:str; feature_a_id:str; feature_b_id:str|None; target_id:str; grid:str; resolution:int
    state_payload:Mapping[str,JsonValue]; state_definition:str; direction:int; source_snapshot_hash:str
    selection_run_id:str; selection_trial_id:str; return_basis:str; definition_hash:str

@dataclass(frozen=True, slots=True)
class StageResult: stage_name:str; output_keys:tuple[ArtifactKey,...]; metrics:Mapping[str,JsonValue]; warnings:tuple[str,...]=()

@dataclass(frozen=True, slots=True)
class SurfaceStats:
    resolution:int; counts:Any; sums_bps:Any; means_bps:Any

