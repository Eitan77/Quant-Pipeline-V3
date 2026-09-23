# Quant Pipeline V3

**Comprehensive research handoff status:** the bounded real-core gate completed mandatory subgroup coverage and a local query/recomputation/diagnostic/replay loop. The configured full discovery request has not been launched, and the 19-task handoff is still in progress. Its dense storage estimate does not block the bounded recomputable path. See [implementation status](docs/RESEARCH_IMPLEMENTATION_STATUS.md). Existing `v3_discovery` artifacts retain their legacy coverage meaning.

> A single-machine, GPU-accelerated quantitative research engine for searching large spaces of equity features, interactions, tails, and specialist effects without throwing away useful evidence too early.

Quant Pipeline V3 is the third version of a research pipeline I built to answer a deceptively hard question:

**Given a very large set of market features and forward-return targets, where are the relationships that are actually interesting enough to investigate further?**

The project is designed around broad, reproducible discovery. It generates the evidence first, keeps that evidence auditable, and leaves the final interpretation to a separate research step rather than having the scanner automatically declare a “best strategy.”

V3 is built to run on one workstation, make heavy use of the GPU, survive long unattended runs, reuse previous work, protect sealed out-of-sample data, and finish each run with a standardized analysis package that can be queried directly with DuckDB or handed to GPT for deeper forensic analysis.

---

## What the pipeline does

At a high level, V3:

1. Reads the external market-data store **without modifying it**.
2. Builds point-in-time observation panels and research targets.
3. Computes a large feature library from versioned feature packs.
4. Runs single-feature analysis for context — but **does not require a feature to look good alone before testing interactions**.
5. Exhaustively tests every structurally compatible pair of canonical feature concepts.
6. Evaluates each pair independently at **r3, r5, and r10** state resolutions.
7. Preserves the full surface of every tested interaction, not just the strongest cell.
8. Measures specialist effects, temporal stability, interaction lift, frequency, concentration, and other diagnostics.
9. Reconciles the work into a complete trial ledger.
10. Builds a compact `analysis_bundle` containing Parquet tables plus a queryable DuckDB research database.
11. Optionally “zooms in” on interesting regions with variant expansion, candidate freezing, and detailed dossiers.
12. Keeps replication and final-holdout data sealed until explicitly authorized.

The result is less like a traditional strategy backtester and more like an **evidence factory for quantitative research**.

---

# How V3 is built

## 1. Read-only source data and point-in-time research

The external candle/source store is treated as an input, not as V3's workspace. V3 creates its own caches, scratch files, run outputs, manifests, and analysis bundles under its own directories.

That separation matters because it makes a research run easier to reproduce and prevents the research pipeline from quietly rewriting its source data.

The data layer also keeps track of point-in-time universe membership, corporate actions, observation identity, timestamps, and other information needed to avoid accidentally using data that would not have been available at the time of a decision.

---

## 2. Feature packs

Features are loaded through versioned **feature packs**.

The built-in `builtin_v2_port` pack is a parity-preserving port of the authoritative V2 feature registry and feature implementations. Each feature concept has metadata describing things such as:

- concept identity;
- family;
- canonical representation;
- window or scale;
- availability timing;
- price basis;
- and definition identity.

A key V3 idea is the distinction between a **concept** and all of its possible variants.

Instead of brute-forcing every tiny variation of every feature against every other variation, V3 first chooses one declared canonical representation of each concept. The broad search is exhaustive across those canonical concepts. More expensive window/representation expansion can happen later for relationships that deserve a closer look.

This gives the search wide interaction coverage without making the first pass computationally absurd.

---

## 3. Targets

The target engine builds forward-looking return targets across compatible grids and horizons.

Targets remain separate from feature definitions, which makes it possible to study the same feature relationship across different holding periods and return interpretations without rebuilding the entire feature layer.

Later forensic stages can also construct horizon ladders and event paths so an apparent edge can be inspected across time rather than judged from one arbitrary exit horizon.

---

## 4. Singles are measured, but they are not a gate

This is one of the most important differences from a conventional funnel.

V3 still computes single-feature statistics because they are useful research information. But a feature **does not need to be predictive by itself to enter the main dual search**.

Why?

Because two weak standalone features can create a strong conditional relationship when they are combined.

Examples include:

- confirmation states;
- disagreement states;
- exhaustion plus flow;
- regime-dependent behavior;
- reversal conditions;
- interaction-only effects.

A singles gate would destroy those relationships before they were ever tested. V3 therefore treats single-feature performance as evidence, not permission.

---

## 5. Exhaustive canonical dual search

The main discovery stage tests every structurally compatible pair of canonical feature concepts.

