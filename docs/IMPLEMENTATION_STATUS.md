# V3 implementation status

Built from `V3_MASTER_SPEC.md` with the causal/sealed-data rules taking
priority. The production implementation includes a byte-parity internal port
of V2's data, identity, adjustment, feature, target, binning, CUDA scan,
inference, resume, forensics and execution-export modules. Normal V3 runtime
does not import or read V2 code, caches, results or checkpoints.

The external source is `D:/AlgoResearch/data`. V3 creates only its own derived
catalog/cache/run/scratch artifacts under `D:/AlgoResearch/Quant-Pipeline-V3`.
The source bridge filters at or before `2026-04-30`; normal discovery configs
cannot enable replication or final-holdout access.

Implemented contracts include the canonical CLI/DAG, split research/machine
configuration, immutable observation IDs, feature-pack loader, exact V2 tie/bin
semantics, exhaustive canonical pair planner without a singles gate, independent
r3/r5/r10 surfaces, direction-neutral selection, active-vs-weighted effects,
trial reconciliation, specialist probe, hierarchical variant request planning,
candidate identity/lifecycle, episode/independent-opportunity counting,
cluster-aware diagnostics, interaction decomposition, content-addressed atomic
artifacts, telemetry, compact Parquet/DuckDB bundles and SIP signal export.

Validation artifacts:

- `V2_PARITY.json`: module hashes and focused copied-port tests.
- `BENCHMARKS.json`: cold/warm smoke, real external replay and GPU throughput.
- `D:/AlgoResearch/Quant-Pipeline-V3/runs/smoke_v3`: deterministic end-to-end run.
- `D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_external_smoke`: bounded real-data
  V2 replay with CUDA and reconciled trial coverage.

The full one-year canonical run is intentionally not executed as a build test;
it is the long research workload started by the documented `v3_discovery.yaml`
command after the bounded smoke/parity gates are green.

