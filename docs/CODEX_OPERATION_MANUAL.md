# Quant Pipeline V3 — Codex Operation Manual

## Purpose

This document is the operating manual for a Codex agent working inside the **Quant Pipeline V3** repository.

It is intentionally written as an agent runbook rather than a human-facing architecture overview. Follow it when you are asked to:

- validate or run the pipeline;
- monitor or resume a run;
- inspect completed research;
- answer a GPT request using the analysis bundle;
- investigate a candidate more deeply;
- scan neighboring feature variants;
- run focused tail, horizon, specialist, or temporal analysis;
- run a focused execution/backtest experiment;
- export candidate signals for downstream SIP work;
- prepare a candidate for later sealed replication;
- add new research without contaminating the canonical discovery run.

The repository code is authoritative. If this manual and the current code disagree, **inspect the current code before acting and follow the current causal/sealed-data invariants**.

---

# 1. Agent operating contract

## 1.1 Always do these things

1. **Work from the repository root.**
2. **Read the active research config and machine config before running anything.**
3. **Treat the external market-data store as read-only.**
4. **Keep research semantics separate from machine/hardware settings.**
5. **Use a new `run_name` whenever research semantics change.**
6. **Prefer existing pipeline primitives over rewriting research logic in one-off scripts.**
7. **Use the analysis bundle first when the requested answer already exists in generated evidence.**
8. **Preserve negative effects, interaction-only findings, and all r3/r5/r10 evidence.**
9. **Keep discovery evidence clearly labeled as discovery evidence.**
10. **Write ad-hoc follow-up outputs to a derived-analysis directory instead of overwriting canonical artifacts.**
11. **Record exactly what a focused follow-up tested: candidate/pair, target, resolution, state, assumptions, source run, and code/config identity.**
12. **Report failures and incomplete evidence instead of silently skipping work.**
13. **Distinguish a diagnostic slice from a changed strategy rule.** A symbol whitelist, time-of-day filter, regime filter, tighter tail/threshold, new horizon, logical combination, or altered state boundary may be analyzed on discovery data as derived evidence; if it is adopted as the rule to trade or validate OOS, it must receive a new governed identity before sealed evaluation.
14. **Make derived tasks idempotent.** Store a request/manifest with the task. If `derived/<task_id>/` already exists, reuse it only when its saved request hash/specification matches exactly; otherwise choose a new task ID. Never silently overwrite a previous derived experiment with different assumptions.

## 1.2 Never do these things

- Never write into `data_root`.
- Never hand-edit `research.duckdb` and treat that edit as research truth.
- Never alter an existing frozen candidate definition in place.
- Never silently replace a candidate's target, state, resolution, return basis, direction, or feature definitions.
- Never use singles as a gate for whether canonical duals are allowed to exist.
- Never collapse r3/r5/r10 into one “best” resolution during discovery.
- Never discard a result only because its edge is negative.
- Never describe discovery-year folds, months, cross-fit results, tails, or backtests as sealed OOS evidence.
- Never open replication or final-holdout data merely because GPT asks to “check if it works.”
- Never claim `replicate` evaluated the replication period. In the current V3 CLI, it promotes an explicitly authorized frozen candidate into a **replication request**; it does not perform the sealed evaluation itself.
- Never run a zero-direction `interaction_only` candidate as a long/short execution strategy until a directional rule is explicitly defined and frozen as a new candidate.
- Never use a benchmark-adjusted or beta-residual target as though its stored target return were directly executable P&L. Execution research must reconstruct explicit stock and hedge legs.

---

# 2. Know the current production boundary

For real data, `python -m quant_pipeline run ...` enters `V3ProductionRunner`.

The embedded V2-derived code is a **numerical/parity core**. Its production role is limited to the low-level stages used by `LegacyCoreAdapter`:

```text
validate-config
snapshot
build-panel
compile-registry
build-features
build-targets
scan-singles
scan-duals-coarse
scan-duals-fine
exact-duals
audit-exhaustiveness
```

V3 owns the post-scan production logic:

- r3/r5/r10 resolution consolidation;
- exhaustive cell specialist diagnostics;
- exhaustive cell temporal diagnostics;
- trial reconciliation;
- analysis-bundle construction;
- optional specialist zoom;
- hierarchical variant expansion;
- candidate materialization/freezing;
- dossiers;
- candidate lifecycle;
- SIP export;
- shared-cache/checkpoint behavior.

Do **not** invoke old V2-style stability/autopsy/promotion stages as a substitute for the V3 production runner unless the task is specifically to engineer or test those legacy modules.

---

# 3. Environment setup

The validated environment is Windows, Python 3.12, PyTorch/CUDA, and an NVIDIA RTX 3080 Ti-class machine.

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
```

Quick environment check:

```powershell
.\.venv\Scripts\python -c "import torch,duckdb,pandas,pyarrow; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'); print(duckdb.__version__)"
```

Also check the GPU directly when available:

```powershell
nvidia-smi
```

Do not rebuild the entire environment if an existing `.venv` is healthy.

---

# 4. Machine configuration

Create the machine-local config once:

```powershell
Copy-Item configs\machines\local.example.yaml configs\machines\local.yaml
```

Required keys:

```yaml
data_root: D:/AlgoResearch/data
source_catalog: D:/AlgoResearch/data/catalog.duckdb
cache_root: D:/AlgoResearch/Quant-Pipeline-V3/cache
run_root: D:/AlgoResearch/Quant-Pipeline-V3/runs
scratch_root: D:/AlgoResearch/Quant-Pipeline-V3/scratch
duckdb_temp: D:/AlgoResearch/Quant-Pipeline-V3/scratch/duckdb
gpu_device: cuda:0
```

Typical resource settings for the validated workstation:

```yaml
resource_budget: {ram_gb: 32, reserve_ram_gb: 6, vram_soft_limit_gb: 10.0}
feature_workers: 6
duckdb_threads: 5
duckdb_memory_limit_gb: 18
blas_threads_per_worker: 1
omp_threads_per_worker: 1
```

## Machine-config invariants

- `cache_root`, `run_root`, and `scratch_root` must not be inside `data_root`.
- Paths and worker counts are machine concerns, not research semantics.
- Do not modify research settings to solve a hardware problem. Lower worker/tile pressure instead.

---

# 5. Research-config invariants

Normal V3 discovery config must satisfy all of these:

```yaml
periods:
  discovery:
    end: '2026-04-30'