That means the pair planner is designed to answer:

> “Have we tested the interaction space we said we were going to test?”

rather than:

> “Did the parent features look good enough that we felt like testing them?”

The scanner is implemented around GPU-friendly batching and reusable rank/bin representations. It preserves both positive and negative effects and records the information required to reconstruct the shape of the relationship later.

The search is exhaustive at the **canonical concept** level, while variant expansion is hierarchical and downstream.

---

## 6. r3, r5, and r10 are separate views — not a ladder where r10 automatically wins

Every canonical pair is evaluated at three state resolutions:

| Resolution | Intuition |
|---|---|
| **r3** | Broad regimes / coarse states |
| **r5** | Medium selectivity |
| **r10** | Fine states / extreme tails |

A relationship can be real at one resolution and disappear at another. That disagreement is itself useful information.

For example, a broad r5 region may contain a stable effect while the narrower r10 tail becomes noisy. V3 therefore keeps all three resolution surfaces independently instead of assuming that more bins always means a better answer.

---

## 7. Full surfaces, not just “the winning cell”

For each pair, target, and resolution, V3 preserves the sufficient statistics for the **entire state surface**.

This allows later analysis of:

- the strongest positive state;
- the strongest negative state;
- neighboring cells;
- plateaus versus isolated spikes;
- surface spread;
- state frequency;
- selected observation count;
- interaction lift;
- weighted contribution;
- and the overall geometry of the relationship.

This is important because a single best cell can be misleading. A broad plateau and a one-cell spike may have the same maximum return but tell completely different research stories.

The analysis bundle exposes an expanded `cell_evidence` view so the exhaustive cell-level results can be queried directly.

---

## 8. Edge size and frequency are kept separate

A rare state with a large conditional return is different from a common state with a smaller return.

V3 therefore separates:

- **active edge** — the average return while the state is active;
- **frequency** — how often the state occurs;
- **weighted contribution** — the effect size multiplied by how often it occurs.

Keeping these separate prevents an interesting tail from disappearing just because it is rare, while still making its economic footprint visible.

---

## 9. Specialist and global-cancellation analysis

A relationship that looks weak globally can still contain useful structure.

For example:

- one group of symbols may have a strong positive effect;
- another group may have a strong negative effect;
- the aggregate can cancel to almost zero.

V3 includes specialist diagnostics across the exhaustive surfaces to capture this type of **global cancellation** rather than assuming a weak global mean means “nothing is here.”

The production evidence includes per-cell measurements such as positive/negative symbol fractions, symbol-effect dispersion, and cancellation scores. Candidate dossiers can later expand selected relationships into more detailed symbol-level breakdowns.

---

## 10. Temporal diagnostics

V3 also asks whether the effect is concentrated in one part of the discovery period or appears repeatedly across chronological folds.

For each cell, the production temporal stage records information such as:

- positive-fold fraction;
- negative-fold fraction;
- best and worst fold;
- median fold effect;
- fold dispersion;
- minimum fold sample size.

These are **discovery diagnostics**, not true out-of-sample evidence. The actual replication period remains sealed until a candidate definition has been frozen.

---

## 11. Trial accounting

A huge search is only interpretable if the system can say what it actually tested.

V3 therefore builds a trial ledger that tracks work across research families and reconciles statuses such as:

- executed;
- reused;
- structurally excluded;
- unavailable;
- failed.

The pipeline checks the expected exhaustive coverage against the generated resolution, specialist, and temporal evidence before declaring the evidence set complete.

This is intentionally different from only saving whatever happened to look interesting.

---

## 12. The analysis bundle

Every completed production run ends with a standardized `analysis_bundle/`.

The bundle contains compact Parquet tables plus a `research.duckdb` database with convenient views over the run.

Core tables include:

- feature registry;
- target registry;
- single-feature summary;
- canonical dual summary;
- r3/r5/r10 surface data;
- cell specialist diagnostics;
- cell temporal diagnostics;
- trial ledger;
- and bundle/run manifests.

When the optional zoom stage is enabled, the bundle can also include:

- variant summaries;
- candidate registry;
- candidate summaries;
- detailed dossiers;
- tail ladders;
- horizon ladders;
- chronology;
- cross-fit diagnostics;
- time-of-day analysis;
- coverage tables;
- regime diagnostics;
- and other forensic outputs.

The database exposes an expanded `cell_evidence` interface so questions can be asked across the entire exhaustive search without manually opening thousands of result shards.

Example research questions:

```sql
-- Which states are large, frequent enough to matter, and temporally consistent?
SELECT *
FROM cell_evidence
WHERE active_n >= 250
  AND abs(raw_edge_bps) >= 2
ORDER BY abs(raw_edge_bps) DESC;
```

