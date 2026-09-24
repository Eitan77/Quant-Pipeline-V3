# Quant Pipeline V3

Clean-room quantitative discovery and evidence pipeline with point-in-time inputs, causal feature timing, sealed replication and final holdout periods, resumable stages, and shared core caches.

## Current canonical run

- Run ID: `v3_comprehensive_20260923`
- Request: `configs/research/v3_comprehensive_20260923.yaml`
- Machine: `configs/machines/local.yaml`
- Runtime root: `D:\AlgoResearch\Quant-Pipeline-V3`
- Discovery window: 2025-05-01 through 2026-04-30
- Replication and final holdout access remain disabled in the request.

The run reuses verified feature, target, and panel cache artifacts. Old run outputs, gate artifacts, temporary scripts, historical logs, and prior release bundles have been removed from the live project trees.

## Commands

```powershell
.\.venv\Scripts\python -m quant_pipeline status --run-id v3_comprehensive_20260923 --machine configs\machines\local.yaml
.\.venv\Scripts\python -m quant_pipeline resume --run-id v3_comprehensive_20260923 --machine configs\machines\local.yaml
.\tools\watch-v3.ps1 -RunId v3_comprehensive_20260923
```

Start a new run only with a new governed request and run name:

```powershell
.\.venv\Scripts\python -m quant_pipeline run --request configs\research\v3_comprehensive_20260923.yaml --machine configs\machines\local.yaml
```

## Completion

Treat a run as complete only when its `EVIDENCE_COMPLETE.json` exists and agrees with `STATUS.json`, stage checkpoints, and published evidence. A live process or a clean Git tree is not completion.

See [CODEX_OPERATION_MANUAL.md](docs/CODEX_OPERATION_MANUAL.md) for the compact operating procedure and [V3_MASTER_SPEC.md](V3_MASTER_SPEC.md) for the governing specification.