allow_replication_access: false
allow_final_holdout_access: false
resolutions: [3, 5, 10]

discovery:
  single_parent_gate: false
```

The config loader rejects ordinary discovery configs that violate these rules.

The standard full-discovery request is:

```text
configs/research/v3_discovery.yaml
```

Current discovery periods:

- discovery: `2025-05-01` through `2026-04-30`;
- sealed replication: `2026-05-01` through `2026-08-31`;
- sealed final holdout: `2026-09-01` onward.

---

# 6. Validation ladder before a full run

Do not jump straight into the year-long production request on a fresh machine or after meaningful code changes.

## 6.1 Deterministic smoke

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\smoke.yaml `
  --machine configs\machines\local.yaml
```

Then:

```powershell
.\.venv\Scripts\python -m quant_pipeline status `
  --run-id smoke_v3 `
  --machine configs\machines\local.yaml
```

This is the cheap deterministic plumbing check.

## 6.2 Bounded real-data smoke

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\external_smoke.yaml `
  --machine configs\machines\local.yaml
```

This verifies the real source bridge, real feature/target path, and CUDA scanner on a bounded sample.

## 6.3 Production-path validation

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\production_validation.yaml `
  --machine configs\machines\local.yaml
```

This uses the same V3 production architecture as the full run, with a smaller discovery window/universe.

## 6.4 Tests

Do not automatically run the whole test suite after every operator request.

Run focused tests when code was changed in the relevant subsystem. Examples:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_production_repair.py -q
.\.venv\Scripts\python -m pytest tests\unit\test_cell_evidence.py -q
.\.venv\Scripts\python -m pytest tests\integration\test_candidate_services.py -q
```

Run the broader suite when making architectural changes, parity-sensitive changes, sealed-data changes, or release-level validation.

---

# 7. Full production run

Run the full discovery year with:

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\v3_discovery.yaml `
  --machine configs\machines\local.yaml
```

The canonical run ID is determined by the YAML `run_name`, currently:

```text
v3_discovery
```

## Important: never change semantics under an existing run ID

`run_pipeline()` stores the request at:

```text
runs/<run_id>/request.yaml
```

and does not overwrite that stored request if it already exists.

Therefore:

**If research semantics change, create a new YAML with a new `run_name`.**

Do not reuse `v3_discovery` for a different date range, universe, target set, candidate policy, variant policy, or zoom policy.

---

# 8. Monitoring a run

Use the CLI first:

```powershell
.\.venv\Scripts\python -m quant_pipeline status `
  --run-id v3_discovery `
  --machine configs\machines\local.yaml
```

The status file is:

```text
runs/v3_discovery/STATUS.json
```

Useful fields can include:

- current stage;
- completed / expected units;
- heartbeat;
- process ID;
- RSS memory;
- available RAM;
- CPU utilization;
- disk free space;
- GPU utilization;
- GPU memory;
- GPU temperature;
- GPU clock;
- GPU power.

Detailed events are appended to:

```text
runs/v3_discovery/events.jsonl
```

If a watchdog identifies a stall, diagnostics are written under:

```text
runs/v3_discovery/diagnostics/
```

## Do not infer a hang from low GPU utilization alone

Some stages are CPU-, disk-, DuckDB-, or aggregation-bound. Use heartbeat and stage progress, not one utilization number.

---

# 9. Resume behavior

Resume an interrupted run with:

```powershell
.\.venv\Scripts\python -m quant_pipeline resume `
  --run-id v3_discovery `
  --machine configs\machines\local.yaml
```

`resume` reloads the stored:

```text
runs/v3_discovery/request.yaml
```

The production system has two relevant reuse layers:

1. **cross-run shared stage cache** for expensive compatible core stages;
2. **run-local V3 checkpoints** for post-scan production stages.

Reuse is keyed by source/config/implementation identity. If the source manifest or implementation identity changes, the system may recompute affected work instead of trusting stale artifacts.

## Resource failures

The low-level core can degrade pair tile size and worker count after recoverable memory/resource failures.

If the process terminates after an OOM or temporary I/O failure:

1. inspect `STATUS.json`, `events.jsonl`, and any diagnostics;
2. fix the machine-level pressure if needed;
3. use `resume`;
4. do not delete the whole run unless the artifacts are actually corrupt.

Correctness/parity/schema failures should stop the run. Do not “fix” those by simply reducing workers.

---

# 10. What success looks like

A completed canonical production run should contain:

```text
runs/<run_id>/EVIDENCE_COMPLETE.json
runs/<run_id>/trial_ledger.parquet
runs/<run_id>/cell_specialist_summary.parquet
runs/<run_id>/cell_temporal_summary.parquet
runs/<run_id>/v3_diagnostics/dual_resolution_summary.parquet
runs/<run_id>/analysis_bundle/research.duckdb
runs/<run_id>/analysis_bundle/bundle_manifest.json
```

Before telling the user “the run completed,” verify:

1. `STATUS.json` reports completion;
2. `EVIDENCE_COMPLETE.json` has `status: complete`;
3. `bundle_manifest.json` has `evidence_complete: true`;
4. `replication_accessed` is false;
5. `final_holdout_accessed` is false;
6. all three resolutions are present;
7. the trial ledger contains no unexplained failed work;
8. the production evidence-count reconciliation passed.

Example read-only check:

```powershell
.\.venv\Scripts\python -c "import duckdb; p=r'runs/v3_discovery/analysis_bundle/research.duckdb'; c=duckdb.connect(p,read_only=True); print(c.execute('show tables').fetchall()); print(c.execute('select resolution,count(*) from dual_summary group by 1 order by 1').fetchall()); c.close()"
```

---

# 11. Analysis bundle is the default interface for GPT follow-up

When GPT asks a question about an already completed run, **query the analysis bundle before starting new compute**.

Primary database:

```text
runs/<run_id>/analysis_bundle/research.duckdb
```