Or at a higher level:

- Which pairs are strong at r5 but weak at r10?
- Which globally weak relationships show strong specialist cancellation?
- Which feature families repeatedly interact across targets?
- Which states have broad plateaus instead of isolated spikes?
- Which tails persist across multiple horizons?

This is one of the main design goals of V3: **make the output easier to investigate than the pipeline itself.**

---

# Optional zoom stage: from huge search to candidate dossiers

The exhaustive production pass is intentionally evidence-first.

If `zoom.enabled: true`, V3 can then take a broad pool of interesting surfaces and perform deeper work:

1. specialist probing;
2. hierarchical variant/window expansion;
3. candidate materialization;
4. frozen candidate identity;
5. detailed forensic dossier generation;
6. rebuilt trial accounting and analysis bundle.

A dossier can include:

- independent opportunity counts;
- episode/state lifecycle information;
- symbol breakdowns;
- interaction decomposition;
- chronological diagnostics;
- r3/r5/r10 comparison;
- tail ladders;
- horizon ladders;
- event paths;
- actual trade-path diagnostics;
- concentration analysis;
- time-of-day behavior;
- coverage diagnostics;
- clustered inference;
- signal timestamps;
- and the exact frozen state definition.

The important idea is that deeper analysis happens **after** broad evidence has been preserved, not instead of it.

---

# Sealed replication and holdout data

The current discovery configuration separates the timeline into three periods:

| Period | Dates | Access during normal discovery |
|---|---|---|
| **Discovery** | 2025-05-01 → 2026-04-30 | Allowed |
| **Replication** | 2026-05-01 → 2026-08-31 | Sealed |
| **Final holdout** | 2026-09-01 onward | Sealed |

Normal discovery is prevented from reading beyond the discovery cutoff.

A candidate must first be frozen with a stable definition hash. Replication access then requires an explicit candidate-specific authorization path.

This makes it much harder to accidentally “peek” at future evaluation data while iterating on a discovery rule.

---

# Reliability and long-run behavior

V3 is designed for long unattended jobs on a single PC.

Important reliability features include:

### Resumable stages
Completed production stages have checkpoints tied to both the source snapshot and the implementation hash. Compatible work can be reused instead of recomputed.

### Atomic outputs
Critical metadata is written through temporary files and atomically promoted, reducing the chance that an interrupted run is mistaken for a valid completed artifact.

### Shared caches
Expensive reusable artifacts are stored separately from one-off run output so future research can reuse compatible work.

### Resource-aware batching
The specialist and temporal GPU stages choose pair block sizes based on available device memory rather than blindly allocating a fixed giant batch.

### Telemetry
The pipeline has telemetry/watchdog infrastructure for tracking long-running work and diagnosing stalls or resource pressure.

### Research config vs machine config
Research decisions and hardware settings live in separate YAML files, so changing a path, thread count, or GPU device does not silently change the research definition.

---

# Built for a real single-machine workstation

The default machine profile is tuned around a workstation with:

- Intel Core i9-11900KF;
- 32 GB RAM;
- NVIDIA RTX 3080 Ti;
- NVMe storage.

The goal is not simply “use 100% of everything.” V3 deliberately reserves RAM for the OS, limits CPU/BLAS oversubscription, uses NVMe scratch space, and batches GPU work around available VRAM.

That matters for jobs that may run for many hours: stable throughput is more useful than briefly maximizing utilization and then paging, thrashing, or crashing.

---

# Recorded benchmark artifacts

The repository includes [benchmark records](docs/BENCHMARKS.json) from the
production-repair validation work.

| Test | Recorded result |
|---|---:|
| Deterministic smoke, cold | **1.61 s** |
| Deterministic smoke, warm resume | **0.71 s** |
| External smoke rows | **175,419** |
| External smoke backend | **Torch / CUDA (`cuda:0`)** |
| External smoke wall time | **42.44 s** |
| External smoke scan throughput | **1,708 pair-targets/s** |
| Latest external warm resume | **0.157 s** |
| GPU microbenchmark device | **RTX 3080 Ti** |

These are validation benchmarks, not a claimed runtime for the full discovery-year workload.

---

# V2 parity without a runtime V2 dependency

V3 keeps a parity-sensitive internal port for the parts where changing semantics would make old and new research difficult to compare — including point-in-time construction, panels, features, targets, singles, and canonical surface scanning.

The repository contains a [`V2_PARITY.json` validation artifact](docs/V2_PARITY.json)
showing matching hashes for the copied parity modules and successful focused
parity tests.

