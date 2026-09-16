# V3 implementation status

Built from `V3_MASTER_SPEC.md` and repaired against
`V3_PRODUCTION_REPAIR_SPEC.md`, with causal and sealed-data rules taking
priority. `V3ProductionRunner` owns every real-run post-scan decision. The
internal V2 port is limited to parity-sensitive PIT, panel, feature, target,
single, and fused canonical scan computation. Normal runtime does not import
or read the external V2 repository, caches, results, or checkpoints.

The external source is `D:/AlgoResearch/data`. V3 creates only its own derived
catalog/cache/run/scratch artifacts under `D:/AlgoResearch/Quant-Pipeline-V3`.
The source bridge filters at or before `2026-04-30`; normal discovery configs
cannot enable replication or final-holdout access.

Implemented contracts include the canonical CLI/DAG, split research/machine
configuration, immutable observation IDs, feature-pack loader, exact V2 tie/bin
semantics, exhaustive canonical pair planner without a singles gate, independent
r3/r5/r10 surfaces, direction-neutral selection, active-vs-weighted effects,
trial reconciliation, specialist/global-cancellation probes, executed and
trial-accounted hierarchical variant expansion,
candidate identity/lifecycle, episode/independent-opportunity counting,
cluster-aware diagnostics, interaction decomposition, complete frozen-rule
dossiers, cross-run content-addressed atomic artifacts, telemetry, bounded
resource recovery/stall diagnostics, compact Parquet/DuckDB bundles and SIP
signal export. Production dual results persist separate state return,
interaction lift, frequency, selected N, weighted contributions, direction,
and diagnostic inference fields at r3/r5/r10. Negative states are retained;
legacy statistical and synthetic-cost gates do not control V3 materialization.
Replication promotion requires an exact explicit authorization record and
preserves the frozen definition hash.

Validation artifacts:

- `V2_PARITY.json`: module hashes and focused copied-port tests.
- `BENCHMARKS.json`: cold/warm smoke, real external replay and GPU throughput.
- Generated run directories are intentionally absent from the clean project.
  The deterministic smoke and bounded real-data replay can be regenerated with
  the documented commands.

No full discovery-year workload was launched during production repair. The
machine-local config is ignored, the environment is locked, and the supplied
production-validation request exercises the same production path when the
user chooses to run it. Sealed replication cannot be evaluated without a later
explicit candidate-specific authorization, by design.