Open it read-only:

```python
import duckdb

con = duckdb.connect(
    "runs/v3_discovery/analysis_bundle/research.duckdb",
    read_only=True,
)
```

Useful views/tables include:

- `feature_registry`
- `target_registry`
- `single_summary`
- `dual_summary`
- `surface_summary`
- `surface_cells`
- `cell_evidence`
- `cell_specialist_summary`
- `cell_temporal_summary`
- `trial_ledger`
- `specialist_summary`
- `variant_summary`
- `edge_registry`
- `candidate_summary`
- `edge_families`
- `resolution_comparison`
- `tail_ladder`
- `horizon_ladder`
- `chronological_diagnostics`
- `crossfit_diagnostics`
- `time_of_day`
- `coverage`
- `regime_breakdown`

Some zoom-dependent tables are intentionally empty when the run was made with `zoom.enabled: false`.

## Source-of-truth rule

`research.duckdb` is a rebuildable query layer. The durable Parquet/run artifacts are the research evidence.

Never hand-edit a DuckDB view or table and then treat the result as canonical pipeline output.

---

# 12. High-value `cell_evidence` queries

`cell_evidence` is the main exhaustive cell-level interface.

It expands each canonical pair-target-resolution surface into individual cells and includes:

- active N;
- raw edge in bps;
- frequency;
- standard error;
- interaction lift;
- weighted contribution;
- positive/negative symbol fractions;
- symbol-effect dispersion;
- cancellation score;
- positive/negative fold fractions;
- best/worst fold;
- minimum fold N.

## Large cells by absolute raw edge

```sql
SELECT *
FROM cell_evidence
WHERE active_n >= 250
ORDER BY abs(raw_edge_bps) DESC
LIMIT 100;
```

## Large interaction-only structure

```sql
SELECT *
FROM cell_evidence
WHERE active_n >= 250
ORDER BY abs(interaction_lift_bps) DESC
LIMIT 100;
```

## Negative edges

```sql
SELECT *
FROM cell_evidence
WHERE active_n >= 250
  AND raw_edge_bps < 0
ORDER BY raw_edge_bps
LIMIT 100;
```

## Global cancellation / specialist disagreement

```sql
SELECT *
FROM cell_evidence
WHERE active_n >= 250
ORDER BY cancellation_score DESC NULLS LAST
LIMIT 100;
```

## Stronger temporal sign consistency

```sql
SELECT *
FROM cell_evidence
WHERE active_n >= 250
ORDER BY greatest(fold_positive_fraction, fold_negative_fraction) DESC,
         abs(raw_edge_bps) DESC
LIMIT 100;
```

## Same pair/target across r3/r5/r10

```sql
SELECT pair_id, feature_a, feature_b, target_id,
       v3_resolution, selected_cell, selected_n,
       selected_frequency, selected_state_bps,
       selected_interaction_lift_bps,
       neighbor_effect_retention, plateau_area
FROM dual_summary
WHERE pair_id = ?
  AND target_id = ?
ORDER BY v3_resolution;
```

Do not reduce this comparison to “highest resolution wins.” Resolution disagreement is evidence.

---

# 13. How to classify a GPT request

Before running code, classify the request into one of these categories. Before any request that performs **new computation against an existing run**, also verify that the run still belongs to the same source snapshot and compatible implementation. Compare the run's `source_manifest.json` with a freshly built production source manifest, and let `AlphaDiscoveryRun.initialize()` enforce the stored legacy-core config/implementation hash. If those identities no longer match, do not bypass the guard or mutate the old run; use a new governed run/task context and report the mismatch.

## A. Existing-evidence question

Examples:

- “What are the strongest negative tails?”
- “Which cells cancel globally but work on some symbols?”
- “Does this pair survive across folds?”
- “What does r5 vs r10 look like?”

**Action:** query `research.duckdb` and existing Parquet only.

## B. Candidate dossier question

Examples:

- “How many independent opportunities are there?”
- “Is this driven by one symbol?”
- “What does the tail ladder look like?”
- “How does the edge decay by horizon?”

**Action:** use the candidate dossier if it already exists. If not, create a governed zoom run rather than manually inventing dossier metrics.

## C. Neighbor/variant request

Examples:

- “Try nearby windows for these two features.”
- “What if 30m becomes 15m or 60m?”
- “Scan the neighboring representations of this concept pair.”

**Action:** use hierarchical variant logic. Do not globally brute-force all variants.

## D. Focused execution/backtest request

Examples:

- “Backtest this candidate at 0/1/2/3 bps per side.”
- “Add 1, 2, 5 minutes of latency.”
- “Use only independent opportunities.”
- “What is the drawdown if we execute the frozen rule?”

**Action:** only after the candidate definition is frozen and the dossier is complete. Use explicit raw price legs. Save as derived discovery execution research unless an explicitly authorized OOS period is being evaluated.

## E. New research request

Examples:

- “Add a new feature.”
- “Change target definitions.”
- “Add a new grid.”
- “Change the universe.”

**Action:** code/config change + new run ID. Never retrofit it into an existing canonical run.

## F. Replication request

**Action:** stop and verify explicit authorization and frozen definition. Do not inspect sealed rows before authorization.

---

# 14. Governed zoom run: variants + candidates + dossiers

The standard discovery config currently has:

```yaml
zoom: {enabled: false}
```

If GPT/user wants the pipeline itself to perform candidate materialization, hierarchical variants, and dossiers, create a **new research config with a new run name**.

Start from the canonical request rather than editing it in place:

```powershell
Copy-Item configs\research\v3_discovery.yaml configs\research\v3_discovery_zoom_01.yaml
```

Example:

```yaml
run_name: v3_discovery_zoom_01
```

Keep the discovery semantics identical unless the user explicitly asked to change them, then set:

```yaml
zoom: {enabled: true}
```

Run it normally:

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\v3_discovery_zoom_01.yaml `
  --machine configs\machines\local.yaml
```

The shared cache should reuse compatible expensive core work.

The zoom path performs:

