# Quant Pipeline V3

Standalone implementation of `V3_MASTER_SPEC.md`. V3 reads the configured
external candle/source store without writing to it. All caches, runs, scratch,
manifests and analysis bundles are V3-owned.

```powershell
.\.venv\Scripts\python -m quant_pipeline run --request configs\research\smoke.yaml --machine configs\machines\local.yaml
.\.venv\Scripts\python -m quant_pipeline status --run-id smoke_v3 --machine configs\machines\local.yaml
.\.venv\Scripts\python -m quant_pipeline resume --run-id smoke_v3 --machine configs\machines\local.yaml
```

Bounded real-data replay:

```powershell
.\.venv\Scripts\python -m quant_pipeline run --request configs\research\external_smoke.yaml --machine configs\machines\local.yaml
```

Full discovery-year run:

```powershell
.\.venv\Scripts\python -m quant_pipeline run --request configs\research\v3_discovery.yaml --machine configs\machines\local.yaml
.\.venv\Scripts\python -m quant_pipeline status --run-id v3_discovery --machine configs\machines\local.yaml
.\.venv\Scripts\python -m quant_pipeline resume --run-id v3_discovery --machine configs\machines\local.yaml
```

Normal discovery cannot access the sealed replication period beginning
2026-05-01 or the final holdout beginning 2026-09-01.