At runtime, however, V3 does **not** import the external V2 repository or read V2 caches/results/checkpoints. V3 owns its own runtime state and adds the new production diagnostics, trial accounting, candidate lifecycle, dossiers, cache behavior, and analysis bundle on top.

---

# Repository layout

```text
Quant-Pipeline-V3/
|
|-- configs/
|   |-- research/              # Research definitions / run requests
|   `-- machines/              # Local paths and hardware settings
|
|-- feature_packs/             # Versioned feature definitions
|   `-- builtin/v2_port/
|
|-- reference/                 # PIT membership, security master, corp actions
|
|-- src/quant_pipeline/
|   |-- alpha_discovery/       # Parity-sensitive V2-derived research core
|   |-- data/                  # Source bridge, observation identity, manifests
|   |-- features/              # V3 feature-pack / feature-engine infrastructure
|   |-- targets/               # Target engine
|   |-- discovery/             # Planning, trials, variants, surfaces
|   |-- production/            # Authoritative V3 production evidence pipeline
|   |-- forensics/             # Tails, chronology, interactions, paths, etc.
|   |-- candidates/            # Candidate identity, registry, lifecycle
|   |-- analysis_bundle/       # Standardized research output
|   |-- execution_data/        # Downstream SIP export
|   |-- telemetry/             # Runtime telemetry and watchdogs
|   `-- orchestration/         # Pipeline orchestration infrastructure
|
|-- tests/                     # Unit, integration, parity and reliability tests
|-- tools/                     # Benchmark and parity utilities
|-- docs/                      # Codex runbook, environment, and validation artifacts
|-- cache/                     # V3-owned reusable cache
|-- runs/                      # Run outputs
|-- scratch/                   # Temporary / spill / work data
|
|-- V3_MASTER_SPEC.md          # Full research and architecture specification
`-- README.md
```

---

# Running V3

V3 requires Python 3.12+.

Create a machine-local config once:

```powershell
Copy-Item configs\machines\local.example.yaml configs\machines\local.yaml
```

Install the project environment/dependencies, then run through the canonical CLI.

For Codex-specific operating rules—run validation, monitoring, evidence queries,
zoom work, SIP export, and sealed replication handling—use
[`docs/CODEX_OPERATION_MANUAL.md`](docs/CODEX_OPERATION_MANUAL.md).

### Deterministic smoke test

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\smoke.yaml `
  --machine configs\machines\local.yaml
```

### Bounded real-data replay

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\external_smoke.yaml `
  --machine configs\machines\local.yaml
```

### Production-path validation

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\production_validation.yaml `
  --machine configs\machines\local.yaml
```

### Full discovery-year run

```powershell
.\.venv\Scripts\python -m quant_pipeline run `
  --request configs\research\v3_discovery.yaml `
  --machine configs\machines\local.yaml
```

### Check status

```powershell
.\.venv\Scripts\python -m quant_pipeline status `
  --run-id v3_discovery `
  --machine configs\machines\local.yaml
```

### Resume an interrupted run

```powershell
.\.venv\Scripts\python -m quant_pipeline resume `
  --run-id v3_discovery `
  --machine configs\machines\local.yaml
```

---

# Research philosophy

The project is built around a few simple principles:

**Search broadly enough to find interactions.**
Do not assume useful features must look good individually.

**Keep the shape of the evidence.**
A full surface is more informative than one maximum cell.

**Do not throw away negative or specialist effects.**
Direction, rarity, and cross-symbol disagreement are information.

**Separate discovery from true out-of-sample validation.**
Internal folds are diagnostics. Sealed replication is replication.

**Make large searches auditable.**
Track what was executed, reused, excluded, unavailable, or failed.

**Optimize around the machine that actually runs the research.**
Stable overnight throughput matters more than theoretical peak utilization.

**Generate evidence, not automatic trading recommendations.**
The pipeline produces structured research data. Human/GPT analysis and downstream execution testing decide what deserves the next experiment.

---

# Current status

The V3 production architecture is implemented and includes the exhaustive canonical search path, r3/r5/r10 evidence, cell-level specialist and temporal diagnostics, trial reconciliation, resumability, analysis-bundle generation, optional candidate zoom/dossiers, and sealed-period controls.

The repository also includes parity and benchmark validation artifacts. The full discovery-year workload was intentionally **not** launched as part of the production-repair work; the supplied validation and discovery configs are intended to exercise the completed production path when the full run is started.

---

## In one sentence

**Quant Pipeline V3 is a GPU-accelerated, evidence-first research system built to search an enormous interaction space on one PC, preserve enough detail to investigate the weird stuff, and package the results so the next stage of research can actually understand what happened.**