1. permissive structural zoom-pool selection;
2. selected specialist probing;
3. hierarchical neighboring variant expansion;
4. candidate materialization/freezing;
5. dossier construction;
6. updated trial accounting;
7. rebuilt analysis bundle.

For a zoom run, do not use `EVIDENCE_COMPLETE.json` alone as proof that the **zoom** finished: the runner writes the canonical-evidence marker before entering the optional zoom stage. Verify `STATUS.json` is `complete`, `v3_checkpoints/zoom.json` exists and is complete, and the expected `edge_registry.parquet`, `candidate_summary.parquet`, dossier directories, and rebuilt bundle are present. `EVIDENCE_COMPLETE.json` means the exhaustive canonical evidence was reconciled; it is not a standalone zoom-completion marker.

Candidate policy is controlled by:

```yaml
forensics:
  candidate_policy:
    min_active_n: 250
    min_abs_edge_bps: 1.0
    keep_top_k_per_target_resolution: 250
```

Variant behavior is controlled by:

```yaml
variant_expansion:
  parent_limit: null
  neighbors_per_side: 3
  rejected_audit_count: 0
```

Do not make these stricter merely to make the run faster unless the user explicitly accepts the research tradeoff.

---

# 15. Candidate lifecycle

The operating-model lifecycle terms are:

```text
frozen_discovery_candidate
dossier_complete
replication_authorized
replicated
rejected
superseded
```

In the current implementation, materialization creates
`frozen_discovery_candidate`, dossier construction transitions it to
`dossier_complete`, and `replicate` creates a validated replication-request
artifact. The replication CLI does not currently rewrite the registry row to
`replication_authorized` or `replicated`; treat the request artifact and any
later replication evidence as authoritative for those later states.

A materialized candidate is identity-bound to:

- feature A definition;
- feature B definition;
- target definition;
- decision grid;
- resolution;
- exact active cell set/state payload;
- direction;
- return basis;
- source snapshot;
- selection run/trial;
- definition hash.

## Rule

If follow-up analysis changes any of those defining elements, it is a **new candidate**, not an edit to the old one.

**Current implementation boundary:** the automatic V3 materialization/dossier path natively freezes the selected two-feature dual state as a `cell_set` candidate and the dossier builder reconstructs that state from `candidate_summary`/selected cells. Arbitrary rules such as “candidate A AND candidate B,” a symbol whitelist, a custom continuous tail threshold, or a time-of-day filter are **not** safely represented by manually editing `state_payload`. If one of those derived rules is promoted beyond diagnosis, implement a governed candidate/state definition that the identity, dossier, export, and future replication evaluator can reconstruct exactly, then assign a new candidate ID/hash. Do not shoehorn a complex rule into the existing single-cell materializer.

---

# 16. Candidate dossier

Dossiers are written under:

```text
runs/<run_id>/candidates/<candidate_id>/dossier/
```

The production dossier may include:

- `summary.parquet`
- `distribution.parquet`
- `episodes.parquet`
- `chronology.parquet`
- `crossfit_diagnostics.parquet`
- `crossfit_surface.parquet`
- `surface_cells.parquet`
- `resolution_comparison.parquet`
- `tail_ladder.parquet`
- `horizon_ladder.parquet`
- `event_path.parquet`
- `path_diagnostics.parquet`
- `symbol_breakdown.parquet`
- `specialist.parquet`
- `concentration.parquet`
- `interaction.parquet`
- `coverage.parquet`
- `time_of_day.parquet`
- `regime_breakdown.parquet`
- `inference.parquet`
- `state_lifecycle.parquet`
- `signals.parquet`
- `redundancy.parquet`
- `dossier.json`

These are discovery diagnostics. They do not become sealed OOS evidence by being detailed.

## Read the dossier before execution research

At minimum understand:

1. exact frozen state;
2. active observation count;
3. independent opportunities;
4. frequency;
5. raw and direction-aligned return distribution;
6. concentration/outlier dependence;
7. chronology/cross-fit behavior;
8. r3/r5/r10 behavior;
9. tail behavior;
10. horizon decay/path;
11. symbol/specialist structure;
12. time-of-day behavior;
13. return basis.

---

# 17. Focused neighboring-feature analysis

Use this when GPT asks to explore nearby windows/representations for a **specific already identified pair** and a full zoom run would be excessive.

This is derived analysis, not canonical exhaustive discovery.

Before scanning, verify the source run's `source_manifest.json` matches the current production source manifest. Also initialize the reconstructed `AlphaDiscoveryRun` normally; if its stored `run_manifest.json` rejects the current config/implementation hash, **stop rather than bypassing that check**. A focused result should never be presented as an extension of a run produced by different source data or incompatible code.

## 17.1 First inspect the registry

For each parent feature, identify:

- `feature_id`;
- `concept_id`;
- `decision_grid`;
- window/history metadata;
- canonical status/representation.

Neighbors should normally remain inside the same `concept_id` and **must remain on the same `decision_grid` when using the production `_scan_one()` helper**. The helper chooses the grid from the left feature and loads both features on that grid; it is not a cross-grid alignment engine. If the user asks for a cross-grid experiment, treat that as new governed research with an explicit causal alignment rule and a new run/candidate identity rather than forcing it through `_scan_one()`. Cross-concept work is likewise a distinct requested interaction, not an ordinary same-concept neighbor scan.

The production variant code orders nearby variants by proximity to the parent and limits them with `neighbors_per_side`.

## 17.2 Reuse the production scanner

For a focused one-off scan, Codex may reuse:

```python
quant_pipeline.production.variant_scan._scan_one
```

This is an internal helper, so inspect its current signature before using it.

It evaluates the requested feature pair/target at all requested resolutions using the same scanner and rank/bin semantics as production. `_scan_one()` calls the normal feature loader; if a requested neighbor was not already materialized, the loader may create a finalist-feature cache under the **V3-owned run cache**. It must never write to `data_root`. If the task requires a completely untouched source run directory, perform the work in a separate governed run ID instead of using this helper against the original run.

A safe skeleton:

