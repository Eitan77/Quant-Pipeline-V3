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

## Fused CUDA evidence

On the CUDA 12.1 host, install `pip install -e ".[fused-cuda121]"` and set
`evidence_fused_cuda: true` and `evidence_resident_inputs: true` in the machine
YAML. This accumulates counts and FP64 moments directly, retaining verified grid
inputs on the GPU across batches when accumulator headroom permits. Larger grids
fall back to fused streaming. The default remains the Torch path; task identities,
coverage scope, and resume checkpoints are shared by both paths.
When the complete grid has at most 12 distinct valid packed bin codes and the
state fits, one joint histogram supplies all three resolutions. The code verifies
the full alphabet and retains int64 counts and FP64 sums.

See [measured performance and validation](docs/EVIDENCE_PERFORMANCE.md).

## Completion

Treat a run as complete only when its `EVIDENCE_COMPLETE.json` exists and agrees with `STATUS.json`, stage checkpoints, and published evidence. A live process or a clean Git tree is not completion.

See [CODEX_OPERATION_MANUAL.md](docs/CODEX_OPERATION_MANUAL.md) for the compact operating procedure and [V3_MASTER_SPEC.md](V3_MASTER_SPEC.md) for the governing specification.
