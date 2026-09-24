# Quant Pipeline V3 Operation Manual

## Active run

The active canonical run is `v3_comprehensive_20260923` under `D:\AlgoResearch\Quant-Pipeline-V3\runs`. Its governed request is `configs\research\v3_comprehensive_20260923.yaml` and its machine profile is `configs\machines\local.yaml`.

The request covers the one-year discovery window from 2025-05-01 through 2026-04-30. Replication and final holdout access are sealed and disabled.

## Status and resume

Run commands from the repository root:

```powershell
.\.venv\Scripts\python -m quant_pipeline status --run-id v3_comprehensive_20260923 --machine configs\machines\local.yaml
.\.venv\Scripts\python -m quant_pipeline resume --run-id v3_comprehensive_20260923 --machine configs\machines\local.yaml
.\tools\watch-v3.ps1 -RunId v3_comprehensive_20260923
```

Before resuming, confirm there is no existing `quant_pipeline run` or `quant_pipeline resume` process for the same run ID. Do not launch two numerical owners.

## Cache policy

The active run uses shared `build-panel`, `build-features`, and `build-targets` caches under `D:\AlgoResearch\Quant-Pipeline-V3\cache\production_core`. Preserve these caches until the run completes. The active source snapshot is `D:\AlgoResearch\Quant-Pipeline-V3\cache\source\20240401_20260430`.

Feature and target reuse is valid only when the recorded source identity, panel identity, definitions, hashes, shapes, and columns match. The current run records its reuse evidence in `feature_reuse_manifest.json`, `target_reuse_manifest.json`, and stage checkpoints.

## Health check

Check all of the following:

1. The exact run process exists.
2. `STATUS.json` has no `last_error`.
3. `events.jsonl` or a stage checkpoint advances over time.
4. The current stderr tail has no new failure.
5. Available disk and memory remain above the configured reserves.

An unchanged status can be normal during a long feature calculation. Confirm CPU use or output activity before declaring a stall.

## Completion check

Completion requires all of the following:

1. `EVIDENCE_COMPLETE.json` exists.
2. `STATUS.json` reports successful completion.
3. Required stage checkpoints are complete.
4. Evidence counts reconcile with the published manifest.
5. Replication and final holdout access remain false unless separately authorized.

## Live project contents

Keep the live runtime limited to the active run, its logs, its active source snapshot, and reusable feature, target, and panel caches. Historical runs, test gates, temporary scripts, benchmark outputs, and release staging do not belong in the live runtime tree.