```python
from pathlib import Path
import json
import pandas as pd

from quant_pipeline.config import load_machine_config, load_research_config
from quant_pipeline.data.source_manifest import build_production_source_manifest
from quant_pipeline.production.legacy_core import LegacyCoreAdapter
from quant_pipeline.production.variant_scan import _scan_one

repo = Path.cwd()
machine = load_machine_config(repo / "configs/machines/local.yaml")
run_id = "v3_discovery"
research = load_research_config(Path(machine["run_root"]) / run_id / "request.yaml")
source = build_production_source_manifest(
    data_root=Path(machine["data_root"]),
    repo_root=repo,
)
stored_source = json.loads(
    (Path(machine["run_root"]) / run_id / "source_manifest.json").read_text()
)
if stored_source["source_manifest_hash"] != source["source_manifest_hash"]:
    raise RuntimeError("Source snapshot changed; do not extend the old run in place")

adapter = LegacyCoreAdapter(
    research=research,
    machine=machine,
    repo_root=repo,
    source_manifest_hash=source["source_manifest_hash"],
)
legacy_run = adapter.build_run()
legacy_run.initialize()

rows = _scan_one(
    legacy_run,
    "<neighbor_feature_a>",
    "<neighbor_feature_b>",
    "<target_id>",
    [3, 5, 10],
)

out = Path(machine["run_root"]) / run_id / "derived" / "<task_id>"
out.mkdir(parents=True, exist_ok=True)
pd.DataFrame(rows).to_parquet(out / "neighbor_scan.parquet", index=False)
(out / "request.json").write_text(json.dumps({
    "source_run": run_id,
    "feature_a": "<neighbor_feature_a>",
    "feature_b": "<neighbor_feature_b>",
    "target_id": "<target_id>",
    "resolutions": [3, 5, 10],
    "source_manifest_hash": source["source_manifest_hash"],
    "legacy_implementation_hash": legacy_run.implementation_hash,
}, indent=2))
```

## 17.3 Important interpretation rule

A neighboring variant that looks better is **not the same candidate**.

If it becomes serious:

- materialize/freeze it through the governed candidate path;
- give it a new candidate ID/definition hash;
- generate its own dossier;
- do not overwrite the original candidate.

## 17.4 Avoid uncontrolled variant explosion

Do not scan every variant against every other variant.

Default neighboring work should remain hierarchical and local to the requested concept pair.

---

# 18. Focused tail analysis

Before inventing a new scan, check whether a candidate already has:

```text
tail_ladder.parquet
```

The standard dossier tests tail depths such as:

```text
20%
10%
5%
2%
1%
```

Use existing `forensics.tails.build_tail_mask` semantics if a custom tail depth is requested.

## Rules

- Keep the parent candidate/state definition unchanged unless explicitly defining a new candidate.
- Report `active_n`, eligible N/frequency, raw edge, direction-aligned edge, and independent opportunity count.
- Do not auto-select the best tail as “the strategy.”
- If a new tail boundary is adopted as a tradable rule, freeze it as a new candidate definition.

---

# 19. Focused horizon / alpha-decay analysis

Check existing:

```text
horizon_ladder.parquet
event_path.parquet
path_diagnostics.parquet
```

The dossier compares compatible target horizons with the same:

- grid;
- target family;
- return basis;
- entry rule;
- price basis.

Do not compare unlike targets and call the difference “decay.”

For custom horizon work, reuse the existing target registry/target engine. Do not derive future returns from adjusted feature prices or shift arrays casually.

Keep entry timing causal and use the original governed target definitions.

---

# 20. Specialist / per-symbol follow-up

Start with the exhaustive cell-level specialist summary in `cell_evidence`.

Useful fields include:

- `positive_symbol_fraction`;
- `negative_symbol_fraction`;
- `symbol_effect_dispersion_bps`;
- `cancellation_score`.

For materialized candidates, use:

```text
symbol_breakdown.parquet
specialist.parquet
```

Do not rank a huge universe by tiny-sample local returns without local N.

A globally weak mean may be caused by positive/negative specialist cancellation. Preserve both sides of the evidence.

If GPT asks to **trade only the good symbols**, treat the symbol ranking/subset as discovery-derived selection. You may measure the proposed subset as a derived diagnostic, but a chosen whitelist/blacklist changes the strategy definition. Freeze it through a new governed rule/identity before any sealed evaluation; do not relabel the original global candidate as though its OOS definition always contained that symbol filter. Apply the same rule to time-of-day and regime filters discovered after looking at the dossier.

---

# 21. Focused execution/backtest research

Use this only after the exact discovery rule is frozen and its dossier is complete.

The execution module is:

```python
quant_pipeline.alpha_discovery.execution.candidate_backtest
```

Key primitives:

```python
ExecutionAssumptions
replay_candidate_signals
friction_net_return
aggregate_returns
```

## 21.1 What the replay enforces

`replay_candidate_signals`:

- uses explicit price legs;
- supports long and short directions;
- supports raw, benchmark-adjusted, and beta-residual return bases;
- applies additional entry delay;
- applies slippage and commission costs;
- prevents overlapping positions in the same security;
- rejects signals that cannot be executed before the governed exit;
- requires causal beta for beta-residual hedges;
- reconstructs a benchmark hedge instead of pretending residual target return is executable P&L.

## 21.2 Use independent opportunities, not every active observation

`dossier/signals.parquet` contains active observations. Do not automatically trade every row.

Use the same opportunity logic as the dossier:

```python
from quant_pipeline.forensics.opportunities import (
    Episode,
    independent_entries_fixed_hold,
    independent_entries_by_exit,
)
```

The dossier's `episodes.parquet` provides episode boundaries. Use episode starts and the target ledger's exact exits to reconstruct non-overlapping opportunity entries.

For cross-session holds, use exact exit-time independence. For same-session fixed holds, use the governed hold duration.

## 21.3 Build the replay input from canonical artifacts

For the frozen candidate:

1. read its row from `edge_registry.parquet`;
2. read its dossier signals/episodes;
3. read the target ledger:

```text
runs/<run_id>/cache/targets/<grid>.parquet
```

4. filter the exact `target_id`;
5. merge by `observation_id`;
6. preserve governed `entry_ts`, `entry_price`, `exit_ts`, and `exit_price`;
7. use the candidate's frozen direction and return basis;
8. load raw bars from the configured source **read-only** for delayed entries;
9. if the return basis is benchmark-adjusted or beta-residual, also construct explicit benchmark entry/exit legs using the configured benchmark and the candidate's causal `beta_prior`.

The DataFrame passed to `replay_candidate_signals()` must contain these exact columns:

```text
candidate_key
observation_id
security_id
symbol
decision_ts
governed_entry_ts
governed_entry_price
exit_ts
exit_price
local_direction
return_basis
benchmark_entry_ts
benchmark_entry_price
benchmark_exit_ts
benchmark_exit_price
beta_prior
```

Use the frozen `candidate_id` as `candidate_key`; use the candidate's frozen direction as `local_direction`; map the target ledger's `entry_ts`/`entry_price` to `governed_entry_ts`/`governed_entry_price`. For `raw` candidates, keep the benchmark columns present but null/NaN. For `benchmark_adjusted` and `beta_residual`, resolve the configured benchmark security from the security master and obtain the benchmark's governed target window for the **same target horizon and decision event**. Intraday joins should preserve the matching decision timestamp; daily-style targets should preserve the matching session/target definition. Do not approximate the hedge window from the stock return value.

`price_bars` must be a mapping keyed by stringified `security_id`; each value is a time-ordered `pandas.Series` indexed by UTC raw bar-start timestamp and containing the raw **open** used for delayed entry selection. Include the benchmark series when a hedge leg is required. The replay delays entry only; the governed exit timestamp/price remains the target exit, with adverse exit slippage handled by the slippage model.

For a discovery-period replay, bound every direct raw-lake query to the exact governed discovery windows being replayed. Do **not** issue an unconstrained read of later raw bars simply because `data_root` contains them. No helper script may inspect replication/final-holdout dates while preparing discovery execution data. If an additional delay would require an entry at or beyond the governed exit or outside the authorized evidence period, reject that trade rather than reading farther into sealed data. Open external DuckDB/catalog sources read-only.

## 21.4 Do not use residual target values as fills

For `benchmark_adjusted` or `beta_residual` candidates:

- stock leg: explicit raw stock entry and exit;
- hedge leg: explicit raw benchmark entry and exit;
- hedge ratio: 1.0 for benchmark-adjusted, causal `beta_prior` for beta-residual;
- direction: benchmark exposure is opposite the signed stock exposure.

This is required for an execution backtest.

## 21.5 Assumption grid

Example:

```python
from quant_pipeline.alpha_discovery.execution.candidate_backtest import (
    ExecutionAssumptions,
    replay_candidate_signals,
    aggregate_returns,
)

for cost in [0, 1, 2, 3, 5]:
    for delay in [0, 1, 2, 5]:
        assumptions = ExecutionAssumptions(
            cost_bps_per_side=cost,
            slippage_bps_per_side=0,
            additional_entry_delay_minutes=delay,
        )
        trades, rejected = replay_candidate_signals(
            signals,
            price_bars,
            assumptions,
            benchmark_security_id=benchmark_security_id,
        )
        stats = aggregate_returns(trades, "net_trade_return")
```

**Interpret `aggregate_returns()` correctly.** It sums normalized per-trade returns and builds a realized-only additive equity diagnostic from exit events. It does **not** impose a portfolio capital budget, position sizing, leverage limit, cross-symbol concurrency cap, or mark-to-market path. Therefore its `return` and `max_drawdown` are candidate-level execution diagnostics, not automatically a deployable portfolio return/drawdown. If GPT asks for capital-constrained portfolio P&L, define explicit allocation/concurrency rules and run a separate derived portfolio replay. The existing `portfolio_replay.py` is fixed-base and long-only, so do not use it unchanged for short or hedged candidates.

`cost_bps_per_side` and `slippage_bps_per_side` must be nonnegative.

If the user wants to test a rebate or negative transaction-cost assumption, do not force a negative value into this API. Model that separately and label it explicitly.

## 21.6 Save derived execution work separately

Write to something like:

```text
runs/<run_id>/derived/<task_id>/
    request.json
    replay_summary.parquet
    trades.parquet
    rejected_signals.parquet
```

`request.json` should include:

- a deterministic request/spec hash for idempotence;
- source run ID;
- candidate ID;
- definition hash;
- source manifest hash;
- target ID;
- return basis;
- opportunity selection policy;
- cost grid;
- slippage grid;
- delay grid;
- code/commit identity if available;
- explicit statement that this is discovery-period execution research unless otherwise authorized.

## 21.7 Reporting focused backtests

Report at least:

- candidate ID and definition hash;
- period used;
- opportunity count;
- executed trade count;
- rejected trade count and major reasons;
- gross additive trade-return sum / average trade;
- net additive trade-return sum / average trade;
- median trade;
- win rate;
- realized-only additive drawdown diagnostic;
- if a separate capital-constrained portfolio replay was run, its allocation rules and portfolio-level metrics separately;
- cost/slippage/delay assumptions;
- whether results are discovery diagnostics or sealed OOS.

Do not report a synthetic adjusted target mean as executed P&L.

---

# 22. SIP signal export

For a directional candidate with a completed dossier:

```powershell
.\.venv\Scripts\python -m quant_pipeline export-sip `
  --candidate-id <candidate_id> `
  --machine configs\machines\local.yaml
```

Output is written under:

```text
runs/<run_id>/execution_data/<candidate_id>.parquet
```

The export preserves the frozen candidate ID/state and emits signal timestamps, direction, symbol/security, and reference exit timestamps.

**Current implementation detail:** when a production dossier exists, the exporter reads `dossier/signals.parquet`. That file contains the candidate's active observation rows; it is not an independent-opportunity-filtered trade ledger. A downstream execution/replay task must still apply the intended episode/overlap/opportunity policy rather than assuming every exported row is a simultaneously tradable independent opportunity.

A zero-direction interaction-only candidate cannot be exported as a directional SIP signal. The current export service writes the Parquet artifact but does not update `edge_registry.parquet`'s `sip_status`; verify the output file itself rather than assuming the registry status changed.

SIP export is a downstream handoff. It does not fabricate quote fills or market impact.

---

# 23. Explicit replication promotion

Replication is sealed during ordinary discovery.

Before promotion, require:

- frozen candidate;
- `dossier_complete` status;
- unchanged definition hash;
- explicit authorization from the user/research owner.

The current service requires an authorization file at:

```text
runs/<run_id>/authorizations/<candidate_id>.json
```

with these fields:

```json
{
  "candidate_id": "<candidate_id>",
  "definition_hash": "<exact frozen definition hash>",
  "scope": "sealed_replication",
  "authorized_by": "<explicit authorizer>",
  "authorized_at_utc": "<ISO-8601 timestamp>"
}
```

Do not create this file merely because an analysis prompt says “see if it holds up.” Explicit authorization is required. Authorization must refer to the exact candidate ID, exact frozen definition hash, and `sealed_replication` scope. Do not invent `authorized_by` or backfill an approval from context; use an existing authoritative authorization record or an explicit authorization that supplies enough identity/scope information to record faithfully.

After authorization:

```powershell
.\.venv\Scripts\python -m quant_pipeline replicate `
  --candidate-id <candidate_id> `
  --machine configs\machines\local.yaml
```

## Critical current behavior

In the current V3 CLI, this command validates the authorization and frozen definition, then writes a request under:

```text
runs/<run_id>/replication/<candidate_id>.request.json
```

It **does not itself evaluate the sealed replication data**. It also does not currently rewrite `edge_registry.parquet` to change the candidate row's status; the authoritative product of this CLI action is the validated replication request JSON (whose payload has `status: replication_authorized`). Do not infer that the registry row changed unless code explicitly did so.

Therefore Codex must report:

> replication request prepared / candidate promoted for replication

not:

> replication passed / replication was evaluated

unless a separately implemented and explicitly authorized evaluation workflow actually ran.

Do not manually call legacy sealed-period evaluation methods as an operator shortcut.

---

# 24. Final holdout

The final holdout begins at `2026-09-01` and is sealed.

There is no ordinary V3 CLI command that should be used casually to inspect it.

Treat final-holdout access as a one-way research-governance event that requires an explicitly frozen upstream methodology and explicit authorization.

If GPT asks for final-holdout results and no authorized final-holdout workflow has already produced them, report that the period is still sealed rather than opening it.

---

# 25. Adding a new feature

When asked to add a new feature:

1. identify whether it is truly a new concept or a variant/window/representation of an existing concept;
2. place it in the appropriate feature pack/registry path;
3. define causal input requirements and availability timing;
4. set implementation/definition identity correctly;
5. preserve point-in-time behavior;
6. add focused unit/parity tests;
7. create a new research config/run ID;
8. run smoke -> bounded real-data validation -> production request as appropriate.

If it is only a nearby window or representation of an existing concept, prefer the hierarchical variant path rather than pretending it is an unrelated concept.

Never add a feature by manually injecting a column into the final DuckDB bundle.

---

# 26. Changing targets, grids, universe, or periods

These are research-semantic changes.

Always use a new run ID. Also respect the implementation's current hard boundaries: `load_research_config()` pins the ordinary V3 discovery **end** to `2026-04-30`, and the current feature/target stack recognizes the repository's governed grids (`intraday_1m`, `intraday_5m`, `daily_close`, `preclose_1555`). Changing the discovery end or introducing a truly new grid is not just a YAML edit; it requires an intentional code/governance change plus focused tests. Never weaken the sealed-period guard merely to satisfy an ad-hoc prompt.

Examples:

- new target horizon;
- different return basis;
- altered entry delay in target definition;
- new decision grid;
- changed liquidity/price universe filter;
- changed discovery dates;
- changed feature scope;
- changed canonical anchors.

Do not patch an old run's Parquet outputs to approximate the new research definition.

---

# 27. What to do when GPT asks “try combining these findings”

Do not immediately invent a portfolio or multi-leg strategy from top rows.

First determine whether the requested combination means:

1. **logical intersection** of two frozen signals;
2. **confirmation** where both are active;
3. **union** of signals;
4. **ranking/priority** among simultaneous signals;
5. **separate sleeves** in a portfolio;
6. **new feature interaction** requiring a new discovery test.

For discovery intersections/unions:

- use observation IDs and signal timestamps from canonical/dossier artifacts;
- keep exact candidate identities;
- compute overlap/Jaccard and independent opportunities;
- report incremental effect vs each parent;
- save the combination as derived analysis;
- if adopted as a strategy rule, freeze it as a new candidate rather than silently modifying either parent.

The current built-in `materialize_candidates()`/dossier path does not natively encode an arbitrary union/intersection of already frozen candidates. If a combination is promoted, add a reconstructible governed rule/state representation and tests instead of fabricating an `edge_registry` row or editing `state_payload` by hand.

Do not call two correlated variants “two independent edges” without redundancy analysis.

---

# 28. Return-basis discipline

The pipeline treats these as distinct targets:

```text
raw
benchmark_adjusted
beta_residual
```

Always include return basis in focused-analysis outputs.

Never compare a residual edge and a raw edge as if they were identical economic objects.

For execution research, reconstruct explicit stock and benchmark legs as required.

---

# 29. Canonical evidence vs derived analysis

Use this rule whenever unsure where output belongs.

## Canonical evidence

Produced by the governed production run and trial-accounted pipeline stages.

Examples:

- exhaustive canonical dual surfaces;
- cell specialist evidence;
- cell temporal evidence;
- governed variant expansion;
- candidate registry;
- dossiers;
- trial ledger;
- analysis bundle.

## Derived analysis

A focused question asked after the run that does not change canonical evidence.

Examples:

- custom SQL ranking;
- one-off visualization;
- custom tail boundary;
- focused nearby-window scan;
- alternative cost grid;
- alternative delay grid;
- overlap comparison between selected candidates.

Derived analysis should go under:

```text
runs/<run_id>/derived/<task_id>/
```

unless the repository later introduces a dedicated first-class location.

A derived result becomes canonical only if it is reintroduced through a governed research stage with trial accounting and frozen identity.

---

# 30. Safe query/report workflow for GPT

When GPT asks Codex to analyze a completed run:

1. identify the source run ID;
2. read `bundle_manifest.json`;
3. open `research.duckdb` read-only;
4. check whether zoom/dossiers exist;
5. query the smallest set of tables needed;
6. use raw Parquet/dossier artifacts when the query layer lacks needed detail;
7. only run new compute if the evidence does not already answer the question;
8. before new compute, verify source/config/implementation compatibility and bound all source reads to the authorized evidence period;
9. store new compute in `derived/<task_id>` with a request/spec hash and do not overwrite a mismatched prior task;
10. state whether the conclusion comes from:
   - exhaustive discovery evidence;
   - candidate dossier diagnostics;
   - derived discovery backtest;
   - sealed replication;
   - final holdout.

Never blur those evidence classes.

---

# 31. Minimal operator decision table

| Request | First action | New compute? | New run ID? |
|---|---|---:|---:|
| “What did the run find?” | Query analysis bundle | Usually no | No |
| “Show strongest cells/tails” | Query `cell_evidence` / dossier | Usually no | No |
| “Analyze this candidate deeply” | Read dossier | Only if dossier missing | Prefer governed zoom run if missing |
| “Try nearby feature windows” | Inspect registry + local variant scan | Yes | Not for a small derived scan; yes if promoting into governed pipeline |
| “Run cost/delay backtest” | Frozen candidate + dossier + explicit price replay | Yes | No, save under derived task |
| “Add a new feature/target” | Modify governed definitions | Yes | Yes |
| “Export signals” | `export-sip` | Yes, downstream artifact | No |
| “Check replication” | Verify explicit authorization | Yes, but sealed workflow only | Candidate-specific promotion |
| “Check final holdout” | Verify explicit authorization/frozen methodology | Yes, sealed workflow only | Controlled one-way workflow |

---

# 32. Failure and troubleshooting checklist

## `ConfigurationError`

Check:

- discovery end is exactly `2026-04-30` for normal V3 discovery;
- sealed access flags are false;
- resolutions are exactly `[3, 5, 10]`;
- `single_parent_gate` is false;
- required machine keys exist;
- V3-owned paths are outside `data_root`.

## CUDA / memory failure

- inspect telemetry first;
- reduce machine-level pressure, not research semantics;
- allow the resource-recovery logic to degrade pair tile/worker count;
- resume.

## Missing r3/r5/r10 output

Do not build the analysis bundle manually around it. The production resolution stage should fail because missing resolution trees violate evidence integrity.

## Evidence count mismatch

Stop. Do not mark the run complete. Compare the exhaustiveness manifest's expected pair-target count against dual/specialist/temporal surface counts.

## Source changed

The source-manifest hash should change. Let the runner invalidate/recompute affected work. Do not force reuse of stale checkpoints.

## Code changed during/after a run

Implementation hashes protect reuse. If the requested analysis depends on new logic, use an appropriately new run or rerun affected governed stages. Do not present old artifacts as if produced by the new code.

## Stale/missing `STATUS.json`

Inspect `events.jsonl`, process existence, diagnostics, and checkpoints. If the process is gone, resume. If it is alive but genuinely stalled, diagnose the current stage rather than deleting output blindly.

---

# 33. Recommended Codex response after an operation

After doing substantial pipeline work, report concisely:

```text
Run/task:
Source run ID:
Action performed:
Evidence period:
Artifacts created/read:
Completed/reused/failed work:
Key findings:
Replication accessed: yes/no
Final holdout accessed: yes/no
Any caveats or next required action:
```

For focused execution research also include:

```text
Candidate ID:
Definition hash:
Target / return basis:
Independent opportunity policy:
Costs/slippage/delay assumptions:
Trade count / rejected count:
Discovery diagnostic or sealed OOS:
```

---

# 34. Preferred operating sequence for the full project

When operating the project end-to-end, use this order:

1. validate environment;
2. validate machine config;
3. deterministic smoke;
4. bounded external smoke;
5. production-path validation;
6. full canonical discovery run;
7. verify evidence completeness and trial reconciliation;
8. analyze `research.duckdb` / Parquet evidence;
9. identify relationships worth deeper investigation;
10. run governed zoom or focused derived analyses;
11. freeze any materially changed candidate as a new identity;
12. require a complete dossier before execution research;
13. run focused raw-price execution/cost/delay work on frozen rules;
14. export SIP signals if requested;
15. keep replication sealed until explicit authorization;
16. promote the exact frozen candidate to a replication request only when authorized;
17. do not claim sealed validation until an authorized evaluation actually runs;
18. keep final holdout sealed until its own explicit later promotion.

---

# 35. Explicit zoom requests

A zoom config may request exact neighboring variants in `variant_expansion.explicit_requests` and exact canonical or variant states in `forensics.explicit_candidates`. Use `zoom.selection_mode: explicit` for only guaranteed requests or `explicit_plus_rules` to union them with the deterministic, bounded dossier selector. Existing automatic behavior remains the default.

An explicit cell must use the authoritative stored `feature_a` / `feature_b` surface orientation; reversing those fields is rejected because the same numeric cell would mean a different state. `cell_mode: scanner_selected` retains the scanner cell, while `cell_mode: explicit` freezes `cell_index`. Use `direction_mode: auto` for normal directional semantics or `descriptive` for a zero-direction evidence dossier whose raw evidence is preserved and whose direction-aligned fields are unavailable.

Specialist evidence is keyed by the exact feature pair, target, resolution, and selected cell (`state_key`). Guaranteed explicit states are probed even below the automatic selected-N screen. Dynamic dossiers are selected in deterministic pre/post-specialist passes and remain bounded; guaranteed explicit dossiers are outside that cap. `symbol_active_breakdown.parquet` reports every active frozen-cell observation by security, while `symbol_breakdown.parquet` remains the independent-opportunity view.

---

# 36. The core rule

**Use V3 to generate auditable evidence, use GPT/Codex to ask focused questions of that evidence, and never let a convenient follow-up silently rewrite the experiment that produced it.**

Broad discovery, hierarchical variants, frozen candidate identity, explicit execution assumptions, and sealed OOS periods are separate steps. Keep them separate in code, artifacts, and reporting.
