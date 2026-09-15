# Quant-Pipeline V3 — MASTER SPECIFICATION

> **Single source of truth for requirements, architecture, implementation
> contracts, validation semantics, performance design, and Sol/Codex operating
> instructions.**
>
> Recommended repository filename: `V3_MASTER_SPEC.md`

## How to Use This File

This document intentionally replaces the previous separate V3 requirements,
technical-specification, and implementation-guide documents.

Sol/Codex should need this **one Markdown file** to understand what V3 is
supposed to do and how it should be built.

The document has five functional layers:

1. **Research Requirements** — what V3 must accomplish and why.
2. **Reference Architecture** — how the system should be decomposed.
3. **Code-Level Implementation Contract** — stable interfaces and schemas.
4. **Copy-Ready Reference Implementation** — concrete Python implementations
   and module-by-module build code Sol can use directly.
5. **Operating Instructions** — how Sol/Codex should use the spec during the
   build.

### Authority / Priority

If two passages appear to conflict, use this priority:

```text
causality + sealed-data invariants
    >
research semantics / validation rules
    >
public data contracts and schemas
    >
reference architecture
    >
performance recommendations
```

Performance work never overrides correctness.

### Current Validation Timeline

For the initial V3 rebuild, preserve the current V2 research split:

```text
2025-05-01 ───────── 2026-04-30
DISCOVERY YEAR
Aggressive research. Folds/months/cross-fitting are diagnostics.

2026-05-01 ───────── 2026-08-31
SEALED REPLICATION / REAL OOS
Inaccessible during normal discovery.

2026-09-01 ───────── onward
FINAL HOLDOUT
Separately sealed until explicit later promotion.
```

The C-r5/A-r10 work done so far belongs to the **discovery-year research**, not
the sealed OOS layer.

### Clean-room V3 repository rule

The initial V3 build must be created in a **new project directory** and operate
as an independent Python project.

Required isolation:

- create a project-local `.venv`;
- do not install V3 packages into the user's global Python environment;
- do not make V3 import modules from V2 at runtime;
- do not make V3 depend on V2 caches, result directories, checkpoints, or
  generated artifacts;
- do not copy the large candle dataset into the V3 repository;
- locate the existing candle/source-data root and reference it read-only through
  the local machine configuration;
- V2 may be inspected read-only during implementation solely to port and
  parity-test authoritative semantics such as PIT identity, price adjustments,
  feature formulas, targets, bin/tie rules, and sealed-period behavior;
- once ported, V3 must run with V2 absent as long as the configured external
  source candle data remains available;
- never modify the V2 repository or the external source candle data during the
  V3 build.

Machine-specific paths and local environment files must be git-ignored.

---

# PART I — RESEARCH REQUIREMENTS

## Purpose

Quant-Pipeline V3 should turn V2 into a **reliable single-machine research engine** that can search broadly for real equity alpha, preserve strong conditional/tail/specialist effects, run unattended for long periods, reuse previous work, and produce standardized research data for GPT to analyze.

This document intentionally excludes institutional process that does not directly help this project. V3 does **not** need to behave like a bank or hedge fund's enterprise platform. It does need to borrow the parts of professional quant research that directly improve:

- edge discovery;
- statistical trustworthiness;
- coverage of interaction/tail/specialist alpha;
- computational efficiency;
- overnight reliability;
- reproducibility;
- and ease of GPT analysis.

The target workflow is:

> **GPT proposes feature ideas → V3 computes the research → V3 exports standardized data → GPT analyzes the findings → promising candidates move to separate execution testing.**

The pipeline itself should **not make trading recommendations**.

### Validation terminology

V3 uses the most recent one-year discovery period aggressively. Monthly,
chronological-fold, rolling, and cross-fitted results **inside that discovery
year are diagnostics**, not the true OOS test.

The project's real OOS/replication evidence comes only from the separately
sealed replication period after a candidate is frozen. A later final holdout
remains separately sealed as well.

---

# A. SEARCH COVERAGE AND EDGE DISCOVERY

## 1. Remove Single-Feature Performance as a Gate for Dual Testing

### Problem

V2 can restrict dual testing to features that first perform well individually.

This assumes that two useful features must each have standalone predictive power before their interaction is worth examining.

That assumption is false for many conditional relationships.

### Why It Matters

Two individually weak features can form a strong interaction.

Examples include:

- confirmation/disagreement states;
- exhaustion + flow combinations;
- regime indicators;
- reversal conditions;
- features that only become meaningful conditional on another feature.

Using single performance as a prerequisite can remove these relationships before the dual scanner ever sees them.

### V3 Fix

Calculate singles and keep them as useful research data, but **do not use single-feature performance as permission to enter canonical dual discovery**.

Every structurally compatible canonical concept should be eligible for dual testing.

---

## 2. Make the Main Dual Search Exhaustive at the Canonical-Concept Level

### Problem

There are thousands of feature specifications once different windows, scales, transforms, and representations are included.

Brute-forcing every variant against every other variant would create excessive compute, huge redundancy, and an enormous multiple-testing burden.

Restricting the search too aggressively creates the opposite problem: missed alpha.

### Why It Matters

We need broad interaction coverage without wasting most of the night evaluating near-duplicate representations.

### V3 Fix

Define one **canonical representation** for each feature concept and make the main dual search exhaustive across those canonical concepts.

Every compatible canonical concept should be tested against every other compatible canonical concept.

Variant/window expansion happens later only for concept pairs that justify deeper examination.

---

## 3. Clearly Define the Canonical Representation of Every Concept

### Problem

If the pipeline uses a canonical representation as its first-pass search, that representation cannot be arbitrary or silently change from run to run.

### Why It Matters

A poor canonical choice can make a good concept look uninteresting before variant expansion.

It also makes results difficult to compare across runs if "canonical" is not stable.

### V3 Fix

Every feature concept should have a declared canonical specification used for broad discovery.

The registry should preserve:

- concept identity;
- canonical window/scale;
- representation;
- family;
- availability timing;
- and definition hash.

Canonical definitions should change only deliberately.

---

## 4. Treat r3, r5, and r10 as Separate Views of the Relationship

### Problem

A relationship can work at one binning resolution and fail at another.

- r3 captures broad states;
- r5 captures medium/selective states;
- r10 isolates extreme tails.

More bins do not automatically mean better information.

### Why It Matters

We have already seen real examples where a broad r5 state survives but the narrower r10 tail fails.

If the highest resolution determines survival, valid relationships can be discarded.

### V3 Fix

Run and retain r3, r5, and r10 independently.

Do not allow r10 to automatically override r5 or r3.

Use agreement or disagreement across resolutions as research information in its own right.

---

## 5. Make Discovery Fully Direction-Neutral

### Problem

Any positive-effect requirement introduces a bias toward long/positive relationships.

### Why It Matters

Negative conditional returns can represent:

- short alpha;
- reversal;
- relative underperformance;
- market-neutral opportunities;
- useful hedge legs;
- or important confirmation for another strategy.

### V3 Fix

Positive and negative relationships should travel through the same discovery process.

Store direction explicitly rather than using sign as a survival filter.

---

## 6. Separate Active Edge From Frequency-Weighted Contribution

### Problem

A rare high-return state can appear weak if its return is averaged over every eligible observation, including observations where the signal is inactive.

For example, a +10 bp state active 1% of the time can look like approximately +0.10 bp when expressed as average contribution across the entire opportunity set.

### Why It Matters

This can systematically bury exactly the high-value selective tails we want GPT to notice.

### V3 Fix

Every result should clearly separate:

- **active edge:** average forward return when the state actually occurs;
- **state frequency;**
- **frequency-weighted opportunity contribution;**
- **interaction effect beyond the single-feature marginals;**
- **active observation count;**
- **independent opportunity count.**

No single metric should be ambiguously called "the effect."

---

## 7. Preserve Full Surface Shape Instead of Only the Winning Cell

### Problem

One winning cell does not tell us whether the relationship is broad and coherent or an isolated spike.

### Why It Matters

Two relationships with the same best-cell return can have very different credibility.

A smooth region or plateau is generally more interesting than one isolated cell surrounded by noise.

Surface shape can reveal:

- monotonic structure;
- thresholds;
- reversals;
- plateaus;
- disagreement states;
- extreme-tail behavior.

### V3 Fix

Keep full r3/r5/r10 surfaces as first-class outputs.

Also summarize:

- best-to-worst spread;
- neighboring-cell support;
- plateau/region size;
- cell populations;
- local direction;
- whether structure strengthens or weakens as resolution increases.

---

## 8. Judge the Selected Region, Not Unrelated Sparse Cells

### Problem

At high resolution, some cells may naturally have very few observations even when the selected region is well populated.

Using the sparsest unrelated cell as a major quality gate can reject a perfectly usable relationship.

### Why It Matters

Highly non-uniform or discrete features may never fill a 10×10 surface evenly.

The relevant question is whether the **state we care about** has enough data.

### V3 Fix

Prioritize:

- selected-cell/selected-region N;
- neighbor N;
- populated-cell fraction;
- effective number of populated states.

Do not allow an irrelevant empty corner of the surface to automatically kill an otherwise well-supported state.

---

## 9. Add Standardized Tail Ladders

### Problem

An interesting relationship may become substantially better as the state becomes more selective, or it may collapse when narrowed.

Without a standard tail view, that must be investigated manually.

### Why It Matters

The strongest opportunities may live in:

- top/bottom 20%;
- 10%;
- 5%;
- 2%;
- or 1%.

We want to know the trade-off between selectivity, edge, and frequency.

### V3 Fix

For relationships worth deeper analysis, calculate standardized tail ladders where appropriate.

For each tail depth report:

- active edge;
- frequency;
- independent opportunities;
- and chronological stability.

The pipeline does not choose the "best strategy"; it exposes the curve for GPT.

---

## 10. Add Standardized Horizon Ladders

### Problem

A signal may be strong at one horizon and weak at another.

A single target can hide whether alpha appears immediately, persists, reverses, or decays.

### Why It Matters

The return path is often as informative as the terminal return.

### V3 Fix

For interesting states, output the available forward-return path across compatible horizons such as:

1m, 2m, 5m, 10m, 15m, 30m, 60m, 120m, 240m, and EOD.

Do not automatically optimize the holding period. Provide the data.

---

## 11. Track Independent Opportunities From the Beginning

### Problem

Raw observation counts can dramatically overstate how many independent trading opportunities exist.

A continuing state sampled every five minutes can create many observations belonging to the same underlying trade.

### Why It Matters

This affects:

- scalability;
- statistical confidence;
- trades/day;
- concurrency;
- realistic P&L potential.

### V3 Fix

For important states report separately:

- raw observations;
- active signal observations;
- unique signal timestamps;
- non-overlapping opportunities;
- unique symbol-days;
- trades/day;
- average/max concurrency;
- effective independent N where practical.

---

# B. VALIDATION AND STATISTICAL TRUSTWORTHINESS

## 12. Use Chronological Cross-Fitted State Selection as a Discovery Diagnostic

### Problem

Selecting the best state using the full dataset and then reporting its performance across pieces of that same dataset still contains selection bias.

### Why It Matters

When many states are examined, some will look excellent by chance.

We want to know whether the rule used to choose the state transfers to unseen time periods.

### V3 Fix

For serious candidates, select the state on the training portions of each chronological fold and evaluate that frozen selection on the held-out fold.

Keep the full-sample surface for descriptive analysis, but distinguish it clearly from cross-fitted evidence.

---

## 13. Use Inference Appropriate to Intraday Dependence

### Problem

Intraday observations from the same session are not independent.

Longer-horizon targets can overlap even more heavily.

Naive observation-level statistics can therefore make confidence look stronger than it really is.

### Why It Matters

The pipeline should not confuse a huge row count with a huge number of independent bets.

### V3 Fix

Use session-aware/cluster-aware inference for intraday research and appropriately account for overlapping horizons.

The output should expose both raw N and the more realistic independent structure.

---

## 14. Keep Multiple-Testing Accounting Honest Across Research Stages

### Problem

The project searches:

- singles;
- canonical duals;
- resolutions;
- variant expansions;
- tails;
- horizons;
- specialist effects.

If later-stage searches are treated as though they were the only hypothesis tested, confidence can be overstated.

### Why It Matters

We want broad research without fooling ourselves about how much searching occurred.

### V3 Fix

Track distinct hypothesis families for:

- canonical discovery;
- resolution/state search;
- variant expansion;
- specialist analysis;
- tail/horizon follow-up.

The goal is not bureaucratic statistics. It is simply to ensure GPT can see how much selection preceded a result.

---

## 15. Preserve Complete Trial Accounting

### Problem

When a large search is interrupted, filtered, or reused from prior runs, it can be difficult to know whether the intended hypothesis universe was actually covered.

### Why It Matters

A result set should not be called exhaustive if thousands of intended tests silently never ran.

### V3 Fix

For each run, report expected hypotheses and classify them as:

- newly executed;
- safely reused;
- structurally excluded;
- unavailable;
- failed.

Any unexplained gap should be visible.

---

## 16. Track Symbol, Sector, and Time Concentration

### Problem

An apparently strong global result may actually be driven by:

- one stock;
- a small handful of stocks;
- one industry;
- one month;
- one unusual market period.

### Why It Matters

Concentrated alpha is not automatically bad, but GPT needs to know whether the relationship is broad or dependent on a narrow pocket.

### V3 Fix

Important results should expose:

- top symbol contribution;
- top-5 symbol contribution;
- sector/industry concentration where available;
- top month/period contribution;
- largest session contribution.

---

## 17. Keep Raw, Benchmark-Adjusted, and Residual Return Meaning Separate

### Problem

A relationship can look excellent in benchmark-adjusted returns while the underlying stock barely moves, or vice versa.

### Why It Matters

These imply very different eventual execution and hedging requirements.

### V3 Fix

Where multiple return bases exist, preserve them as separate fields and never describe them interchangeably.

GPT should be able to distinguish:

- raw stock return;
- benchmark-relative return;
- beta/residual return.

---

# C. SPECIALIST AND CONDITIONAL ALPHA

## 18. Make Per-Symbol Analysis a Standard Pipeline Stage

### Problem

Per-symbol analysis currently behaves more like an auxiliary workflow than a core discovery component.

### Why It Matters

The existing results have already shown that globally mediocre relationships can contain very strong symbol-specific effects.

### V3 Fix

Integrate a compact per-symbol analysis stage into normal discovery.

For each relevant relationship expose:

- number/fraction of symbols agreeing with the global direction;
- symbol-level effect dispersion;
- top contributors;
- concentration;
- number of symbols with meaningful activity.

---

## 19. Explicitly Detect Global Cancellation

### Problem

A global effect near zero can mean "nothing is happening," or it can mean strong positive and negative specialist effects are canceling.

### Why It Matters

The second case can contain excellent tradable structure that the global average completely hides.

### V3 Fix

Track cross-symbol sign disagreement and dispersion.

Flag globally weak relationships whose symbol-level distribution is unusually structured or wide.

This creates a dedicated specialist-discovery path.

---

## 20. Use a Cheap Specialist Probe Before Full Per-Symbol Expansion

### Problem

Full per-symbol r3/r5/r10 surfaces for every pair-target would generate huge compute and storage.

### Why It Matters

We want specialist discovery without making the pipeline explode.

### V3 Fix

Run a compact specialist probe broadly, likely using one medium resolution such as r5.

Only relationships showing meaningful heterogeneity receive detailed per-symbol expansion.

---

## 21. Require Enough Local Evidence for Specialist Results

### Problem

A symbol can appear spectacular because it has very few qualifying observations.

### Why It Matters

Rare local noise can easily masquerade as specialist alpha.

### V3 Fix

Per-symbol outputs should make sample size, independent opportunities, and concentration unavoidable.

Detailed specialist results should be interpreted in the context of their local N rather than raw return alone.

---

## 22. Expand Windows and Representations Hierarchically

### Problem

Testing every possible window combination globally is wasteful, but using only one window can miss scale-specific relationships.

### Why It Matters

A concept pair can be real while its useful timing exists at a different scale than the canonical representation.

### V3 Fix

Search in layers:

1. canonical concept pair;
2. confirm meaningful global or specialist structure;
3. expand that pair into alternate windows/scales/representations;
4. keep those expansion results labeled separately.

---

## 23. Measure Whether the Search Funnel Is Missing Useful Variants

### Problem

Any hierarchical search can miss cases where the canonical representation is weak but a variant is strong.

### Why It Matters

We should not simply assume the pruning policy is safe.

### V3 Fix

Periodically expand a small deterministic sample of pairs that failed the normal expansion gate.

Measure how often those rejected pairs contain meaningful variant-level structure.

Use that observed miss rate to decide whether the funnel should be broader.

This is a practical search-quality check, not a giant formal testing program.

---

# D. FEATURE AND COMPUTE ARCHITECTURE

## 24. Build a Shared Cross-Run Cache

### Problem

Many expensive artifacts are deterministic and unchanged between research runs, but run-local workflows can recompute them.

### Why It Matters

The intended V3 workflow involves frequent GPT-generated feature ideas.

Adding a few features should not require rebuilding the entire historical research universe.

### V3 Fix

Persist and reuse compatible:

- panels;
- targets;
- feature columns;
- reusable feature primitives;
- rank/bin representations;
- completed old-old dual results.

Nightly runtime should scale mainly with **new work**.

---

## 25. Use Component-Level Cache Lineage Instead of One Global Code Hash

### Problem

If cache compatibility depends on a hash of the entire project, an unrelated code change can invalidate hours of mathematically unchanged artifacts.

### Why It Matters

That defeats much of the benefit of cross-run caching.

### V3 Fix

Each artifact should depend only on the inputs and implementation components that mathematically determine it.

A report change should not invalidate targets.

A scanner change should not invalidate feature columns.

A feature-builder change should invalidate affected features without unnecessarily invalidating unrelated targets.

---

## 26. Make Large Caches Incremental Rather Than Monolithic

### Problem

A monolithic artifact can become invalid when only a small part of the underlying dataset changes.

### Why It Matters

As new sessions or symbols are added, V3 should not need to rebuild years of unchanged data.

### V3 Fix

Partition reusable artifacts at sensible boundaries so only affected portions need recomputation.

The exact partitioning can be decided during implementation, but incremental extension should be a design requirement.

---

## 27. Compile Features From Shared Primitives

### Problem

Thousands of feature specs reuse common calculations such as:

- returns;
- rolling sums;
- rolling means;
- rolling variance;
- highs/lows;
- volume aggregates;
- signed volume;
- ranks;
- OBV-like primitives.

### Why It Matters

Feature construction has been one of the largest measured runtime stages.

### V3 Fix

Treat feature generation as a dependency graph of reusable primitives rather than thousands of unrelated calculations.

Calculate common primitives once and reuse them wherever possible.

---

## 28. Optimize the Single-Symbol Feature Hot Path

### Problem

The feature workload is already partitioned by symbol, yet generic grouped-Pandas operations can still impose unnecessary overhead inside a single-symbol worker.

### Why It Matters

The i9-11900KF is capable, but several hours of CPU feature construction is still a major portion of a full run.

### V3 Fix

Profile the feature builder and optimize only the expensive repeated operations.

Where worthwhile, move the hottest rolling calculations to direct contiguous-array/NumPy/Numba-style computation.

Do not rewrite the entire feature library blindly.

---

## 29. Maintain Separate Durable, Research, and GPU-Hot Representations

### Problem

One storage format is not ideal for every task.

### Why It Matters

- Parquet/DuckDB are excellent for durable analytical data.
- Large dense arrays are better for repeated numerical access.
- Compact packed tensors are better for GPU scanning.

Trying to use one format everywhere increases overhead.

### V3 Fix

Formalize three layers:

1. **durable source/results:** DuckDB + Parquet;
2. **research cache:** memmaps / dense arrays / reusable intermediate artifacts;
3. **GPU hot path:** compact packed bins and numerical tensors.

Use each where it is strongest.

---

## 30. Split Exhaustive Dual Search Into Surface Discovery and Deep Validation

### Problem

Running expensive inference, detailed symbol diagnostics, and other second-pass calculations on every canonical pair-target would make the exhaustive search too slow.

### Why It Matters

The existing scanner is fast enough for the current restricted universe but not ideal for doing every expensive calculation across the full canonical universe.

### V3 Fix

Use two computational layers.

### Surface Discovery

Run exhaustively across the canonical universe and calculate:

- r3/r5/r10 cell counts;
- conditional returns;
- spread/topology;
- fold-level summaries;
- active edge/frequency;
- cheap specialist indicators.

### Deep Validation

Only surfaces with enough structure to justify further work receive:

- expensive robust inference;
- cross-fitted state evaluation;
- detailed per-symbol analysis;
- variant expansion;
- tail/horizon analysis.

The broad search remains exhaustive; only expensive follow-up is selective.

---

## 31. Keep the Deep-Validation Gate Broad

### Problem

A narrow p-value-style gate at the boundary between surface discovery and deep validation would recreate the same problem as the old single-survivor funnel.

### Why It Matters

Interesting relationships can be:

- moderate globally;
- specialist-heavy;
- broad but noisy;
- nonlinear;
- strongest only at one resolution.

### V3 Fix

The deep-validation gate should consider several structural signals and be deliberately permissive.

Its purpose is to avoid spending heavy compute on completely dead surfaces, not to decide what is tradable.

---

## 32. Improve GPU Data Reuse and Batching

### Problem

The 3080 Ti can process substantial work, but repeated CPU→GPU transfers, small jobs, and Python-level loops can leave GPU capability unused.

### Why It Matters

Replacing the GPU would not help if the current bottleneck is feeding it.

### V3 Fix

Organize scans around reusable blocks of:

- feature tiles;
- target tiles;
- packed bin data.

Reuse GPU-resident data for as many combinations as possible before eviction.

Overlap CPU preparation, GPU computation, and output writing when beneficial.

---

## 33. Profile Before Rewriting GPU Kernels

### Problem

It is easy to spend time building custom CUDA/Triton code without knowing whether kernel execution is actually the bottleneck.

### Why It Matters

The scanner may instead be limited by:

- CPU preparation;
- transfers;
- Python launch overhead;
- memory bandwidth;
- result writing.

### V3 Fix

Instrument the hot path and profile representative workloads before choosing low-level optimizations.

Only replace working Torch/CUDA operations when measurements show a meaningful wall-clock opportunity.

---

## 34. Correctly Measure Scanner Throughput

### Problem

A reported "tests/sec" number can be misleading if a single pair-target evaluation produces multiple resolutions.

### Why It Matters

Bad throughput definitions lead to bad runtime estimates and poor architecture decisions.

### V3 Fix

Track separate rates for:

- pair-targets/sec;
- resolution-tests/sec;
- observations/sec where useful.

Use pair-targets/sec as the primary measure for forecasting exhaustive scan runtime.

---

# E. RESOURCE MANAGEMENT FOR THE ACTUAL PC

## 35. Tune for the 11900KF / 32 GB RAM / RTX 3080 Ti / NVMe Machine

### Problem

The best resource settings for this workstation are not simply "use all threads and all memory."

### Why It Matters

The current machine has a strong GPU and CPU, but 32 GB RAM means memory pressure and Windows paging can destroy long-run performance.

### V3 Fix

V3 should use stage-specific resource profiles rather than one global setting.

The goal is maximum **stable throughput**, not maximum utilization.

---

## 36. Prevent CPU Oversubscription

### Problem

Using all 16 logical threads for multiple processes while numerical libraries also create internal threads can cause contention and memory pressure.

### Why It Matters

More workers can actually reduce throughput.

### V3 Fix

Control worker count and internal BLAS/OpenMP threading centrally.

Benchmark realistic worker counts for feature building rather than assuming 16 is optimal.

---

## 37. Keep a Real RAM Reserve

### Problem

Allowing research processes to consume nearly all 32 GB leaves Windows, filesystem caching, and other processes with too little memory.

### Why It Matters

Once the machine starts hard paging, a long run can become dramatically slower or unstable.

### V3 Fix

Reserve meaningful physical RAM for the OS and dynamically reduce concurrency before paging becomes severe.

RAM pressure should be treated as a scheduling signal, not something the pagefile should rescue.

---

## 38. Autotune GPU Batch Size From Available VRAM

### Problem

Static GPU batch settings can either waste VRAM or push the machine into OOM failures.

### Why It Matters

The 3080 Ti has 12 GB VRAM, which is enough for substantial tiling but still requires bounded operation.

### V3 Fix

Choose tile sizes based on available VRAM during preflight and allow safe adjustment if resource conditions change.

---

## 39. Use the NVMe Intentionally

### Problem

A fast NVMe helps only if active scratch/cache workloads actually live on it and result layout avoids pathological small-file behavior.

### Why It Matters

The pipeline performs substantial memmap, Parquet, DuckDB temp, cache, and result I/O.

### V3 Fix

Use the NVMe for:

- active shared cache;
- memmaps;
- DuckDB temp/spill;
- current-run scratch.

Check free space before starting long runs.

---

## 40. Compact Completed Result Shards

### Problem

Fine-grained output shards are good for resume behavior but can create thousands of small files that are inefficient to query and manage.

### Why It Matters

This is especially relevant on Windows/NTFS and when GPT later needs consolidated research tables.

### V3 Fix

Keep small execution shards while a stage is running, then compact completed results into larger analysis-oriented Parquet files.

Preserve shard metadata so resumability is not lost.

---

# F. RELIABILITY AND LOW-INTERVENTION RUNNING

## 41. Use One Canonical Pipeline DAG and One Normal Command

### Problem

Multiple scripts currently represent overlapping versions of the research workflow.

### Why It Matters

This creates uncertainty about:

- which command is current;
- which stages run;
- which dependencies are respected;
- which resume behavior applies.

### V3 Fix

Define one authoritative pipeline graph.

All command-line entrypoints should delegate to that same graph.

A normal research run should require one command.

---

## 42. Separate Research Configuration From Machine Configuration

### Problem

Research configs can contain machine-specific paths and hardware settings.

### Why It Matters

This mixes two unrelated concerns and makes configs harder to reuse or compare.

### V3 Fix

Research configuration should contain:

- universe;
- features;
- targets;
- grids;
- discovery rules.

A separate local machine profile should contain:

- paths;
- cache location;
- scratch location;
- CPU/RAM limits;
- GPU device/resource preferences.

---

## 43. Make Every Expensive Work Unit Independently Resumable

### Problem

A multi-hour stage should not need to restart because the PC was interrupted near the end.

### Why It Matters

Low-intervention overnight use depends on robust restart behavior.

### V3 Fix

Break large stages into deterministic work units that can be verified independently.

On restart, reconstruct required work, verify completed artifacts, and execute only missing/incompatible units.

---

## 44. Use Atomic Writes and Artifact Validation

### Problem

A crash during file creation can leave an artifact that exists but is incomplete.

### Why It Matters

A resume system must distinguish a valid completed result from a partial file.

### V3 Fix

Write incomplete outputs separately, validate them, then mark/promote them as complete atomically.

Cached artifacts should also have enough metadata to verify compatibility and integrity.

---

## 45. Automatically Recover From Resource Failures, Not Logic Failures

### Problem

Some failures are operational rather than research errors.

Examples:

- GPU batch too large;
- excessive memory pressure;
- temporary I/O interruption.

### Why It Matters

These should not require manual babysitting.

At the same time, automatically retrying real logic/correctness failures can hide serious problems.

### V3 Fix

Automatically adapt/retry known resource failures.

Stop immediately on things such as:

- causality violations;
- incompatible schemas;
- corrupt source data;
- numerical parity failures;
- invalid feature definitions.

---

## 46. Add Useful Runtime Telemetry

### Problem

When a 10–20 hour run is slow or stuck, the current state can be difficult to diagnose quickly.

### Why It Matters

We need to know whether the problem is:

- CPU;
- RAM;
- GPU;
- disk;
- DuckDB spill;
- a particular shard;
- or falling throughput.

### V3 Fix

Continuously record:

- current stage/work unit;
- completed/expected work;
- elapsed time;
- pair-targets/sec or relevant throughput;
- cache hit rate;
- RAM;
- CPU;
- GPU utilization;
- VRAM;
- disk usage/throughput;
- retries/errors.

This is operational data only, not research interpretation.

---

## 47. Benchmark Every Major Performance Change

### Problem

An optimization can make code more complicated without making the actual overnight job faster.

### Why It Matters

The only performance improvement that matters is lower wall-clock time or greater useful research throughput without changing results.

### V3 Fix

Maintain small representative benchmarks for:

- feature construction;
- target construction;
- surface scanning;
- deep inference;
- specialist analysis.

Keep optimizations only when they improve measured performance while preserving numerical behavior.

---

# G. GPT-NATIVE RESEARCH OUTPUT

## 48. End Every Run With One Standardized Analysis Bundle

### Problem

The current result tree contains valuable data but requires detailed knowledge of many folders and stage-specific files.

### Why It Matters

The intended workflow is for GPT to analyze the output repeatedly.

GPT should not need a custom map of the repository for every run.

### V3 Fix

Every completed research run should produce one consistent `analysis_bundle` containing:

- run manifest;
- feature registry;
- target registry;
- singles;
- canonical dual summaries;
- r3/r5/r10 comparisons;
- full surfaces;
- cross-fitted/fold results;
- specialist summaries;
- detailed per-symbol outputs where generated;
- tail ladders;
- horizon ladders;
- independent-opportunity statistics;
- trial accounting;
- runtime/performance metadata;
- schemas/data dictionary.

---

## 49. Include a GPT-Friendly Research Database

### Problem

Many Parquet files are efficient for pipeline execution but cumbersome for interactive cross-table analysis.

### Why It Matters

GPT should be able to ask broad forensic questions across an entire run.

### V3 Fix

Create a compact DuckDB database or equivalent query layer inside the analysis bundle.

It should make questions like these straightforward:

- Which pairs strengthen at r5 but deteriorate at r10?
- Which globally weak pairs contain strong specialists?
- Which states have the largest active edge with at least N independent opportunities?
- Which feature families interact repeatedly across targets?
- Which relationships are broad versus highly concentrated?
- Which tails persist across horizons?

The database provides data and convenient views, not recommendations.

---

## 50. Keep the Pipeline as a Data Generator, Not a Strategy Recommender

### Problem

Automated recommendations inside the same system that performs discovery blur the distinction between evidence and interpretation.

### Why It Matters

Our preferred workflow is to use GPT as the research analyst after the entire output is available.

### V3 Fix

V3 should stop at standardized research evidence.

It may calculate objective diagnostics, but it should not output:

- "best strategy";
- portfolio weights;
- trading recommendations;
- or narrative conclusions.

---

## 51. Keep SIP/Execution Research Downstream

### Problem

Alpha discovery and execution are different problems.

Adding spread/fill assumptions too early can obscure whether an underlying conditional return exists.

### Why It Matters

We first need to find potentially valuable states.

Then we can test whether the alpha survives realistic market execution.

### V3 Fix

Preserve the SIP exporter as a downstream tool.

For selected candidates, export exact signal/exit timestamps and obtain raw quote/trade data.

Marketable/passive/latency/fill analysis should be performed separately from the discovery engine.

---

## 52. Give GPT-Generated Feature Ideas a Standard Entry Format

### Problem

If every batch of new feature ideas requires editing several registry files and manually wiring pipeline stages, nightly research remains fragile.

### Why It Matters

The desired workflow depends on quickly turning new feature hypotheses into reproducible research jobs.

### V3 Fix

Define one standard feature-pack/request format containing the information the pipeline needs to validate and register new concepts.

Adding feature ideas should not require manual edits across unrelated components.

The exact implementation can be decided during the V3 build.

---

# H. OPERATING MODES

## 53. Incremental Nightly Mode

### Problem

Re-running the entire historical research universe whenever a few new concepts are added wastes most of the available compute.

### V3 Fix

The normal mode should:

1. validate new feature ideas;
2. reuse all compatible previous artifacts;
3. compute only missing feature/primitives;
4. run the new singles;
5. test new canonical concepts against the complete existing canonical bank;
6. test new concepts against one another;
7. perform normal structural/specialist follow-up;
8. produce the updated analysis bundle.

This should be the everyday research loop.

---

## 54. Full-Canonical Mode

### Problem

Incremental research is efficient, but the project also needs a way to periodically prove that the complete canonical search space has been covered under the current data/configuration.

### V3 Fix

Provide a full-canonical mode that runs the entire compatible canonical concept-pair universe on the current discovery snapshot.

This is the broad refresh/check mode.

---

## 55. Keep V3 a Strong Single-Machine System

### Problem

It would be easy to respond to scale by adding distributed infrastructure, services, schedulers, or a rewrite in another language.

### Why It Matters

That complexity creates maintenance burden and new failure modes without necessarily improving research on one workstation.

### V3 Fix

Keep the core stack centered on:

- Python;
- DuckDB;
- Parquet;
- NumPy/memmaps;
- CUDA/Torch or selectively optimized kernels;
- simple local caching/checkpointing.

The goal is to make the existing architecture more efficient and disciplined, not to turn the project into enterprise infrastructure.

---


# I. EDGE FORENSICS — SIFTING THE GOLD FROM THE PAYDIRT

The broad discovery engine tells us **where an interesting relationship may exist**. V3 also needs to tell GPT **what that relationship actually is**.

This section is deliberately important. A "printer" cannot be identified from a mean return and a t-stat alone. We need a standardized description of the edge's geometry, distribution, temporal behavior, cross-sectional behavior, frequency, persistence, concentration, and relationship to other discovered edges.

The pipeline still does not make a trading recommendation. It produces the evidence needed for GPT to understand the edge.

---

## 56. Freeze a Candidate Definition Before Deep Characterization

### Problem

Once an interesting relationship is found, it is easy for follow-up analysis to slowly mutate the rule:

- change the bin;
- change the tail;
- change the horizon;
- change the feature window;
- change the symbol subset;
- and keep whichever version looks best.

That makes it difficult to tell whether we are understanding an edge or continually redesigning it around the same historical data.

### Why It Matters

We need a stable reference point.

Otherwise every additional diagnostic becomes another opportunity to optimize the candidate after seeing the result.

### V3 Fix

When a relationship enters deep validation, create a **frozen candidate identity** containing the exact:

- feature definitions;
- target;
- resolution;
- state/region;
- direction;
- discovery source;
- data snapshot;
- and selection rule.

All forensic analysis should reference that frozen candidate.

Follow-up analyses may reveal better variants, but those variants become new explicitly identified candidates rather than silently changing the original one.

---

## 57. Produce a Standardized Edge Dossier for Every Serious Candidate

### Problem

Candidate information is currently distributed across surfaces, folds, symbol tables, backtests, and ad hoc analysis.

### Why It Matters

GPT should be able to open one candidate record and understand the complete nature of the edge without manually reconstructing it from many files.

### V3 Fix

Every candidate that reaches deep validation should receive one standardized **edge dossier**.

The dossier should combine the major research dimensions described below into one consistent package.

This becomes the primary unit GPT analyzes.

---

## 58. Describe the Full Return Distribution, Not Only the Mean

### Problem

Two states can both average +5 bp while having completely different behavior.

One could produce small, repeatable gains.

Another could lose most of the time and be rescued by a few enormous observations.

### Why It Matters

A repeatable "printer-like" edge should be distinguishable from a jackpot-driven average.

### V3 Fix

For each serious candidate, retain descriptive return-distribution statistics such as:

- mean;
- median;
- useful quantiles;
- win rate;
- average winner;
- average loser;
- downside tail;
- upside tail.

The purpose is not to optimize on these numbers. It is to show GPT what generates the mean.

---

## 59. Measure Return-Contribution Concentration

### Problem

An attractive historical edge can be dominated by a tiny number of trades, symbols, or sessions.

A normal win rate and high mean do not reveal this by themselves.

### Why It Matters

A candidate driven by three extraordinary events is fundamentally different from one that repeatedly generates small positive outcomes.

### V3 Fix

For each serious candidate, report how much of total gross return comes from:

- the largest individual observations/trades;
- the top 1% and 5% of outcomes;
- the largest sessions;
- the top symbols.

This complements the existing symbol/time concentration diagnostics and directly exposes "lottery-ticket" edges.

---

## 60. Measure the Alpha Path, Not Just the Terminal Target

### Problem

A 30-minute +6 bp result does not tell us whether the return:

- arrives in the first two minutes;
- rises steadily;
- peaks at minute 12 and gives half back;
- goes against us first;
- or appears only near the end.

### Why It Matters

The path tells us much more about the nature of the edge and later becomes essential for execution design.

Professional trading research cares about alpha decay because expected returns and transaction costs interact through time. V3 should expose that decay rather than reduce the signal to one terminal number.

### V3 Fix

For serious candidates, provide a standardized cumulative forward-return path through the available horizon.

Include descriptive quantities such as:

- time to meaningful positive return;
- time to peak expected return;
- return at several intermediate horizons;
- post-peak giveback;
- persistence/decay after the apparent peak.

The pipeline should expose the curve, not automatically select the optimum exit.

---

## 61. Measure Favorable and Adverse Excursion

### Problem

A final +5 bp return can hide very different paths.

One candidate may move directly in the expected direction.

Another may routinely go -15 bp before eventually finishing +5 bp.

### Why It Matters

This affects:

- risk;
- realistic execution;
- stop sensitivity;
- capital usage;
- and whether the effect is truly smooth/predictable or merely terminal.

### V3 Fix

For serious candidates, characterize the distribution of:

- maximum favorable excursion;
- maximum adverse excursion;
- time to each;
- and how much favorable move is later given back.

This remains descriptive research data.

---

## 62. Compress Repeated Observations Into Signal Episodes

### Problem

A state sampled every five minutes may remain active for 30 minutes and generate six rows.

Treating those rows as six independent instances obscures the real behavior.

### Why It Matters

For a tradable edge, we need to know whether the useful unit is:

- a new state entry;
- every repeated observation;
- a long persistent episode;
- or a transition out of the state.

### V3 Fix

In addition to observation-level data, group consecutive same-symbol activations into **signal episodes**.

Report:

- episode count;
- episode duration;
- return from first activation;
- return from later activations;
- and recurrence after the episode ends.

This makes the raw 5-minute research grid much easier to translate into actual opportunities.

---

## 63. Analyze State Entry, Persistence, and Exit Separately

### Problem

A profitable state does not necessarily mean that every moment spent inside that state has the same predictive value.

The real alpha may occur:

- when the stock first enters the state;
- only after it persists;
- when one feature changes while the other stays extreme;
- or immediately after the state breaks.

### Why It Matters

This can reveal the mechanism of an edge and prevent us from trading repeated stale observations as though each were new information.

### V3 Fix

For serious candidates, characterize:

- fresh entry into the state;
- first continuation;
- later persistence;
- exit from the state;
- re-entry after a gap.

Do not optimize among these automatically. Present the transition data to GPT.

---

## 64. Characterize Time-of-Day Behavior

### Problem

Intraday effects can be heavily dependent on market structure and time of day.

A global intraday mean can hide the fact that an edge exists only:

- near the open;
- around midday;
- late in the session;
- or before a same-day exit becomes impractical.

### Why It Matters

Time-of-day dependence tells us whether the edge is broad or structurally tied to a particular part of the session.

### V3 Fix

For serious intraday candidates, report performance and frequency across a **small fixed set of predetermined session buckets**.

This should be characterization, not a giant search over arbitrary clock intervals.

---

## 65. Characterize a Small Fixed Set of Market Regimes

### Problem

An edge may appear stable overall while actually existing only during one broad market environment.

### Why It Matters

Understanding whether the effect depends on market conditions helps GPT distinguish:

- structural relationships;
- crisis-only effects;
- trend-dependent behavior;
- volatility-dependent behavior;
- liquidity-sensitive effects.

### V3 Fix

Use a small predefined regime panel for characterization, such as broad:

- market volatility;
- market trend;
- breadth;
- market liquidity.

Do not create hundreds of regime combinations.

The goal is to explain the edge, not optimize it into existence.

---

## 66. Characterize Cross-Sectional and Liquidity Dependence

### Problem

A signal can appear broad across symbols while its economics are actually concentrated in illiquid names, expensive stocks, or one liquidity segment.

### Why It Matters

This strongly affects eventual tradability and tells us whether the relationship is a universal market behavior or a specialist phenomenon.

### V3 Fix

Where the source data supports it, characterize serious candidates across a few broad cross-sectional buckets such as:

- liquidity/volume;
- spread;
- price;
- size/universe tier.

Keep the number of axes limited and predetermined.

---

## 67. Report Discovery-to-Cross-Fitted Diagnostic Degradation Explicitly

### Problem

A candidate can look excellent in the discovery surface but substantially weaker under cross-fitted evaluation.

That degradation is easy to overlook when the two results live in separate reports.

### Why It Matters

The size of the haircut is itself information about how much of the original result was probably selection noise.

Research on backtest overfitting emphasizes that the winner of a large search cannot be judged as though it were specified in advance.

### V3 Fix

Every serious candidate should show side-by-side:

- discovery/full-sample active edge;
- cross-fitted discovery-year diagnostic edge;
- ratio or absolute degradation;
- best fold;
- median fold;
- worst fold;
- sign consistency.

GPT should see the haircut immediately. These fold/cross-fitted numbers remain
**in-sample discovery diagnostics**, not the sealed replication result.

---

## 68. Measure Rolling Historical Persistence

### Problem

A few broad chronological folds can miss gradual edge decay or a regime-local phenomenon.

### Why It Matters

A "printer" should ideally not depend entirely on one early historical period.

We need to know whether the effect:

- appears throughout history;
- strengthens;
- weakens;
- disappears and returns;
- or begins only recently.

### V3 Fix

For serious candidates, store a rolling or fixed-period history of:

- active edge;
- frequency;
- independent opportunities.

This is descriptive persistence analysis, not an instruction to select the best historical interval.

---

## 69. Measure Long/Short and Tail Asymmetry

### Problem

A feature pair may have strong predictive structure on one side of the surface but no corresponding mirror effect on the other.

Assuming symmetry can hide the actual nature of the relationship.

### Why It Matters

A genuine exhaustion/reversal state may be inherently asymmetric because market behavior, liquidity, shorting, and investor responses are asymmetric.

### V3 Fix

Where applicable, explicitly compare corresponding positive/negative or high/low tails.

Store asymmetry rather than forcing the signal into a symmetric interpretation.

---

## 70. Build an Edge Redundancy and Overlap Map

### Problem

A large discovery engine can find the same underlying phenomenon many times under different feature names, windows, or targets.

Ten "successful" candidates may really represent one edge.

### Why It Matters

Without a redundancy map:

- GPT may overestimate how much independent alpha has been found;
- repeated versions of one idea can dominate the candidate list;
- later portfolio combination can accidentally stack the same exposure several times.

### V3 Fix

For serious candidates, quantify similarity using information such as:

- signal timestamp overlap;
- symbol overlap;
- return/P&L-series correlation where available;
- feature-family similarity;
- state overlap;
- horizon similarity.

This is descriptive clustering, not automatic portfolio construction.

---

## 71. Group Near-Duplicate Discoveries Into Edge Families

### Problem

Candidate-level output can become overwhelming when dozens of slightly different variants describe the same market behavior.

### Why It Matters

We want GPT to reason about underlying **edge families**, not confuse every window/resolution variation with a new independent discovery.

### V3 Fix

Create descriptive edge-family groupings based on the redundancy/overlap data.

Preserve every candidate underneath the family.

The grouping should make it easy to see:

- the common phenomenon;
- strongest variants;
- broadest variants;
- specialist variants;
- and where the variants disagree.

---

## 72. Report Gross Opportunity Economics Without Pretending It Is Executed P&L

### Problem

Active edge alone favors rare high-return states.

Frequency alone favors weak high-frequency states.

Neither tells us the gross economic scale of the opportunity.

### Why It Matters

A potential "printer" needs some combination of:

- repeatability;
- edge magnitude;
- enough independent opportunities.

### V3 Fix

For serious candidates, report simple gross opportunity descriptors such as:

- active gross bp/opportunity;
- independent opportunities/day;
- gross additive bp/day under a clearly stated equal-opportunity convention;
- average concurrency;
- approximate gross cost budget implied by the edge.

These are **not executed P&L** and should be labeled accordingly.

SIP/quote analysis still determines whether that gross opportunity is capturable.

---

## 73. Make the Edge Dossier a Required Handoff Before Execution Research

### Problem

It is tempting to jump from an exciting cell directly into a backtest or SIP-fill experiment.

### Why It Matters

That can waste time executing an effect whose underlying nature is still poorly understood.

### V3 Fix

Before a candidate moves to execution research, require a complete enough edge dossier covering:

1. frozen candidate definition;
2. active edge and frequency;
3. independent opportunities;
4. full surface/topology;
5. r3/r5/r10 behavior;
6. return distribution;
7. contribution concentration;
8. chronological/cross-fitted discovery-year diagnostic behavior;
9. rolling persistence;
10. horizon/alpha path;
11. favorable/adverse excursion;
12. signal-episode/transition behavior;
13. symbol/specialist structure;
14. time-of-day behavior;
15. fixed broad regime behavior;
16. return basis;
17. overlap/redundancy with other edges.

The dossier does not decide whether to trade.

It gives GPT enough information to understand what has actually been discovered before asking whether it can be executed.

---

# J. SUSTAINED SINGLE-MACHINE PERFORMANCE

## 74. Calibrate the Machine at the Start of a Research Run

### Problem

Fixed worker counts and tile sizes can be wrong when free RAM, GPU memory, background load, or dataset shape changes.

### Why It Matters

A configuration that is fastest in one workload can be unstable or slower in another.

### V3 Fix

Before a major run, perform lightweight resource calibration or use recently measured machine-profile values to choose safe:

- CPU concurrency;
- DuckDB concurrency/memory;
- GPU tile size;
- prefetch depth.

The goal is predictable overnight throughput on the actual workstation.

---

## 75. Keep CPU Preparation, GPU Scanning, and Result Writing From Blocking Each Other

### Problem

Even a fast GPU can sit idle if the next block is not ready, while the CPU can sit idle waiting for GPU output to be written.

### Why It Matters

The current 3080 Ti has enough compute that pipeline coordination may matter as much as low-level kernel speed.

### V3 Fix

Design the compute flow so that, where practical:

- the CPU prepares the next work unit;
- the GPU processes the current unit;
- completed results are written separately.

This is a pipeline-efficiency requirement, not a mandate for a particular technical implementation.

---

## 76. Monitor Sustained Clocks and Thermals During Long Runs

### Problem

A benchmark lasting two minutes can look excellent while a 15-hour run gradually loses performance because of:

- CPU thermal throttling;
- GPU thermal/power limits;
- reduced clocks;
- memory pressure;
- background system activity.

### Why It Matters

We care about overnight throughput, not short benchmark peaks.

### V3 Fix

Include sustained CPU/GPU clock, temperature, power, and throughput trends in runtime telemetry.

A slowdown caused by hardware conditions should be distinguishable from a software regression.

---

## 77. Manage Cache and Scratch Space as a Bounded Resource

### Problem

Cross-run caching can eventually fill the NVMe with obsolete run artifacts, stale variants, temporary files, and duplicate compacted outputs.

### Why It Matters

A full disk can kill an unattended run and makes a useful cache turn into an operational problem.

### V3 Fix

Track:

- cache size;
- scratch size;
- free-space reserve;
- artifact last use;
- artifact lineage.

V3 should make it straightforward to remove safe-to-regenerate stale cache while protecting currently referenced artifacts and immutable source data.

---


# K. FINAL EDGE-FORENSICS REFINEMENTS

These additions close the remaining practical gaps between "we found a statistically interesting cell" and "we actually understand the edge well enough to decide whether it deserves execution research."

---

## 78. Measure Cross-Fitted Discovery-Year Surface Calibration

### Problem

A candidate can have one strong selected cell while the rest of the discovered surface contains little genuine predictive information.

A good-looking winning cell does not tell us whether the surface learned on one period generalizes to unseen periods.

### Why It Matters

A repeatable edge is more convincing when states predicted to have higher returns actually rank higher on held-out data.

This is stronger evidence than simply finding one historical maximum.

### V3 Fix

For candidates entering deep validation, use the training portion of each
chronological discovery-year fold to estimate the expected return associated
with each state or region.

Apply that frozen surface to the held-out discovery-year fold and report:

- predicted-state return versus realized return;
- rank ordering of states;
- OOF surface spread;
- an OOF calibration slope or equivalent descriptive calibration measure;
- an information-coefficient-style rank relationship where appropriate.

For continuous single features, retain conventional rank/quantile diagnostics where useful.

For duals, the emphasis should be whether the **surface learned in other
parts of the discovery year orders the held-out discovery-year observations
correctly**.

This is a cross-fitted discovery diagnostic. It must never be labeled as the
project's true OOS result; the sealed replication period remains the actual OOS
test.

---

## 79. Decompose the Dual Into Marginal Effects and True Interaction Lift

### Problem

A strong A × B state may simply be a strong A signal with an irrelevant B condition attached.

### Why It Matters

If the second feature adds nothing, we have not discovered a new interaction.

This matters for:

- understanding the mechanism;
- reducing redundant features;
- avoiding needless rule complexity;
- identifying genuinely complementary signals.

### V3 Fix

For every serious dual candidate, place side-by-side:

- unconditional return;
- return conditioned on A alone;
- return conditioned on B alone;
- return conditioned on A and B together;
- incremental lift of A × B beyond a reasonable additive/marginal baseline.

The pipeline should not decide that the interaction is "good" or "bad." It should make clear **what the second feature actually adds**.

---

## 80. Add Event-Aligned Pre-Signal and Post-Signal Paths

### Problem

The existing horizon ladder mainly describes what happens after a signal.

It may not show the price/flow path that led into the state.

### Why It Matters

The pre-signal path helps GPT understand whether the state represents:

- exhaustion after a run;
- continuation;
- a sudden reversal;
- absorption;
- delayed reaction;
- or another recognizable market behavior.

It can also expose cases where most of the apparent edge already occurred before the signal was observable.

### V3 Fix

For fresh signal episodes, align observations around first activation and retain a standardized event path covering a reasonable period before and after the signal.

Where available, include:

- raw return path;
- benchmark-adjusted path;
- residual path;
- relevant feature evolution.

Keep the window predetermined and descriptive rather than optimizing its endpoints.

---

## 81. Measure State Turnover and Autocorrelation

### Problem

Episode duration alone does not fully describe how sticky a state is across decision timestamps.

### Why It Matters

A persistent state and a rapidly rotating state have very different:

- independent opportunity counts;
- turnover;
- execution requirements;
- and interpretations.

### V3 Fix

For serious states, report descriptive persistence measures such as:

- probability of remaining in the state at the next decision;
- probability after several decisions;
- selected-name overlap from one timestamp to the next;
- median episode duration;
- re-entry frequency.

For continuous features where appropriate, retain rank-autocorrelation-style diagnostics.

---

## 82. Measure Cross-Sectional Simultaneity

### Problem

Twenty symbol signals on one day may actually be twenty manifestations of one common market event occurring at the same timestamp.

Counting them as twenty independent opportunities can materially overstate breadth and independence.

### Why It Matters

A printer built from many independent opportunities is different from a strategy that occasionally fires across the entire market at once.

### V3 Fix

For serious candidates, report:

- unique signal timestamps;
- average signals per active timestamp;
- largest simultaneous cluster;
- fraction of signals occurring in clusters of 2+, 5+, and 10+ names;
- contribution from the largest timestamp clusters;
- return correlation among simultaneous names where practical.

This should feed the interpretation of independent opportunity count.

---

## 83. Add Practical Leave-the-Best-Out Sensitivity

### Problem

Concentration metrics can show that the best symbol or month matters, but they do not directly show what the edge looks like without those historical winners.

### Why It Matters

A candidate that remains clearly recognizable after removing its historical heroes is qualitatively different from one that disappears immediately.

### V3 Fix

For serious candidates, report a small fixed set of descriptive sensitivity views such as:

- remove the best contributing symbol;
- remove the top five contributing symbols;
- remove the best month;
- remove the largest few sessions;
- remove or winsorize the most extreme small fraction of outcomes.

Do not search over arbitrary removal rules.

These are stress descriptions, not new optimized strategies.

---

## 84. Characterize Eligibility and Data-Coverage Composition

### Problem

Different features and targets can have different history requirements, missingness, and eligibility patterns.

An apparent edge can partly reflect **which observations were eligible**, rather than the intended economic state.

### Why It Matters

A relationship that exists only because one feature happens to be valid for a particular era or subset of securities is very different from a broad structural edge.

### V3 Fix

For serious candidates, report:

- eligible observations as a fraction of the relevant universe;
- coverage through time;
- symbol coverage;
- whether eligibility materially changes around the selected state;
- whether the candidate population differs sharply from the feature's normal eligible population.

The goal is to make data-composition artifacts visible.

---

## 85. Check State-Boundary Continuity

### Problem

A candidate can depend too precisely on an arbitrary bin boundary.

For example, the 90th percentile may look excellent while observations immediately below it behave completely differently for no coherent reason.

### Why It Matters

A real underlying relationship often has some continuity or interpretable threshold behavior.

A result that depends on a razor-thin quantile boundary deserves more skepticism.

### V3 Fix

Use the existing surface and tail information to show behavior immediately around the selected boundary.

For serious candidates, make it easy to see:

- selected region;
- directly adjacent states;
- nearby percentile/tail behavior;
- whether the response changes smoothly, plateaus, or jumps abruptly.

Do not automatically optimize the boundary.

---

## 86. Add Conditional Baseline Comparisons

### Problem

A candidate can look strong partly because it occurs in symbols or times that already have unusual unconditional returns.

### Why It Matters

We need to know whether the feature state adds information beyond obvious composition effects.

### V3 Fix

Where appropriate and data-supported, characterize the candidate relative to a small number of predetermined baselines such as:

- the same symbol's normal return at that time of day;
- the same broad market/time bucket;
- benchmark-adjusted and residual return bases already maintained by the pipeline.

This should remain descriptive and standardized, not become an open-ended matching exercise.

---

## 87. Maintain a Central Edge Registry and Candidate Lifecycle

### Problem

Large-scale discovery will repeatedly find related versions of the same phenomenon.

Without a central registry it becomes easy to:

- lose track of which rule was frozen;
- rerun the same analysis;
- confuse a new variant with a new independent edge;
- forget which candidates already went through SIP/execution research.

### Why It Matters

The research system needs memory even though it should not make recommendations.

### V3 Fix

Maintain a machine-readable edge registry containing candidate identity, lineage, edge-family membership, and factual lifecycle state such as:

- discovered;
- deep validation requested;
- dossier complete;
- SIP data requested/available;
- execution analysis available;
- frozen for untouched replication/final validation;
- untouched validation recorded;
- superseded by another explicitly linked variant.

The registry should contain evidence and status, not an automated "buy/drop" judgment.

---

## 88. Report a Gross Cost-Budget Curve Before SIP Testing

### Problem

A statistically strong candidate may have too little gross edge to tolerate realistic trading friction.

Conversely, a slower high-edge state may have substantial room for execution cost.

### Why It Matters

Gross return magnitude, alpha speed, and frequency together determine whether execution research is worth spending time on.

### V3 Fix

Before SIP simulation, report purely arithmetic gross cost-budget information:

- gross active edge by horizon;
- gross break-even total round-trip cost;
- gross break-even cost per side under the stated one-leg convention;
- how that budget changes across the alpha-decay path.

Clearly label this as a **gross research cost budget**, not realized execution P&L.

---

# L. FINAL COMPUTE-ARCHITECTURE REFINEMENTS

These additions focus on using the current 11900KF / 32 GB RAM / RTX 3080 Ti / NVMe machine as efficiently as possible without turning V3 into a complicated infrastructure project.

---

## 89. Build a Compact Canonical Discovery Plane

### Problem

The full float32 feature cache is far larger than system RAM.

Using large floating-point feature arrays as the primary representation for exhaustive canonical dual scanning creates unnecessary I/O and memory traffic once rank/bin state has already been determined.

### Why It Matters

The exhaustive canonical search mostly needs:

- compact feature state/bin information;
- targets;
- validity;
- fold/session/symbol identifiers.

A compact scan plane can be dramatically smaller than the full feature cache and much easier to stream predictably from NVMe.

### V3 Fix

Create a dedicated canonical discovery representation using the smallest safe types for the required information.

Where the existing bin semantics permit, store one compact rank/bin code from which r3/r5/r10 states can be derived rather than maintaining redundant large matrices.

Keep raw feature values separately for forensic work.

---

## 90. Compact and Reuse Validity, Fold, Session, and Symbol Metadata

### Problem

Repeatedly reconstructing or transferring eligibility masks, fold IDs, session IDs, symbol IDs, and target validity wastes memory bandwidth and compute.

### Why It Matters

These structures are reused across enormous numbers of pair-target evaluations.

### V3 Fix

Precompute and share compatible metadata at the appropriate grid/target level.

Use compact integer/bit representations where safe.

Targets with compatible alignment/validity should reuse the same metadata rather than rebuilding it pair by pair.

---

## 91. Schedule Pair Tiles for Memory Locality

### Problem

An arbitrary pair-processing order can cause repeated loading of feature data from NVMe/RAM and repeated transfers to the GPU.

### Why It Matters

The dataset is much larger than available RAM, so access pattern matters.

The scanner should behave like a blocked numerical kernel, not random access over a giant feature store.

### V3 Fix

Order exhaustive work around feature tiles:

> feature block A × feature block B × compatible target block.

Load/reuse a block for many combinations before moving on.

Choose deterministic tile ordering that favors sequential/local access and GPU reuse.

---

## 92. Batch and Reuse Compatible Target Blocks

### Problem

Even with good pair batching, repeatedly looping over targets or reloading targets can add CPU overhead and transfer cost.

### Why It Matters

Many targets share the same observation grid and similar validity structure.

### V3 Fix

Group compatible targets into reusable target blocks.

Keep a target block resident long enough to evaluate many feature-pair tiles when memory permits.

Benchmark the target-batch dimension alongside feature-tile dimensions.

---

## 93. Reuse GPU Allocations and Avoid Unnecessary Cache Clearing

### Problem

Frequent GPU allocation/free operations and aggressive cache clearing can add overhead and fragmentation.

### Why It Matters

PyTorch already uses a caching allocator.

Clearing unused cached memory does not create additional memory for PyTorch itself and can defeat reuse if called unnecessarily.

### V3 Fix

Prefer long-lived preallocated/reusable input, output, and workspace buffers for stable scan shapes.

Do not clear the CUDA allocator in hot loops unless profiling demonstrates a real fragmentation or coexistence problem.

Track allocator statistics when diagnosing VRAM issues.

---

## 94. Use Bounded Pinned Buffers and Asynchronous Double Buffering

### Problem

Host-to-device transfer can become a bottleneck, but pinning too much host RAM is also harmful on a 32 GB workstation.

### Why It Matters

The goal is to hide transfers behind useful computation without starving Windows or the CPU feature pipeline.

### V3 Fix

Where profiling shows benefit, maintain a small bounded pool of pinned host staging buffers.

Use asynchronous transfer/compute overlap so that:

- CPU prepares N+1;
- GPU processes N;
- writer handles N-1.

Pinned memory must have a strict budget and should not become a general storage layer.

---

## 95. Avoid Unnecessary Pandas Materialization in Large Intermediate Paths

### Problem

Converting large Arrow/DuckDB results into Pandas and then into NumPy can create extra copies and temporary memory spikes.

### Why It Matters

On a 32 GB machine, avoidable copies can reduce throughput or trigger paging.

### V3 Fix

For large numerical paths, prefer direct Arrow/native-buffer/NumPy/memory-map handoffs where practical.

Use Pandas where its semantics are genuinely useful, not automatically as the intermediate representation for every stage.

---

## 96. Use Different Compute Engines for Tabular Work and Numerical Hot Loops

### Problem

No one Python dataframe/numerical engine is best for:

- joins and filtering;
- lazy scans;
- grouped reshaping;
- custom rolling numerical kernels.

### Why It Matters

Trying to force every feature operation through one abstraction can leave a lot of CPU performance unused.

### V3 Fix

Benchmark a division of labor such as:

- DuckDB and/or a lazy columnar engine for large tabular scans, joins, projections, and filtering;
- NumPy/Numba-style compiled numerical kernels for the hottest custom rolling primitives;
- Pandas only where it remains competitive or substantially simpler.

Choose per workload based on measured wall-clock performance and memory use.

---

## 97. Define an Explicit Numerical-Precision Contract

### Problem

Aggressively compacting or accelerating the pipeline can silently change numerical results if input, accumulation, or reduction precision is reduced without a clear policy.

### Why It Matters

Speed improvements are useless if they change which cells, candidates, or rankings are produced.

### V3 Fix

Define which data can safely use compact types and which operations require higher-precision accumulation.

For example:

- bins/IDs use compact integer types;
- feature/target hot arrays may use float32 where validated;
- critical aggregates/reductions use enough precision to preserve parity.

Every optimized path must remain within declared CPU/reference tolerances.

---

## 98. Make Cache Retention Value-Aware

### Problem

A cross-run cache can consume the entire NVMe if every artifact is retained indefinitely.

But deleting everything by age can throw away expensive high-value artifacts.

### Why It Matters

Cache space should be spent on artifacts that save meaningful future compute.

### V3 Fix

Track basic cache economics such as:

- artifact size;
- build time/cost;
- last use;
- reuse count;
- current lineage references;
- whether the artifact is cheap or expensive to reproduce.

Protect high-value canonical artifacts aggressively.

Allow safe regeneration of cheap, stale, or one-off temporary expansions when space is needed.

---

## 99. Optimize Final Analytical Storage for Repeated GPT Queries

### Problem

Execution-friendly shards are not necessarily efficient for repeated cross-table analysis.

### Why It Matters

Once a run finishes, GPT will repeatedly query relationships across candidates, surfaces, symbols, folds, and horizons.

### V3 Fix

After successful completion:

- compact compute shards into appropriately sized analytical Parquet files;
- create the GPT-facing DuckDB database/views;
- organize common filter dimensions for efficient scans;
- avoid thousands of tiny files in the final bundle.

The execution representation and the analysis representation do not need to be identical.

---

## 100. Benchmark Cold, Warm, and Incremental Runs Separately

### Problem

A pipeline can appear fast because it is benefiting from a warm OS cache or already-built artifacts, while full rebuild performance remains poor.

The opposite is also true: cold full-run timing can hide how fast the normal incremental research loop will be.

### Why It Matters

We need honest expectations for the three workloads we actually care about.

### V3 Fix

Track separate benchmark profiles for:

- cold/full rebuild;
- warm/full-canonical run with reusable caches;
- normal incremental new-feature run.

Report wall-clock time and the dominant stage for each.

---

## 101. Add a Stall/Heartbeat Watchdog for Overnight Runs

### Problem

A process can remain alive while making no useful progress because of deadlock, pathological spill, blocked I/O, or an unexpectedly slow shard.

### Why It Matters

A run that silently stalls at 2 AM is almost as bad as one that crashes.

### V3 Fix

Use the existing telemetry/STATUS concept to track a heartbeat and useful-work counters.

If no meaningful progress occurs for an abnormal period:

- record the diagnostic state;
- distinguish expected long work from a true stall;
- safely fail/restart the affected work unit where possible.

Do not restart endlessly.



# M. NON-NEGOTIABLE V3 INVARIANTS

These are not new research features. They are V2 strengths that V3 must preserve while the architecture is consolidated and accelerated.

---

## 102. Preserve the Existing Point-in-Time and Causality Guarantees

### Problem

A major V3 refactor can accidentally weaken protections that already work in V2.

Speed and convenience are not worth introducing subtle leakage.

### Why It Matters

A fast pipeline with compromised timing semantics can manufacture extremely convincing false alpha.

### V3 Fix

Treat the following as hard non-regression requirements:

- immutable/fingerprinted source snapshots;
- point-in-time universe membership;
- stable security identifiers;
- split/price-basis consistency;
- explicit feature availability time;
- explicit decision time;
- explicit entry/exit timing;
- no use of future bars when constructing a feature;
- deterministic feature/target definitions;
- CPU/GPU numerical parity within declared tolerances;
- sealed replication/final-holdout data remaining inaccessible to ordinary discovery runs.

Any V3 optimization must preserve these guarantees.

---

## 103. Keep a Truly Untouched Final Validation Stage

### Problem

Cross-fitting and OOF analysis substantially improve trustworthiness, but the research process still repeatedly examines the discovery dataset while developing features, variants, diagnostics, and execution ideas.

Eventually we need one piece of data that has not participated in that iterative process.

### Why It Matters

The strongest historical candidate can still be the winner of a huge amount of human/GPT-guided searching.

A printer should ultimately survive data that was not used to discover, diagnose, refine, or choose it.

### V3 Fix

Preserve the existing sealed replication/final-holdout concept.

Ordinary nightly/full-canonical discovery must never access it.

Only after:

1. the candidate definition is frozen;
2. the edge dossier is complete;
3. the execution rule/cost methodology is frozen;
4. no further parameter changes are allowed for that candidate;

should an explicit promotion step evaluate the untouched data.

The result should be recorded once and linked to the candidate registry.

If the candidate is redesigned afterward, the redesign is a new candidate and must not inherit the old untouched result as though it were still unseen.

This stage is intentionally rare and separate from routine research.

---

## 104. Define Practical Runtime Targets Without Sacrificing Coverage

### Problem

Performance work can drift into optimizing benchmarks without a clear operational goal.

### Why It Matters

The purpose of V3 optimization is to make broad, trustworthy research routinely usable on the current workstation.

### V3 Fix

Use practical wall-clock objectives for the current machine:

- normal incremental feature research should comfortably fit into an unattended overnight cycle;
- a full-canonical refresh should target roughly the user's acceptable ~20-hour window where achievable;
- recovery/resume should prevent ordinary failures from turning that into a full restart;
- no runtime target is allowed to justify weakening causal controls, canonical coverage, or numerical parity.

These are design goals, not hard promises before profiling.

---


## REQUIRED EDGE DOSSIER OUTPUT

For a candidate that reaches deep validation, V3 should make the following information available in one standardized location.

### Identity
- candidate ID;
- features and exact definitions;
- target;
- direction;
- resolution/state/region;
- data snapshot;
- selection origin.

### Economic Shape
- active edge;
- state frequency;
- independent opportunities/day;
- opportunity contribution;
- gross additive opportunity;
- return basis;
- gross break-even cost budget by horizon.

### Distribution
- mean;
- median;
- win rate;
- key quantiles;
- average winner/loser;
- top-outcome contribution concentration.

### Surface Geometry
- full r3/r5/r10 surfaces;
- selected region;
- cell populations;
- neighbor support;
- plateau size;
- best/worst spread;
- tail ladder;
- boundary continuity;
- cross-fitted discovery-year surface calibration/ranking;
- A marginal, B marginal, and incremental A×B interaction lift.

### Time Structure
- cross-fitted folds;
- discovery-to-cross-fitted diagnostic degradation;
- rolling historical edge/frequency;
- horizon ladder;
- pre-signal and post-signal event path;
- cumulative alpha path;
- time to 25% / 50% / 75% of terminal or peak edge where meaningful;
- time to peak;
- decay/giveback;
- favorable/adverse excursion;
- time-of-day.

### Signal-Episode Structure
- fresh entries;
- persistent observations;
- episode duration;
- state autocorrelation/persistence;
- re-entries;
- state exits/transitions;
- unique active timestamps;
- simultaneous-signal cluster sizes.

### Cross-Sectional Structure
- per-symbol effect distribution;
- specialist concentration;
- top-symbol/top-5 contribution;
- simultaneous-name concentration;
- sector concentration where available;
- broad liquidity/size/spread dependence;
- eligibility and data-coverage composition.

### Market Context
- small fixed set of broad market-regime slices;
- long/short or high/low asymmetry where meaningful.

### Relationship to Other Research
- signal overlap;
- return-series similarity;
- feature-family similarity;
- edge-family membership;
- candidate lineage in the central edge registry.

### Execution Handoff
- exact signal timestamps;
- planned/reference target exit timestamps;
- enough identifiers for the SIP exporter;
- clear statement that gross research returns are not executed P&L;
- whether the candidate remains discovery-only, execution-tested, or frozen for untouched validation.

This dossier is the core "gold-sifting" product of V3.


# V3 BUILD ORDER

## Phase 1 — Correct the Research Funnel

Implement first because these determine whether good alpha is found and represented correctly.

1. Remove single-survivor dual gating.
2. Make canonical dual discovery exhaustive.
3. Stabilize canonical concept definitions.
4. Make discovery sign-neutral.
5. Treat r3/r5/r10 independently.
6. Separate active edge, contribution, and interaction effect.
7. Preserve full surfaces and selected-region populations.
8. Track independent opportunities.
9. Add chronological cross-fitted state validation.
10. Preserve distinct raw/benchmark/residual semantics.

---

## Phase 2 — Capture and Understand Conditional Alpha

1. Integrate per-symbol summaries.
2. Detect global cancellation.
3. Add lightweight specialist probes.
4. Add hierarchical variant/window expansion.
5. Add tail ladders.
6. Add horizon/alpha-path ladders.
7. Add concentration and return-distribution diagnostics.
8. Add signal-episode and state-transition analysis.
9. Add time-of-day and small fixed regime characterization.
10. Add rolling persistence and discovery-to-cross-fitted diagnostic degradation.
11. Add edge redundancy/family mapping.
12. Add OOF surface calibration and marginal-vs-interaction decomposition.
13. Add event-aligned pre/post paths, state persistence, and simultaneity diagnostics.
14. Add practical leave-the-best-out and eligibility-composition checks.
15. Maintain a central edge registry.
16. Produce the standardized edge dossier.
17. Add a small rejected-pair expansion audit to measure funnel miss rate.

---

## Phase 3 — Make Exhaustive Research Computationally Practical

1. Split dual research into exhaustive surface discovery and selective deep validation.
2. Build the shared cross-run cache.
3. Add component-level artifact lineage.
4. Compile features from shared primitives.
5. Optimize the hottest single-symbol feature operations.
6. Improve GPU tile/target reuse.
7. Calibrate resource settings for the current machine.
8. Allow CPU preparation, GPU scanning, and result writing to overlap.
9. Profile before lower-level kernel rewrites.
10. Build the compact canonical discovery plane.
11. Reuse compact validity/fold/session/target metadata.
12. Schedule feature/target tiles for memory locality.
13. Reuse GPU buffers and use bounded async staging where measured beneficial.
14. Reduce unnecessary Pandas materialization in large hot paths.
15. Define and enforce a numerical-precision contract.
16. Compact completed shards.
17. Make cache retention value-aware and bound cache/scratch growth.
18. Benchmark cold, warm, and incremental workloads separately.
19. Ensure throughput metrics describe actual pair-target work.
20. Preserve all point-in-time, timing, sealed-data, and numerical-parity invariants while optimizing.

---

## Phase 4 — Make Overnight Runs Reliable

1. One canonical pipeline DAG.
2. One normal command.
3. Separate machine and research configs.
4. Fine-grained checkpoints/resume.
5. Atomic artifact writes.
6. Resource-aware automatic recovery.
7. Stage-specific CPU/RAM/GPU tuning.
8. Runtime telemetry.
9. Performance benchmarks.

---

## Phase 5 — Make GPT the Analyst

1. Standardized analysis bundle.
2. Consolidated Parquet tables.
3. GPT-friendly DuckDB research database.
4. Stable schemas and data dictionary.
5. Trial accounting included in the bundle.
6. No automated trading recommendations.
7. SIP/execution data remains downstream.
8. Untouched replication/final validation remains explicitly sealed and separate from routine GPT analysis.

---

# HARDWARE TARGET FOR V3

V3 should be designed around the current workstation:

- **GPU:** NVIDIA RTX 3080 Ti, 12 GB VRAM
- **CPU:** Intel i9-11900KF, 8 cores / 16 threads
- **RAM:** 32 GB DDR4
- **Storage:** NVMe M.2 SSD

The software should not require a hardware upgrade to work reliably.

The main constraints to design around are:

- avoiding RAM exhaustion and Windows paging;
- keeping the GPU fed with sufficiently large reusable blocks;
- avoiding excessive CPU worker oversubscription;
- using the NVMe intentionally for cache/scratch;
- and maximizing reuse between runs.

A future move to 64 GB RAM could provide more flexibility, but V3 should be robust on the existing 32 GB system.

---

# SUCCESS CRITERIA

V3 is successful when this becomes routine:

1. GPT proposes a small set of new feature concepts.
2. Those concepts are added through one standardized mechanism.
3. One command starts the research.
4. The pipeline validates inputs and chooses safe resource settings.
5. Previously completed compatible work is reused automatically.
6. New concepts are tested against the full canonical concept bank even if their singles are weak.
7. r3/r5/r10, positive/negative effects, tails, and specialist behavior are preserved.
8. Broad canonical discovery is exhaustive.
9. Expensive follow-up is focused on relationships showing real structure.
10. A crash or resource error does not destroy hours of completed work.
11. The machine can be left unattended overnight.
12. The next morning there is one complete, standardized research bundle.
13. GPT can analyze that bundle without needing to understand the pipeline's internal directory tree.
14. Promising candidates can then be sent separately to SIP/execution analysis.
15. The pipeline itself remains a neutral research-data generator.
16. Every serious candidate has a standardized edge dossier showing where its return comes from.
17. GPT can tell whether a candidate is broad, tail-driven, specialist, regime-dependent, transition-driven, or outlier-dependent.
18. Repeated 5-minute observations are distinguishable from genuinely new trade opportunities.
19. Discovery performance and cross-fitted/OOS-like performance are displayed together so degradation is obvious.
20. Near-duplicate discoveries are grouped so ten variants of the same phenomenon are not mistaken for ten independent edges.
21. The alpha path, time-to-peak, decay, favorable/adverse excursion, and return distribution are available before execution testing.
22. A candidate does not move to SIP/execution work until its research evidence is sufficiently characterized to understand what is actually being tested.
23. The held-out surface shows whether predicted state ordering/calibration survives beyond the selected winning cell.
24. GPT can see exactly how much incremental information B adds beyond A in a dual.
25. The pre-signal path is available so continuation, exhaustion, reversal, and already-realized moves can be distinguished.
26. Simultaneous cross-sectional clusters are not mistaken for independent trade opportunities.
27. Practical leave-the-best-out views make outlier dependence immediately visible.
28. Feature/target eligibility composition is visible so data availability is not mistaken for alpha.
29. The exhaustive canonical scanner operates from a compact discovery representation rather than repeatedly streaming the full floating-point feature universe.
30. GPU/CPU/I/O work is scheduled for locality and reuse, with precision parity protected.
31. Cold rebuild, warm full-canonical, and incremental nightly performance are measured separately.
32. A stalled overnight process is detectable as a lack of useful-work progress rather than merely by whether the process is alive.
33. V3 preserves V2's point-in-time universe, timestamp, split/price-basis, source-fingerprint, and sealed-data guarantees.
34. A tiny number of fully frozen candidates can receive a one-shot untouched validation without contaminating normal discovery.
35. Incremental research is designed for routine overnight completion, while a full-canonical refresh targets the roughly 20-hour operational budget where profiling shows it is achievable without sacrificing correctness.

That is the target architecture for Quant-Pipeline V3.


---

# REVIEW SATURATION NOTE

This plan was repeatedly reviewed from four separate angles:

1. **alpha discovery coverage** — what could cause V3 to miss a real interaction, tail, specialist, or negative edge;
2. **edge forensics** — what information is required to understand whether a discovered effect is repeatable, broad, independent, persistent, economically meaningful, or driven by outliers/composition;
3. **single-machine computational efficiency** — what materially reduces wall-clock time and resource waste on the current i9-11900KF / 32 GB DDR4 / RTX 3080 Ti / NVMe workstation;
4. **overnight reliability and research integrity** — what prevents recomputation, silent stalls, corrupted artifacts, leakage, or repeated peeking at sealed data.

At this point, additional ideas found during review fall mainly into one of three categories:

- **implementation choices** that belong in the later V3 technical design (exact schemas, tile sizes, algorithms, libraries, thread counts, kernel shapes, etc.);
- **institutional infrastructure** that is unnecessary for this single-machine project;
- **extra slicing/testing dimensions** that would increase complexity and multiple-testing burden without clearly improving the ability to find and understand real edges.

For that reason, this document should now be treated as the **requirements/master improvement plan** for V3. Further work should move into technical architecture and implementation planning rather than continuing to expand the requirements list.

---

# PART II — REFERENCE TECHNICAL ARCHITECTURE

# 1. Core Design

V3 should be separated into four logical layers:

```text
DATA LAYER
    ↓
DISCOVERY PLANE
    ↓
FORENSICS PLANE
    ↓
ANALYSIS / EXECUTION HANDOFF
```

## Data Layer

Responsible for:
- immutable market-data snapshots
- PIT universe/security identity
- research-price basis
- feature inputs
- target inputs
- eligibility metadata
- reusable artifact cache

## Discovery Plane

Responsible for:
- feature generation
- singles
- exhaustive canonical dual surface scans
- r3/r5/r10
- compact specialist probe
- lightweight structural diagnostics

It must be optimized for **breadth and throughput**.

## Forensics Plane

Runs only on selected serious candidates.

Responsible for:
- candidate freezing
- fold/chunk diagnostics
- edge dossier
- signal episodes
- event paths
- return distribution
- tails/horizons
- per-symbol detail
- persistence
- concentration
- edge redundancy

It must be optimized for **understanding**, not exhaustive breadth.

## Analysis / Execution Handoff

Responsible for:
- `analysis_bundle/`
- `research.duckdb`
- edge registry
- SIP request generation/export
- sealed replication promotion workflow

The pipeline itself does not make trading recommendations.

---

# 2. Repository Layout

Recommended top-level structure:

```text
Quant-Pipeline-V3/
├─ pyproject.toml
├─ README.md
├─ V3_MASTER_SPEC.md
├─ configs/
│  ├─ research/
│  ├─ machines/
│  └─ examples/
├─ feature_packs/
│  ├─ builtin/
│  └─ experimental/
├─ src/quant_pipeline/
│  ├─ cli/
│  ├─ orchestration/
│  ├─ data/
│  ├─ registry/
│  ├─ features/
│  ├─ targets/
│  ├─ cache/
│  ├─ discovery/
│  │  ├─ singles/
│  │  ├─ duals/
│  │  ├─ surfaces/
│  │  └─ specialist_probe/
│  ├─ forensics/
│  │  ├─ dossier/
│  │  ├─ episodes/
│  │  ├─ event_paths/
│  │  ├─ tails/
│  │  ├─ horizons/
│  │  ├─ symbols/
│  │  └─ redundancy/
│  ├─ execution_data/
│  ├─ analysis_bundle/
│  ├─ telemetry/
│  └─ governance/
├─ tools/
├─ tests/
└─ runs/
```

Avoid accumulating multiple independent pipeline launchers.

---

# 3. Canonical CLI

Normal interface:

```bash
python -m quant_pipeline run --request configs/research/<request>.yaml
```

Modes:

```bash
python -m quant_pipeline run --mode incremental --request ...
python -m quant_pipeline run --mode full-canonical --request ...
python -m quant_pipeline resume --run-id <id>
python -m quant_pipeline status --run-id <id>
```

Explicit later promotion:

```bash
python -m quant_pipeline replicate --candidate-id <id>
```

Normal discovery must not access sealed replication/final-holdout data.

---

# 4. Configuration Separation

## Research config

Contains only research semantics:

```yaml
run_name:
discovery_period:
universe:
decision_grids:
feature_packs:
targets:
resolutions: [3, 5, 10]
mode: incremental | full-canonical
forensics_policy:
```

## Machine config

Git-ignored local profile:

```yaml
data_root:
cache_root:
run_root:
scratch_root:
duckdb_temp:
gpu_device:
ram_budget_gb:
vram_budget_gb:
max_cpu_workers:
```

Research results must not change merely because paths changed.

---

# 5. One Authoritative DAG

Conceptual stage order:

```text
preflight
   ↓
snapshot_validate
   ↓
observation_index
   ↓
registry_compile
   ↓
panel
   ├────────────────┐
   ↓                ↓
features          targets
   ↓                ↓
canonical_bins    target_arrays
   └───────┬────────┘
           ↓
        singles
           ↓
canonical_dual_surface_scan
           ↓
specialist_probe
           ↓
variant_expansion_queue
           ↓
variant_scan (only queued canonical families)
           ↓
candidate_materialization / freeze
           ↓
forensics
           ↓
analysis_bundle
```

Every CLI uses this DAG.

---

# 6. Artifact Model

Every expensive artifact must have:

```text
artifact_type
artifact_id
schema_version
input_hashes
definition_hash
implementation_hash
created_at
row_count / shape
dtype
checksum
status
```

Artifacts are immutable after completion.

Write incomplete outputs as `.partial`, validate, then atomically promote.

---

# 7. Content-Addressed Cache

Cache keys depend only on inputs that mathematically determine the artifact.

Examples:

## Feature

```text
hash(
    source_snapshot_hash,
    universe/grid identity,
    feature_definition_hash,
    required upstream primitive hashes,
    feature_engine_version
)
```

## Target

```text
hash(
    source_snapshot_hash,
    target_definition_hash,
    target_engine_version
)
```

## Canonical bin representation

```text
hash(
    feature_artifact_hash,
    binning_definition,
    bin_engine_version
)
```

## Dual surface shard

```text
hash(
    feature_A_bin_hash,
    feature_B_bin_hash,
    target_hash,
    grid,
    resolutions,
    scan_engine_version,
    shard_definition
)
```

Do not invalidate feature artifacts because report code changed.

---

# 8. Feature Registry

Every feature definition exposes a stable `FeatureSpec`-style contract:

```text
feature_id
concept_id
family
canonical: bool
grid
required_inputs
required_history
availability_rule
price_basis
parameters
definition_hash
dependencies
implementation_id
output_dtype
```

The implementation may be a function/class/registered kernel, but the metadata
above must be serializable without importing arbitrary research code.

Each concept has one declared canonical representation per relevant grid unless deliberately changed.

Experimental features live in isolated feature packs.

## Target contract

Every target should use a stable `TargetSpec`-style contract:

```text
target_id
family
grid
horizon
return_basis
entry_rule
exit_rule
same_day_requirement
benchmark/residual definition where applicable
validity_rule
definition_hash
implementation_id
output_dtype
```

Targets must preserve explicit decision, entry, and exit semantics. The target
registry—not downstream scripts—defines what a target means.

---

# 8A. Immutable Observation Index

For each source snapshot + universe + decision grid, build one immutable
observation index before feature/target hot-path work.

Minimum fields:

```text
obs_id
security_id
symbol (lookup/display only)
session_date
decision_timestamp
entry/reference timestamp where grid semantics require it
session_id
grid_id
```

Features, targets, validity masks, fold/chunk diagnostics, and compact scan
arrays align to `obs_id`.

Hot numerical paths should use integer-aligned arrays rather than repeatedly
joining on timestamps/symbol strings.

Forensics and reports map `obs_id` back to human-readable metadata.

This index is a core correctness contract: feature and target arrays cannot be
silently realigned by row order.

---

# 9. Feature Dependency DAG

Feature engine compiles shared primitives.

Example:

```text
close
 └─ returns
     ├─ positive_returns
     ├─ negative_returns
     ├─ squared_returns
     └─ signed_return

volume
 ├─ rolling_volume
 ├─ up_volume
 └─ down_volume

returns + volume
 ├─ signed_volume
 ├─ money_flow
 └─ return_x_rvol
```

Do not recompute identical rolling primitives independently for every feature spec.

---

# 10. Feature Compute Backend

Preferred division:

- **DuckDB / Arrow / optional lazy columnar engine**
  - scans
  - joins
  - filtering
  - projections
  - large tabular transforms

- **NumPy / Numba-style compiled kernels**
  - hot rolling numerical primitives
  - custom path calculations
  - repeated single-symbol operations

- **Pandas**
  - only where it remains simple and competitive

Optimization must be benchmark-driven.

On Windows, avoid sending giant DataFrames/arrays through multiprocessing
pickles. Prefer persistent stage-local worker pools that receive compact work
descriptors and read immutable Parquet/Arrow/memmap inputs directly. Large
read-only arrays should be memory-mapped/shared rather than copied into every
worker. Keep BLAS/OpenMP threads per worker bounded to prevent nested
oversubscription.

---

# 11. Compact Canonical Discovery Plane

Do not use the full float feature cache as the main exhaustive-scan representation.

Create compact arrays containing only:

```text
canonical_feature_state
target
validity
symbol_id
session_id
fold_id
timestamp_index
```

Preferred types where safe:

```text
uint8 / uint16  feature states / small IDs
int32           larger IDs/indexes
float32         targets
bitsets/compact masks where practical
```

If one compact rank/state code can derive r3/r5/r10 **with bit-for-bit or
declared-tolerance parity to the reference causal binning semantics**, prefer
that. Do not change tie handling, cross-sectional eligibility, or timestamp
availability merely to obtain a smaller representation.

Raw feature values remain available for forensics.

---

# 12. Singles

Singles run for all requested canonical features/targets.

Singles are descriptive results and **must not gate canonical dual scanning**.

Core output:

```text
feature_id
target_id
grid
active_edge_bps
frequency
opportunity_contribution_bps
active_n
independent_n where available
direction
basic temporal diagnostics
```

---

# 13. Exhaustive Canonical Dual Surface Scan

Search universe:

```text
all structurally compatible canonical concept pairs
×
compatible targets
```

No `single_survivors` gate.

No positive-sign gate.

Produce r3/r5/r10 in the same scan path where practical.

---

# 14. GPU Work Tiling

Conceptual scan unit:

```text
FEATURE_TILE_A
    ×
FEATURE_TILE_B
    ×
TARGET_TILE
```

Goals:
- sequential/local NVMe access
- reuse feature tiles
- reuse target tiles
- minimize H2D transfer
- keep GPU busy
- avoid random feature access

Tile dimensions come from profiling and current free VRAM.

---

# 15. GPU Pipeline

Preferred conceptual flow:

```text
CPU prepare tile N+1
       ↓
bounded pinned staging
       ↓
GPU compute tile N
       ↓
writer persists tile N-1
```

Use async streams/double buffering only if measured beneficial.

Pinned host memory must have a strict budget.

Prefer reusable/preallocated GPU buffers.

---

# 16. Surface-Pass Output

For every canonical pair-target-resolution retain:

```text
pair_id
feature_A
feature_B
target
grid
resolution
cell_counts
cell_returns
interaction_surface
best_state
worst_state
best_worst_spread
selected_active_edge
selected_frequency
selected_n
neighbor_support
plateau_size
populated_fraction
fold/chunk summary
trial_id
```

Preserve full surfaces in compact form.

## Statistical/inference contract

The exhaustive surface pass should remain cheap. Expensive inference belongs to
deep validation, but V3 must preserve enough lineage to know how a candidate was
selected.

For candidates entering deep validation:

- use session-aware/cluster-aware uncertainty for intraday observations;
- account for overlapping holding horizons where relevant;
- store raw effect, standard error, t/statistic, p-value and q-value when
  calculated;
- treat discovery-year statistics as **selection-aware diagnostics**, not sealed
  OOS evidence;
- never use a p-value as the sole candidate gate.

## Trial-family contract

Every test carries a `trial_family_id` and `trial_id`.

At minimum distinguish:

```text
single discovery
canonical dual discovery
resolution/state search
variant/window expansion
specialist follow-up
tail follow-up
horizon follow-up
```

Multiple-testing summaries/FDR may be calculated within declared families, but
the complete search count must remain visible in the trial ledger.

---

# 17. Cheap Specialist Probe

Run broadly after/coupled with canonical surface discovery.

Compact output:

```text
pair_id
target_id
resolution_used
symbols_active
fraction_positive
fraction_negative
effect_dispersion
top_symbol_share
top5_symbol_share
top_k_local_effects
global_vs_local_disagreement
```

Do not generate full per-symbol surfaces for every hypothesis.

The probe must also expose local `active_n` / independent-opportunity counts so
large local effects from tiny samples are obvious. Detailed per-symbol
expansion should require enough local evidence to be interpretable, with the
threshold/config stored in the run manifest.

---

# 18. Variant Expansion Before Candidate Freeze

Canonical discovery is exhaustive; variant/window expansion is hierarchical.

A canonical concept pair may enter an expansion queue because of global
structure, specialist structure, cross-resolution structure, or another
predeclared permissive criterion.

Expansion may test alternate:

- lookback windows;
- scales;
- representations;
- compatible grids.

All expanded tests belong to a separate trial family and remain in the trial
ledger.

Do not globally brute-force all 6,000+ feature variants against one another.

In periodic/full-canonical audit work, optionally fully expand a small
deterministic sample of rejected canonical pairs to estimate the search-funnel
miss rate. This audit is not required on every nightly incremental run.

---

# 19. Candidate Materialization

A pair-target enters deep forensics when a predefined permissive structural policy requests it.

The gate may consider:
- active edge magnitude
- spread
- frequency/N
- neighbor/plateau structure
- cross-resolution shape
- fold/chunk consistency
- specialist dispersion

Do not use one p-value as the entire gate.

Materialization creates a frozen candidate ID.

---

# 20. Candidate Identity

Candidate ID uniquely encodes:

```text
feature_A definition
feature_B definition if dual
target
grid
resolution
state/region
direction
data snapshot
selection source
```

Changing the rule creates a new candidate.

---

# 21. Edge Registry

Maintain an `edge_registry` table with:

```text
candidate_id
edge_family_id
parent_candidate_id
status
created_from_run
definition_hash
dossier_status
sip_status
replication_status
superseded_by
```

Statuses are factual lifecycle states, not recommendations.

---

# 22. Edge Dossier

Each serious candidate gets one standardized package.

## Identity
- frozen rule
- lineage
- return basis

## Economic shape
- active edge
- frequency
- independent opportunities/day
- gross opportunity contribution
- arithmetic cost budget

## Distribution
- mean/median
- win rate
- quantiles
- average winner/loser
- top 1%/5% contribution

## Surface
- r3/r5/r10
- selected region
- selected-region N
- boundaries and adjacent-state continuity
- neighbors
- plateau
- tail ladder
- discovery-year cross-fitted surface calibration/ranking diagnostic

## Interaction
- unconditional return
- A marginal
- B marginal
- A×B
- incremental interaction lift

## Time
- chronological chunks/months (discovery diagnostics)
- rolling persistence
- horizon ladder
- event-aligned pre/post path
- time to 25% / 50% / 75% of peak or terminal edge where meaningful
- time to peak
- decay/giveback
- MFE/MAE
- small fixed time-of-day breakdown
- small fixed broad market-regime breakdown

## Episodes
- fresh entry
- persistence
- exit
- re-entry
- episode duration
- state autocorrelation

## Cross-section
- symbol distribution
- specialist structure
- simultaneous signal clusters
- sector/liquidity/size/spread concentration where available
- coverage/eligibility composition
- long/short or high/low-tail asymmetry where meaningful

## Robustness description
- discovery statistics vs sealed OOS clearly labeled
- discovery-year cross-fitted/fold diagnostics explicitly labeled as diagnostics
- discovery-to-cross-fitted diagnostic degradation
- leave-best-symbol out
- leave-top-5-symbols out
- leave-best-month/session out
- top 1%/5% return-contribution concentration
- extreme-outcome sensitivity
- conditional baselines (same-symbol/time-of-day and available benchmark/residual bases)

## Redundancy
- signal overlap
- outcome-series correlation
- feature-family similarity
- edge-family membership

---

# 23. Discovery-Year Diagnostics vs Real OOS

The normal one-year discovery period may be used aggressively.

Internal monthly/chunk/fold results—including any cross-fitted surface
calibration performed within the discovery year—are **diagnostics**, not the
true untouched OOS test.

Preserve:

```text
DISCOVERY YEAR
    aggressive search + diagnostics

SEALED REPLICATION PERIOD
    inaccessible during normal discovery

FINAL HOLDOUT
    inaccessible until explicit promotion
```

---

# 24. Replication Workflow

Replication is explicit.

Requirements before sealed replication access:

```text
candidate frozen
dossier complete
execution methodology frozen if part of the test
candidate registry status updated
```

Replication applies the exact frozen rule unchanged.

Any later redesign becomes a new candidate.

---

# 25. Independent Opportunity Engine

Create one reusable utility converting active observations into:

```text
episodes
fresh signals
non-overlapping opportunities
unique symbol-days
concurrency
simultaneous clusters
```

Use this everywhere so trades/day is consistent.

Denominator uses all relevant trading days, not only active days.

---

# 26. Tail Ladder

For requested candidates:

```text
20%
10%
5%
2%
1%
```

Output:

```text
tail_definition
active_edge
frequency
independent_n
opportunities/day
chunk/month diagnostics
```

Do not auto-select the best tail as the strategy.

---

# 27. Horizon Ladder

Use existing compatible targets, e.g.:

```text
1m
2m
5m
10m
15m
30m
60m
120m
240m
EOD
```

Support:
- cumulative alpha path
- time to 25/50/75%
- time to peak
- decay

---

# 28. Event Path

For fresh candidate episodes:

```text
pre-window
t=0 first observable signal
post-window
```

Preserve:
- raw return path
- benchmark-relative path if available
- residual path if available
- useful feature-state evolution

Use fixed descriptive windows.

---

# 29. Redundancy / Edge Families

Similarity features:

```text
timestamp Jaccard overlap
symbol overlap
forward-return/P&L correlation
feature family
state similarity
target/horizon similarity
```

Group into `edge_family_id`.

Preserve individual candidates.

---

# 30. Analysis Bundle

Every completed run produces:

```text
runs/<run_id>/analysis_bundle/
├─ manifest.json
├─ bundle_manifest.json
├─ research.duckdb
├─ feature_registry.parquet
├─ target_registry.parquet
├─ singles.parquet
├─ duals.parquet
├─ trial_ledger.parquet
├─ specialist_summary.parquet
├─ edge_registry.parquet
├─ dossiers/
├─ surfaces/
├─ run_metrics.json
└─ data_dictionary.md
```

---

# 31. Research DuckDB

Provide views such as:

```text
single_summary
dual_summary
resolution_comparison
candidate_summary
specialist_summary
edge_families
tail_ladder
horizon_ladder
chronological_diagnostics
trial_coverage
```

No automated recommendations.

---

# 32. SIP Execution Handoff

Keep SIP work downstream.

Export exact:

```text
symbol
signal_timestamp
direction
candidate_id
reference_exit_timestamp
```

SIP exporter obtains raw quote/trade paths.

Discovery does not fabricate fills or impact.

---

# 32A. Storage-Layer Contract

Use three physical/logical storage layers:

## Durable/source and final analytical data
- immutable source snapshots
- Parquet
- DuckDB catalog/query layer

## Reusable numerical research cache
- partitioned Parquet/Arrow
- NumPy/memmap arrays
- compact observation-aligned artifacts

## GPU-hot representation
- compact bins/states
- float targets
- validity/index metadata
- reusable device buffers

`research.duckdb` is a **rebuildable analysis/query layer**, not the sole source
of truth for discovery artifacts.

Large reusable caches should be partitioned so adding new dates/features does
not force rebuilding unrelated historical partitions.

---

# 33. Resource Scheduler

Lightweight local resource manager tracks:

```text
CPU workers
RAM budget
GPU VRAM budget
disk/scratch budget
```

Stage resource profiles differ.

---

# 34. Machine Defaults to Benchmark

Initial starting points only:

```text
feature workers: 4–8
DuckDB threads: 4–6
DuckDB memory: ~16–20 GB when DuckDB is the dominant stage; lower if other
memory-heavy workers run concurrently
BLAS/OpenMP threads per worker: 1
RAM reserve: >= 6 GB
GPU VRAM working target: ~9.5–10.5 GB as a starting ceiling, adjusted from
measured free VRAM and allocator behavior
```

Benchmark rather than hard-code permanently.

---

# 35. Startup Calibration

Preflight checks:

```text
available RAM
available VRAM
disk free
CUDA
machine profile
cache compatibility
```

Choose safe:
- worker count
- DuckDB concurrency
- feature block size
- GPU tile size
- target tile size
- prefetch depth

---

# 36. Telemetry

Maintain:

```text
STATUS.json
events.jsonl
metrics.jsonl
```

Track:
- stage/shard
- completed/expected
- elapsed
- cache hit %
- rows/sec
- features/sec
- pair-targets/sec
- RAM/RSS
- page faults if available
- GPU utilization/VRAM/temp/clock/power
- CPU utilization/clock; CPU temperature only where a reliable sensor source is available
- disk throughput
- scratch usage
- DuckDB spill
- retries
- last error
- heartbeat

---

# 37. Throughput Terminology

Use explicit metrics:

```text
pair_targets_per_sec
resolution_tests_per_sec
observations_per_sec
```

Do not count fused r3/r5/r10 as three pair-targets.

---

# 38. Stall Detection

Track heartbeat plus useful-work counters.

If no meaningful progress occurs abnormally:
- capture diagnostics
- safely abort/retry shard where appropriate
- never infinitely restart

---

# 39. Failure Policy

Recover automatically from known resource failures:

```text
CUDA OOM → reduce tile, retry shard
RAM/DuckDB pressure → reduce concurrency, retry shard
temporary I/O → bounded retry
```

Stop on:

```text
causality violation
data corruption
schema incompatibility
numerical parity failure
invalid feature definition
sealed-data governance violation
```

---

# 40. Cache Retention

Track:

```text
size
build time
last use
reuse count
lineage references
rebuildability
```

Prefer retaining:
- canonical feature artifacts
- canonical bins
- targets
- expensive primitives
- old-old canonical scan results

Clean:
- temp scratch
- cheap stale variants
- obsolete partials
- regenerable one-off diagnostics

---

# 41. Sharding and Compaction

During compute:
- small enough shards for good resume granularity

After success:
- compact to analysis-friendly Parquet

Execution and analysis layouts may differ.

---

# 42. Numerical Precision Contract

Declare allowed dtypes and reduction precision.

Example:

```text
bins/IDs           smallest safe integer
feature hot arrays float32 where validated
targets            float32 where validated
critical reductions enough precision to preserve decisions
```

Optimized paths must stay within declared parity tolerances.

---

# 43. I/O and Worker-Concurrency Rules

On the current Windows workstation:

- avoid multiple heavy writers competing for the NVMe;
- prefer a bounded/single coordinated result writer per hot stage;
- keep long-lived worker pools where practical to reduce Windows process-spawn overhead;
- workers receive artifact/shard descriptors, not giant Python objects;
- preflight estimates scratch/cache/output space and enforces a free-space reserve;
- DuckDB-heavy stages and Python multiprocessing-heavy stages should not both
  assume ownership of all CPU/RAM resources simultaneously.

---

# 44. Performance Profiling

Instrument hot sections:

```text
LOAD
PREPARE
H2D
SCAN
INFERENCE
D2H
WRITE
```

Profile whole-system bottlenecks before custom CUDA/Triton work.

---

# 45. Performance Benchmarks

Track:

## Cold rebuild
No reusable artifacts.

## Warm/full-canonical
Reusable panels/features/targets.

## Incremental nightly
Small new feature pack.

For each report:
- wall-clock
- peak RAM
- peak VRAM
- disk read/write
- cache hit %
- dominant stage
- pair-target throughput

---

# 46. Performance Goal

Goal, not promise:

- incremental research fits comfortably into unattended overnight use
- full-canonical refresh targets roughly the acceptable ~20-hour window where achievable
- correctness and coverage are never weakened to hit runtime

---

# 47. Non-Negotiable Data / Causality Invariants

V3 must preserve these V2 properties during all optimization/refactoring:

- immutable/fingerprinted source snapshots;
- point-in-time universe membership;
- stable security identity;
- corporate-action/research-price consistency;
- causal feature availability;
- explicit decision/entry/exit timestamps;
- no future bars in feature construction;
- causal cross-sectional ranking/binning using only eligible information
  available at the decision timestamp;
- deterministic feature/target definition hashes;
- sealed replication/final-holdout access controls;
- CPU/GPU parity within declared numerical tolerances.

An optimization is invalid if it weakens one of these guarantees.

---

# 48. V2 Components to Port

Port proven V2 behavior instead of rewriting blindly:

- PIT/security identity
- split/research-price handling
- availability timing
- registry semantics
- sealed replication/final holdout
- packed/memmapped data handling
- fused r3/r5/r10 scanner ideas
- deterministic resume/checkpoint behavior
- CPU/GPU parity
- SIP exporter

---

# 49. V2 → V3 Parity Stage

Before new research:

1. port data contracts
2. port canonical features
3. port targets
4. port discovery boundaries
5. run representative parity checks
6. verify unchanged algorithms match V2

Intentional V3 differences must be documented.

---

# 50. Feature-Pack Authoring Contract for GPT/Codex

A new feature pack should be self-contained and declarative.

Minimum expected contents:

```text
pack metadata
FeatureSpec definitions
implementation(s)
concept/family labels
canonical flag where applicable
required inputs/history
availability semantics
price basis
definition hashes
small deterministic validation fixtures/parity checks
```

Adding a pack must not require editing discovery, cache, orchestration, or output
modules.

The pipeline validates the pack before beginning a long run and rejects:

- missing causal availability metadata;
- unsupported grid/input contracts;
- duplicate IDs/hashes;
- incompatible output shape/dtype;
- definitions that attempt to access sealed-period data.

---

# 51. Recommended Build Sequence

## Build 1 — Skeleton
- repo layout
- configs
- CLI
- DAG
- artifact/cache interfaces
- telemetry

## Build 2 — Data/Registry
- snapshot contract
- immutable observation index
- feature/target registries
- canonical definitions
- sealed-period governance

## Build 3 — Feature/Target Engine
- feature DAG
- primitive cache
- target cache
- compact canonical bin plane

## Build 4 — Discovery Engine
- singles
- exhaustive canonical dual surfaces
- r3/r5/r10
- specialist probe
- hierarchical variant expansion
- trial-family accounting and completeness reconciliation

## Build 5 — Candidate/Forensics
- candidate freezing
- session/dependence-aware inference
- independent opportunities
- full dossier
- discovery-year cross-fitted surface calibration diagnostic
- marginal-vs-interaction decomposition
- episodes/state persistence
- event paths
- tails/horizons
- time-of-day/regime characterization
- symbol detail/simultaneity
- concentration/leave-best-out/coverage diagnostics
- redundancy/edge families

## Build 6 — Analysis Bundle
- consolidated Parquet
- research.duckdb
- edge registry
- manifests/dictionary

## Build 7 — Performance
- profile feature engine
- profile scanner
- tune CPU/RAM/VRAM
- improve locality/target batching
- async staging if beneficial
- compaction/cache policy

## Build 8 — V2 Replay
- recreate discovery run
- compare outputs
- analyze fresh V3 findings

Only after this should normal new-feature research begin.

---

# 52. Minimal Acceptance Criteria

V3 is not ready until:

1. one command starts a clean discovery run
2. restart safely resumes work
3. new features do not require unrelated core edits
4. compatible old artifacts are reused
5. singles do not gate canonical duals
6. all compatible canonical pairs are accounted for
7. r3/r5/r10 are independent outputs
8. negative effects are retained
9. active edge and weighted contribution are separate
10. independent opportunity counts exist
11. specialist/global-cancellation summaries exist
12. serious candidates can produce edge dossiers
13. discovery folds/chunks are diagnostics, not labeled true OOS
14. sealed replication remains inaccessible to normal discovery
15. analysis bundle and DuckDB are automatic
16. SIP export accepts candidate IDs
17. telemetry diagnoses stalls/slowdowns
18. V3 runs safely within 32 GB RAM / 12 GB VRAM
19. parity is preserved where expected
20. pipeline outputs data, not trading recommendations
21. observation-aligned feature/target arrays are keyed by immutable `obs_id`
22. variant expansion is hierarchical and separately trial-accounted
23. deep-validation inference is session/dependence aware
24. return basis is explicit in every candidate/dossier
25. all V2 point-in-time/causality/sealed-data invariants are preserved
26. full run completeness reconciles expected/executed/reused/excluded/failed work

---

# 53. Sol/Codex Operating Rule

When implementing V3:

1. read `V3_MASTER_SPEC.md` completely before architectural changes;
2. work only on the requested build phase;
3. do not redesign unrelated architecture unless a contradiction requires it;
4. preserve completed contracts;
5. run relevant tests/benchmarks before declaring a phase complete;
6. update implementation notes/manifests instead of repeatedly re-explaining architecture;
7. return concise engineering results:
   - files changed;
   - tests;
   - benchmarks;
   - blockers;
   - exact next command.

If a detail is unspecified, choose the simplest design consistent with this
master specification and the current hardware.

---

# 54. Trial-Coverage / Completeness Contract

A run manifest must make it possible to reconcile:

```text
expected
newly executed
reused
structurally excluded
unavailable
failed
```

for singles, canonical duals, and queued expansion tests.

A run must not label a stage "complete" when unexplained expected work is
missing.

---

# 55. Rejected-Pair Funnel Audit

This is optional periodic/audit work, not normal nightly overhead.

For a small deterministic sample of canonical pairs rejected from variant
expansion, run the full variant expansion anyway.

Record:

```text
audited_rejects
meaningful_variant_discoveries
estimated_miss_rate
```

Use the result to decide whether the expansion gate is too narrow.

---

# 56. Return-Basis Contract

Raw, benchmark-adjusted, and beta/residual targets are distinct targets.

Do not silently translate one into another.

Candidate/dossier outputs always identify the return basis.

A benchmark-relative edge is not described as a raw stock edge.

---

# 57. Discovery Statistics vs Sealed Replication

Within the discovery year, V3 may search aggressively and use folds/months,
cross-fitted state-selection diagnostics, tail ladders, and variant expansion.

These remain discovery/diagnostic evidence because the same one-year dataset
participates in research.

The true next validation layer is the sealed replication period configured
outside discovery.

The final holdout remains sealed until explicit later promotion.

---

# 58. Research Database Source-of-Truth Rule

`research.duckdb` exists for convenient GPT/analyst queries.

It is rebuildable from versioned analysis-bundle artifacts and manifests.

Discovery/cache correctness must never depend on hand-edited or mutable
analytical views inside `research.duckdb`.

---

# 59. Determinism Contract

Given identical:

```text
source snapshot
research config
feature/target definitions
implementation versions
machine-independent numerical tolerances
```

the pipeline should produce equivalent candidate/surface results.

Any sampling used for audits must use a stored deterministic seed/key.

---

# 60. Performance Optimization Rule

No optimization is accepted solely because GPU/CPU utilization looks higher.

Accept it only when it:

1. reduces representative wall-clock time or increases useful research
   throughput;
2. stays within RAM/VRAM/disk safety bounds;
3. preserves numerical/candidate parity where the algorithm is unchanged;
4. does not weaken causal/sealed-data guarantees.

---

# 61. Final Architectural Principle

V3 should optimize two things simultaneously:

> **Search as much economically meaningful hypothesis space as possible per unit of compute.**

and

> **Extract enough structured evidence from every serious candidate that GPT can understand the nature of the edge before execution assumptions are introduced.**

Everything in the implementation should support those two goals.


---

---

# PART III — CODE-LEVEL IMPLEMENTATION CONTRACT

This section exists so Sol/Codex does not need to invent the public interfaces,
schemas, naming, or control flow while implementing V3.

These code blocks are **reference public contracts**, not a requirement to copy
every line verbatim. Sol may change internal implementation details when tests
or profiling justify it, but changing a public contract below should be
deliberate and documented in the repository.

The computational internals that should remain implementation-flexible include:

- exact rolling-feature kernels;
- exact CUDA/Torch kernel decomposition;
- exact DuckDB SQL;
- exact Parquet row-group sizes;
- exact tile sizes;
- exact worker counts;
- exact async-stream layout.

Those details must be selected from correctness tests and benchmarks on the
actual workstation.

---

## 62. Core Python Types

Recommended location:

```text
src/quant_pipeline/contracts.py
```

Reference skeleton:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class RunMode(StrEnum):
    INCREMENTAL = "incremental"
    FULL_CANONICAL = "full-canonical"


class ArtifactStatus(StrEnum):
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"


class TrialStatus(StrEnum):
    EXPECTED = "expected"
    EXECUTED = "executed"
    REUSED = "reused"
    STRUCTURALLY_EXCLUDED = "structurally_excluded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    feature_id: str
    concept_id: str
    family: str
    grid: str
    canonical: bool

    required_inputs: tuple[str, ...]
    required_history_bars: int

    availability_rule: str
    price_basis: str

    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()

    implementation_id: str = ""
    output_dtype: str = "float32"
    definition_hash: str = ""


@dataclass(frozen=True, slots=True)
class TargetSpec:
    target_id: str
    family: str
    grid: str
    horizon_minutes: int | None

    return_basis: str
    entry_rule: str
    exit_rule: str
    same_day_requirement: bool
    validity_rule: str

    benchmark_definition: str | None = None
    residual_definition: str | None = None

    implementation_id: str = ""
    output_dtype: str = "float32"
    definition_hash: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactKey:
    artifact_type: str
    semantic_id: str
    content_hash: str
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class CandidateDefinition:
    candidate_id: str

    feature_a_id: str
    feature_b_id: str | None

    target_id: str
    grid: str
    resolution: int

    state_payload: Mapping[str, JsonValue]
    state_definition: str
    direction: int

    source_snapshot_hash: str
    selection_run_id: str
    selection_trial_id: str

    return_basis: str
    definition_hash: str


@dataclass(frozen=True, slots=True)
class StageResult:
    stage_name: str
    output_keys: tuple[ArtifactKey, ...]
    metrics: Mapping[str, JsonValue]
    warnings: tuple[str, ...] = ()
```

Rules:

1. `feature_id`, `target_id`, and `candidate_id` are stable semantic IDs.
2. `definition_hash` changes whenever the mathematical meaning changes.
3. Display labels are not identities.
4. A renamed file path alone must not change research identity.
5. A modified state, resolution, direction, feature definition, target
   definition, return basis, or source snapshot creates a different candidate.

---

## 63. Canonical Hashing

Recommended location:

```text
src/quant_pipeline/hashing.py
```

Reference implementation:

```python
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any


def _canonicalize(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Path):
        return value.as_posix()

    if isinstance(value, dict):
        return {
            str(k): _canonicalize(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }

    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]

    if isinstance(value, set):
        return sorted(_canonicalize(v) for v in value)

    return value


def canonical_json_bytes(value: Any) -> bytes:
    payload = _canonicalize(value)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
```

Do not hash absolute machine paths into research definitions unless the path
itself has mathematical meaning. Hash the source snapshot identity/checksum,
not `D:\\data\\...`.

---

## 64. Artifact Manifest and Atomic Commit

Recommended locations:

```text
src/quant_pipeline/artifacts.py
src/quant_pipeline/cache/store.py
```

Reference contracts:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    artifact_type: str
    artifact_id: str
    content_hash: str
    schema_version: int

    definition_hash: str
    implementation_hash: str
    input_hashes: tuple[str, ...]

    row_count: int | None
    shape: tuple[int, ...] | None
    dtype: str | None

    checksum: str
    created_at_utc: str
    status: str

    metadata: Mapping[str, Any]


class ArtifactStore:
    def has_complete(self, key: ArtifactKey) -> bool:
        raise NotImplementedError

    def validate(self, key: ArtifactKey) -> ArtifactManifest:
        raise NotImplementedError

    def path_for(self, key: ArtifactKey) -> Path:
        raise NotImplementedError

    def begin_write(self, key: ArtifactKey) -> Path:
        """Return unique .partial path owned by this writer."""
        raise NotImplementedError

    def commit(
        self,
        key: ArtifactKey,
        partial_path: Path,
        manifest: ArtifactManifest,
    ) -> Path:
        """Validate, then atomically publish immutable completed artifact."""
        raise NotImplementedError
```

Reference file commit helper:

```python
from pathlib import Path
import os


def atomic_publish_file(partial: Path, final: Path) -> None:
    if final.exists():
        raise FileExistsError(f"Immutable artifact already exists: {final}")

    final.parent.mkdir(parents=True, exist_ok=True)

    # Same-volume rename/replace semantics are required for the atomic step.
    os.replace(partial, final)
```

For directory artifacts, publish a uniquely named completed directory only after
all children and the manifest validate. Do not expose half-built final
directories.

---

## 65. Run Context

Recommended location:

```text
src/quant_pipeline/context.py
```

Reference skeleton:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunPaths:
    repo_root: Path
    data_root: Path
    cache_root: Path
    run_root: Path
    scratch_root: Path
    duckdb_temp: Path


@dataclass(slots=True)
class RunContext:
    run_id: str
    mode: RunMode

    research_config: dict
    machine_config: dict

    source_snapshot_hash: str
    implementation_hash: str

    paths: RunPaths
    artifacts: ArtifactStore

    # Concrete classes can be injected here rather than imported globally.
    telemetry: object
    registry: object
    governance: object
```

Do not store mutable global research configuration in module-level variables.

---

## 66. Pipeline Stage Contract

Recommended location:

```text
src/quant_pipeline/orchestration/stage.py
```

Reference:

```python
from typing import Protocol


class PipelineStage(Protocol):
    name: str

    def required_artifacts(
        self,
        ctx: RunContext,
    ) -> Sequence[ArtifactKey]:
        ...

    def planned_outputs(
        self,
        ctx: RunContext,
    ) -> Sequence[ArtifactKey]:
        ...

    def run(
        self,
        ctx: RunContext,
    ) -> StageResult:
        ...
```

The orchestrator owns stage ordering.

A stage may request dependencies; it may not secretly execute unrelated
downstream stages.

---

## 67. Authoritative Stage Registry

Recommended location:

```text
src/quant_pipeline/orchestration/dag.py
```

Conceptual reference:

```python
STAGES = {
    "preflight": PreflightStage(),
    "snapshot_validate": SnapshotValidationStage(),
    "observation_index": ObservationIndexStage(),
    "registry_compile": RegistryCompileStage(),
    "panel": PanelStage(),
    "features": FeatureStage(),
    "targets": TargetStage(),
    "canonical_bins": CanonicalBinStage(),
    "singles": SingleScanStage(),
    "canonical_duals": CanonicalDualScanStage(),
    "specialist_probe": SpecialistProbeStage(),
    "variant_expansion": VariantExpansionStage(),
    "candidate_materialization": CandidateMaterializationStage(),
    "forensics": ForensicsStage(),
    "analysis_bundle": AnalysisBundleStage(),
}

DEPENDENCIES = {
    "preflight": (),
    "snapshot_validate": ("preflight",),
    "observation_index": ("snapshot_validate",),
    "registry_compile": ("snapshot_validate",),
    "panel": ("observation_index", "registry_compile"),
    "features": ("panel",),
    "targets": ("panel",),
    "canonical_bins": ("features",),
    "singles": ("canonical_bins", "targets"),
    "canonical_duals": ("canonical_bins", "targets"),
    "specialist_probe": ("canonical_duals",),
    "variant_expansion": ("canonical_duals", "specialist_probe"),
    "candidate_materialization": (
        "canonical_duals",
        "specialist_probe",
        "variant_expansion",
    ),
    "forensics": ("candidate_materialization",),
    "analysis_bundle": ("forensics",),
}
```

This is the one stage graph.

Do not create a second "fast runner" with a different hidden order.

---

## 68. Observation Index Schema

Recommended artifact:

```text
observation_index.parquet
```

Required columns:

| Column | Type | Meaning |
|---|---|---|
| `obs_id` | int64 | immutable contiguous observation identity |
| `security_id` | int32/int64 | stable security identity |
| `symbol` | string/dictionary | display/lookup only |
| `session_id` | int32 | stable trading-session ID |
| `security_session_seq` | int32 | per-security sequence within session/grid |
| `session_date` | date32 | exchange-local session date |
| `decision_ts_utc` | timestamp ns UTC | exact decision timestamp |
| `grid_id` | dictionary/string | decision-grid identity |
| `entry_reference_ts_utc` | timestamp ns UTC nullable | grid/target reference if required |
| `universe_eligible` | bool | PIT eligibility flag |

Required invariants:

```python
assert obs_id is unique
assert obs_id is monotonically increasing within the artifact
assert security_id is stable across runs for the same security
assert security_session_seq is contiguous within security/session/grid
assert no feature or target array relies on accidental row order
```

All hot arrays must either:

1. have length exactly equal to the observation index and align by `obs_id`; or
2. carry an explicit integer index mapping back to `obs_id`.

---

## 69. Feature Implementation Interface

Recommended location:

```text
src/quant_pipeline/features/base.py
```

Reference:

```python
from typing import Protocol
import numpy as np


class FeatureImplementation(Protocol):
    implementation_id: str

    def compute(
        self,
        *,
        spec: FeatureSpec,
        observation_index,
        inputs: Mapping[str, object],
    ) -> np.ndarray:
        """
        Return one observation-aligned array.

        The implementation must not read data after the feature's declared
        availability time for any obs_id.
        """
        ...
```

Validation wrapper:

```python
def validate_feature_output(spec: FeatureSpec, values, n_obs: int) -> None:
    if values.ndim != 1:
        raise ValueError(f"{spec.feature_id}: output must be 1-D")

    if len(values) != n_obs:
        raise ValueError(
            f"{spec.feature_id}: {len(values)=} does not match {n_obs=}"
        )

    if str(values.dtype) != spec.output_dtype:
        raise TypeError(
            f"{spec.feature_id}: expected {spec.output_dtype}, got {values.dtype}"
        )
```

Feature implementations should receive explicit inputs/artifacts, not reach into
arbitrary global data directories.

---

## 70. Target Implementation Interface

Recommended location:

```text
src/quant_pipeline/targets/base.py
```

Reference:

```python
class TargetImplementation(Protocol):
    implementation_id: str

    def compute(
        self,
        *,
        spec: TargetSpec,
        observation_index,
        inputs: Mapping[str, object],
    ):
        """
        Return observation-aligned target values plus validity.

        Decision, entry, and exit timing are defined by TargetSpec.
        """
        ...
```

Reference output contract:

```python
@dataclass(frozen=True, slots=True)
class TargetArray:
    values: object
    valid: object
    target_id: str
    return_basis: str
    definition_hash: str
```

---

## 71. Feature-Pack Layout

Recommended structure:

```text
feature_packs/
└─ experimental/
   └─ flow_path_v1/
      ├─ pack.yaml
      ├─ specs.py
      ├─ implementations.py
      └─ tests/
         └─ test_fixtures.py
```

Example `pack.yaml`:

```yaml
pack_id: flow_path_v1
pack_version: 1
description: Flow/path-shape research concepts
features:
  - money_flow_proxy_30m
  - down_up_vol_ratio_30m
```

Feature-pack loader requirements:

- reject duplicate `feature_id`;
- reject duplicate semantic definitions with inconsistent IDs;
- validate `required_history`;
- validate declared inputs;
- validate availability metadata;
- validate canonical concept mapping;
- import only the selected pack;
- never grant sealed-period data access.

---

## 72. Research Configuration — Concrete Example

The first clean V3 recreation should preserve the existing V2 validation
timeline unless the user deliberately changes it.

Example:

```yaml
run_name: v3_discovery_rebuild_01
mode: full-canonical

periods:
  discovery:
    start: 2025-05-01
    end: 2026-04-30
  replication:
    start: 2026-05-01
    end: 2026-08-31
    sealed: true
  final_holdout:
    start: 2026-09-01
    end: null
    sealed: true

allow_replication_access: false
allow_final_holdout_access: false

resolutions: [3, 5, 10]

feature_packs:
  - builtin_v2_port

targets:
  - builtin_intraday_v2_port

discovery:
  canonical_duals: exhaustive_compatible
  single_parent_gate: false
  retain_negative_effects: true

forensics:
  enabled: true
  candidate_policy: permissive_structural
```

No ordinary discovery command may override sealed access with an undocumented
flag.

---

## 73. Machine Configuration — Concrete Example

Example only; tune from benchmarks:

```yaml
data_root: D:/quant_data
cache_root: D:/quant_v3_cache
run_root: D:/quant_v3_runs
scratch_root: D:/quant_v3_scratch
duckdb_temp: D:/quant_v3_scratch/duckdb

gpu_device: cuda:0

resource_budget:
  ram_gb: 32
  reserve_ram_gb: 6
  vram_soft_limit_gb: 10.0

feature_workers: 6
duckdb_threads: 5
duckdb_memory_limit_gb: 18

blas_threads_per_worker: 1
omp_threads_per_worker: 1
```

The machine file is local and should not affect definition hashes.

`data_root` points to the already-existing external candle/source-data location.
The V3 build treats that location as read-only. All generated caches, scratch
files, runs, and reports must live under V3-owned paths, never inside
`data_root`.

---

## 74. Canonical Bin Artifact

The canonical discovery plane should persist compact observation-aligned state
information.

Logical contract:

```python
@dataclass(frozen=True, slots=True)
class CanonicalStateArtifact:
    feature_id: str
    concept_id: str
    grid: str

    obs_count: int
    state_dtype: str

    state_path: Path
    valid_mask_path: Path

    source_feature_hash: str
    binning_definition_hash: str
```

If one percentile/rank code is used to derive r3/r5/r10, tests must prove that
the derived states reproduce reference binning decisions, including ties and
eligibility behavior.

---

## 75. Single Scan Request

```python
@dataclass(frozen=True, slots=True)
class SingleScanRequest:
    feature_id: str
    target_ids: tuple[str, ...]
    resolutions: tuple[int, ...] = (3, 5, 10)
```

Singles must be produced for analysis even when they are weak.

They do not control whether the canonical concept enters the dual scanner.

---

## 76. Dual Scan Request

```python
@dataclass(frozen=True, slots=True)
class DualScanRequest:
    pair_id: str

    feature_a_id: str
    feature_b_id: str

    target_ids: tuple[str, ...]
    resolutions: tuple[int, ...] = (3, 5, 10)

    feature_tile_id: str | None = None
    target_tile_id: str | None = None
```

Pair identity must be order-canonicalized so `(A, B)` and `(B, A)` are not
accidentally scanned twice unless order itself has defined meaning.

Reference helper:

```python
def canonical_pair_id(feature_a_id: str, feature_b_id: str) -> str:
    a, b = sorted((feature_a_id, feature_b_id))
    return f"{a}__X__{b}"
```

---

## 77. GPU Scanner Boundary

The GPU implementation should expose a small stable boundary rather than
leaking Torch tensors throughout the orchestration layer.

```python
@dataclass(frozen=True, slots=True)
class SurfaceBatch:
    pair_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    resolutions: tuple[int, ...]

    feature_a_states: object
    feature_b_states: object
    targets: object
    validity: object


@dataclass(frozen=True, slots=True)
class SurfaceBatchResult:
    counts: object
    sums: object
    means: object
    metadata: dict


class SurfaceScanner(Protocol):
    def scan(self, batch: SurfaceBatch) -> SurfaceBatchResult:
        ...
```

A CPU reference implementation should exist for small parity fixtures.

The optimized GPU scanner is accepted only after matching the reference output
within declared tolerances.

---

## 78. Surface Storage Schemas

### `dual_summary.parquet`

| Column | Type |
|---|---|
| `pair_id` | string |
| `feature_a_id` | string |
| `feature_b_id` | string |
| `target_id` | string |
| `grid` | string |
| `resolution` | int8 |
| `trial_id` | string |
| `best_state_id` | string/int |
| `worst_state_id` | string/int |
| `selected_state_definition` | string |
| `active_edge_bps` | float32/64 |
| `active_frequency` | float32 |
| `active_n` | int64 |
| `best_worst_spread_bps` | float32/64 |
| `neighbor_support` | float32 |
| `plateau_size` | int16/int32 |
| `populated_fraction` | float32 |
| `direction` | int8 |
| `return_basis` | string |

### `surface_cells.parquet`

One row per pair-target-resolution-cell:

| Column | Type |
|---|---|
| `pair_id` | string |
| `target_id` | string |
| `resolution` | int8 |
| `cell_a` | int8 |
| `cell_b` | int8 |
| `n` | int64 |
| `sum_return_bps` | float64 |
| `mean_return_bps` | float64 |
| `selected_region` | bool |

A compact binary/array representation may be used during computation, but the
analysis bundle must expose an easily queryable representation.

---

## 79. Single Summary Schema

### `single_summary.parquet`

| Column | Type |
|---|---|
| `feature_id` | string |
| `target_id` | string |
| `grid` | string |
| `resolution` | int8 |
| `trial_id` | string |
| `state_definition` | string |
| `direction` | int8 |
| `active_edge_bps` | float64 |
| `frequency` | float64 |
| `opportunity_contribution_bps` | float64 |
| `active_n` | int64 |
| `independent_n` | int64 nullable |
| `return_basis` | string |

Do not overload `active_edge_bps` with frequency weighting.

---

## 80. Trial Ledger Schema

### `trial_ledger.parquet`

| Column | Type |
|---|---|
| `trial_id` | string |
| `trial_family_id` | string |
| `run_id` | string |
| `trial_type` | string |
| `feature_a_id` | string nullable |
| `feature_b_id` | string nullable |
| `target_id` | string nullable |
| `resolution` | int8 nullable |
| `variant_definition` | string nullable |
| `status` | string |
| `artifact_hash` | string nullable |
| `reason` | string nullable |
| `created_at_utc` | timestamp |

Allowed `status` values:

```text
expected
executed
reused
structurally_excluded
unavailable
failed
```

A completed stage must reconcile all expected work into one of those outcomes.

---

## 81. Specialist Summary Schema

### `specialist_summary.parquet`

| Column | Type |
|---|---|
| `pair_id` | string |
| `target_id` | string |
| `resolution` | int8 |
| `symbols_active` | int32 |
| `fraction_positive` | float32 |
| `fraction_negative` | float32 |
| `effect_dispersion_bps` | float64 |
| `top_symbol_share` | float32 |
| `top5_symbol_share` | float32 |
| `global_effect_bps` | float64 |
| `global_vs_local_disagreement` | float64 |
| `min_local_active_n` | int64 |
| `median_local_active_n` | float64 |
| `max_local_active_n` | int64 |

Detailed local outputs may live in a separate keyed dataset.

---

## 82. Candidate ID Generation

Candidate identity must be deterministic from the frozen definition.

Reference:

```python
def build_candidate_id(payload: dict) -> str:
    digest = content_hash(payload)[:16]
    return f"cand_{digest}"
```

Payload must include at least:

```python
payload = {
    "feature_a_definition_hash": ...,
    "feature_b_definition_hash": ...,
    "target_definition_hash": ...,
    "grid": ...,
    "resolution": ...,
    "state_payload": ...,
    "direction": ...,
    "source_snapshot_hash": ...,
    "return_basis": ...,
}
```

Do not include mutable labels like "best_strategy_3".

---

## 83. Edge Registry Schema

### `edge_registry.parquet`

| Column | Type |
|---|---|
| `candidate_id` | string |
| `edge_family_id` | string nullable |
| `parent_candidate_id` | string nullable |
| `selection_run_id` | string |
| `definition_hash` | string |
| `status` | string |
| `dossier_status` | string |
| `sip_status` | string |
| `replication_status` | string |
| `superseded_by` | string nullable |
| `created_at_utc` | timestamp |

Recommended factual statuses:

```text
materialized
dossier_complete
sip_exported
replication_authorized
replication_complete
final_holdout_authorized
superseded
```

Do not store "buy", "best", or "recommended" lifecycle statuses.

---

## 84. Independent Opportunity / Episode Interface

The same engine must be used everywhere.

Recommended contract:

```python
@dataclass(frozen=True, slots=True)
class SignalEpisode:
    candidate_id: str
    security_id: int
    session_id: int

    start_obs_id: int
    end_obs_id: int

    start_ts_utc: object
    end_ts_utc: object

    duration_observations: int
    fresh_entry: bool


class OpportunityEngine(Protocol):
    def build_episodes(
        self,
        *,
        candidate: CandidateDefinition,
        obs_ids,
        security_ids,
        session_ids,
        decision_ts,
        active_mask,
    ) -> Sequence[SignalEpisode]:
        ...

    def independent_entries(
        self,
        *,
        episodes: Sequence[SignalEpisode],
        holding_rule: str,
    ):
        ...
```

The exact definition of independence is candidate/target aware and must be
documented. It must not change silently between reports.

"Trades/day" always uses the complete number of eligible trading sessions in
the denominator.

---

## 85. Edge Dossier Object

Reference top-level object:

```python
@dataclass(slots=True)
class EdgeDossier:
    candidate: CandidateDefinition

    identity: dict
    economics: dict
    distribution: dict
    surface: dict
    interaction: dict
    chronology: dict
    event_path: dict
    episodes: dict
    cross_section: dict
    robustness: dict
    redundancy: dict
    provenance: dict
```

Recommended directory:

```text
runs/<run_id>/candidates/<candidate_id>/dossier/
├─ dossier.json
├─ summary.parquet
├─ distribution.parquet
├─ chronology.parquet
├─ horizon_ladder.parquet
├─ tail_ladder.parquet
├─ event_path.parquet
├─ episodes.parquet
├─ symbol_breakdown.parquet
├─ concentration.parquet
├─ surface_cells.parquet
└─ redundancy.parquet
```

The JSON file is navigation/metadata; large analytical data remains columnar.

---

## 86. Variant Expansion Contract

Variant expansion is explicit and trial-accounted.

```python
@dataclass(frozen=True, slots=True)
class VariantExpansionRequest:
    parent_pair_id: str
    reason_codes: tuple[str, ...]

    feature_a_variants: tuple[str, ...]
    feature_b_variants: tuple[str, ...]
    target_ids: tuple[str, ...]

    trial_family_id: str
```

Allowed reason codes should be finite and documented, e.g.:

```text
strong_global_structure
specialist_structure
resolution_structure
tail_structure
manual_research_request
audit_sample
```

Do not hide expanded tests inside the original canonical pair's trial count.

---

## 87. Causal Access Guard

Recommended location:

```text
src/quant_pipeline/governance/access.py
```

Reference contract:

```python
class SealedDataAccessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PeriodPolicy:
    discovery_end: object
    replication_start: object
    replication_end: object
    final_holdout_start: object

    allow_replication_access: bool
    allow_final_holdout_access: bool


def assert_timestamp_allowed(ts, policy: PeriodPolicy) -> None:
    if ts >= policy.final_holdout_start:
        if not policy.allow_final_holdout_access:
            raise SealedDataAccessError(
                f"Final holdout access denied for timestamp {ts}"
            )
        return

    if ts >= policy.replication_start:
        if not policy.allow_replication_access:
            raise SealedDataAccessError(
                f"Replication access denied for timestamp {ts}"
            )
```

This is defense in depth. Source readers should also receive the allowed period
explicitly so sealed rows are not casually loaded and then filtered later.

---

## 88. Replication Authorization Record

Opening sealed OOS data should create an explicit immutable record.

Example:

```json
{
  "candidate_id": "cand_...",
  "candidate_definition_hash": "...",
  "authorized_period": "replication",
  "authorized_at_utc": "...",
  "selection_run_id": "...",
  "dossier_artifact_hash": "...",
  "execution_methodology_hash": null
}
```

If execution methodology is part of the hypothesis, freeze/hash it before
replication.

A modified candidate after replication becomes a new candidate ID.

---

## 89. Telemetry API

Recommended location:

```text
src/quant_pipeline/telemetry/
```

Reference:

```python
class Telemetry:
    def event(self, event_type: str, **fields) -> None:
        ...

    def metric(self, name: str, value: float, **labels) -> None:
        ...

    def heartbeat(
        self,
        *,
        stage: str,
        completed: int,
        expected: int,
        shard_id: str | None = None,
    ) -> None:
        ...

    def update_status(self, **fields) -> None:
        ...
```

`STATUS.json` should be atomically rewritten.

`events.jsonl` and `metrics.jsonl` should be append-only for the run.

Minimal `STATUS.json`:

```json
{
  "run_id": "...",
  "status": "running",
  "stage": "canonical_duals",
  "started_at_utc": "...",
  "updated_at_utc": "...",
  "completed": 12450,
  "expected": 80000,
  "current_shard": "...",
  "cache_hit_fraction": 0.72,
  "pair_targets_per_sec": 11.3,
  "ram_gb": 21.4,
  "vram_gb": 9.7,
  "last_error": null,
  "heartbeat_counter": 145
}
```

---

## 90. Resume State

A run does not resume from a mutable Python checkpoint object.

It resumes from immutable completed artifacts plus stage/shard manifests.

Reference shard state:

```json
{
  "stage": "canonical_duals",
  "shard_id": "fa_004__fb_011__target_002",
  "input_hashes": ["...", "..."],
  "status": "complete",
  "output_artifact_hash": "...",
  "completed_at_utc": "..."
}
```

On restart:

1. rebuild the expected DAG;
2. compute expected artifact keys;
3. validate completed artifacts;
4. reuse valid matches;
5. schedule only missing/incompatible work.

---

## 91. Windows Worker Model

Do not use this pattern for large data:

```python
pool.map(worker, huge_dataframes)
```

Prefer:

```python
@dataclass(frozen=True, slots=True)
class FeatureWorkItem:
    feature_id: str
    observation_index_path: str
    input_artifact_paths: tuple[str, ...]
    output_key: ArtifactKey
```

Workers open immutable inputs/memmaps locally from compact descriptors.

Guidelines:

- long-lived bounded pools;
- no nested process pools;
- `OMP_NUM_THREADS=1` and equivalent BLAS limits inside workers;
- one coordinated writer for high-contention result stages where useful;
- no unbounded prefetch;
- no pinning tens of GB of host RAM.

---

## 92. Reference CLI

Recommended entry:

```text
src/quant_pipeline/__main__.py
```

A built-in `argparse` implementation is enough; a CLI framework is optional.

Required user-facing commands:

```text
python -m quant_pipeline run \
  --request configs/research/v3_discovery.yaml \
  --machine configs/machines/local.yaml

python -m quant_pipeline resume --run-id <id>

python -m quant_pipeline status --run-id <id>

python -m quant_pipeline replicate --candidate-id <id>

python -m quant_pipeline export-sip --candidate-id <id>
```

The actual command names may vary slightly, but there must remain one canonical
entrypoint.

---

## 93. Research DuckDB Build

`research.duckdb` is generated from completed analytical artifacts.

Reference conceptual SQL:

```sql
CREATE OR REPLACE VIEW dual_summary AS
SELECT * FROM read_parquet('dual_summary.parquet');

CREATE OR REPLACE VIEW surface_cells AS
SELECT * FROM read_parquet('surface_cells/*.parquet');

CREATE OR REPLACE VIEW edge_registry AS
SELECT * FROM read_parquet('edge_registry.parquet');

CREATE OR REPLACE VIEW candidate_summary AS
SELECT
    e.candidate_id,
    e.status,
    d.*
FROM edge_registry e
LEFT JOIN read_parquet('dossiers/*/summary.parquet') d
USING (candidate_id);
```

Do not mutate research truth by manually editing database rows.

The database is rebuildable.

---

## 94. Analysis Bundle Manifest

Example:

```json
{
  "run_id": "...",
  "source_snapshot_hash": "...",
  "research_config_hash": "...",
  "implementation_hash": "...",
  "discovery_period": ["2025-05-01", "2026-04-30"],
  "replication_accessed": false,
  "final_holdout_accessed": false,
  "artifacts": {
    "singles": "...",
    "duals": "...",
    "trial_ledger": "...",
    "edge_registry": "...",
    "research_duckdb": "..."
  }
}
```

GPT should be able to inspect one bundle and immediately know whether OOS data
was touched.

---

## 95. SIP Export Contract

Reference export schema:

| Column | Type |
|---|---|
| `candidate_id` | string |
| `security_id` | integer |
| `symbol` | string |
| `signal_ts_utc` | timestamp ns |
| `direction` | int8 |
| `reference_exit_ts_utc` | timestamp ns |
| `state_definition` | string |
| `feature_a_value` | float nullable |
| `feature_b_value` | float nullable |
| `resolution` | int8 |

The export contains **signals**, not simulated fills.

Raw quote/trade collection and execution analysis remain downstream.

---

## 96. Error Classes

Recommended explicit error taxonomy:

```python
class QuantPipelineError(Exception):
    pass


class CausalityError(QuantPipelineError):
    pass


class SealedDataAccessError(QuantPipelineError):
    pass


class ArtifactCorruptionError(QuantPipelineError):
    pass


class SchemaCompatibilityError(QuantPipelineError):
    pass


class NumericalParityError(QuantPipelineError):
    pass


class InvalidFeatureDefinitionError(QuantPipelineError):
    pass


class RecoverableResourceError(QuantPipelineError):
    pass
```

Known CUDA/RAM resource failures may be translated into
`RecoverableResourceError` and retried with smaller resource settings.

The correctness/governance errors above must stop the affected run.

---

## 97. Parity Test Pattern

Every optimized numerical path needs a small reference implementation.

Example pattern:

```python
def test_gpu_surface_scan_matches_cpu_reference():
    fixture = make_small_deterministic_surface_fixture(seed=7)

    cpu = CpuSurfaceScanner().scan(fixture.batch)
    gpu = TorchSurfaceScanner(device="cuda:0").scan(fixture.batch)

    assert_array_equal(cpu.counts, gpu.counts)
    assert_allclose(
        cpu.sums,
        gpu.sums,
        rtol=1e-6,
        atol=1e-7,
    )

    assert selected_state(cpu) == selected_state(gpu)
```

Tolerances must be declared centrally and should be tight enough that
candidate decisions do not flip silently.

---

## 98. Causality Test Pattern

Tests should intentionally create future information that would improve a
feature if leakage occurred.

Example conceptual test:

```python
def test_feature_cannot_see_future_bar():
    data_a = synthetic_market_data()

    data_b = data_a.copy()
    mutate_bars_strictly_after_decision_time(data_b)

    value_a = compute_feature_at_decision(data_a)
    value_b = compute_feature_at_decision(data_b)

    assert value_a == value_b
```

Do this for representative feature families and target timing boundaries.

---

## 99. Sealed-Period Test Pattern

```python
def test_discovery_reader_rejects_replication_rows():
    policy = discovery_only_policy()

    with raises(SealedDataAccessError):
        load_market_rows(
            start="2026-05-01",
            end="2026-05-02",
            policy=policy,
        )
```

Also verify that the completed discovery bundle says:

```text
replication_accessed = false
final_holdout_accessed = false
```

---

## 100. Cache Reuse Test Pattern

```python
def test_unrelated_report_change_does_not_invalidate_feature():
    key_before = feature_artifact_key(
        feature_spec=SPEC,
        source_snapshot_hash="abc",
        feature_engine_version="4",
    )

    key_after = feature_artifact_key(
        feature_spec=SPEC,
        source_snapshot_hash="abc",
        feature_engine_version="4",
    )

    assert key_before == key_after
```

Separately test that changing feature math/availability does invalidate it.

---

## 101. Resume Test Pattern

Integration test:

1. start a small run;
2. complete several shards;
3. terminate the process;
4. restart with `resume`;
5. verify completed shard hashes are reused;
6. verify missing shards run;
7. verify final output equals an uninterrupted reference run.

---

## 102. Discovery-Coverage Test

For a small fixture with known compatible concepts:

```python
def test_canonical_duals_do_not_depend_on_single_quality():
    weak_a = make_weak_single_feature("a")
    weak_b = make_weak_single_feature("b")

    planned_pairs = plan_canonical_duals([weak_a, weak_b])

    assert ("a", "b") in planned_pairs
```

Also test:

- negative selected states are retained;
- r3/r5/r10 results are independently addressable;
- unordered pairs are not duplicated;
- structural incompatibilities are recorded, not silently dropped.

---

## 103. Opportunity-Count Test

For a synthetic session fixture with repeated active observations:

```text
09:35 inactive
09:40 active
09:45 active
09:50 active
09:55 inactive
10:00 active
```

Expected behavior:

- first active block is one episode;
- second active block is a new episode;
- `fresh_signal_count = 2`;
- repeated rows inside one episode are not counted as six trades.

Test the all-session denominator used for opportunities/day.

---

## 104. Required Integration Smoke Run

Before running the full V2-sized dataset, V3 must pass a deterministic smoke
run containing:

```text
small symbol subset
small date range
representative feature families
representative target horizons
r3/r5/r10
singles
canonical dual
specialist probe
variant expansion
candidate materialization
dossier
analysis bundle
resume
```

The smoke run must finish end-to-end from the canonical CLI.

---

## 105. Build Phase Deliverables

Sol should implement V3 in the following sequence and stop at a clean checkpoint
after each phase.

### Phase 1 — Skeleton / Contracts

Deliver:

```text
package layout
pyproject / environment
contracts
config loading
hashing
artifact store interface
telemetry interface
CLI
stage DAG
tests
```

Acceptance:

```text
CLI launches
config validates
DAG plans
hashes are deterministic
atomic artifact test passes
STATUS/events/metrics are emitted
```

### Phase 2 — Data / Governance

Deliver:

```text
source snapshot contract
PIT security identity port
observation index
sealed-period guard
research-price semantics
feature/target registries
```

Acceptance:

```text
obs_id alignment tests
PIT tests
causality tests
sealed-period tests
V2 sample parity
```

### Phase 3 — Feature / Target Engine

Deliver:

```text
feature pack loader
dependency DAG
shared primitives
feature cache
target cache
canonical state/bin plane
```

Acceptance:

```text
representative V2 feature parity
target parity
incremental cache reuse
Windows worker memory behavior acceptable
```

### Phase 4 — Discovery Engine

Deliver:

```text
singles
CPU reference surface scanner
GPU optimized scanner
exhaustive compatible canonical duals
r3/r5/r10
full compact surfaces
specialist probe
trial ledger
variant-expansion queue
```

Acceptance:

```text
CPU/GPU parity
weak singles still enter dual scan
negative effects retained
complete trial reconciliation
resume after forced interruption
representative throughput benchmark
```

### Phase 5 — Forensics

Deliver:

```text
candidate freeze
opportunity/episode engine
full edge dossier
tails
horizons
event paths
marginal-vs-interaction lift
symbol/specialist detail
simultaneity
concentration / leave-best-out
cross-fitted discovery diagnostics
redundancy / edge families
```

Acceptance:

```text
one candidate can generate a complete dossier automatically
all return bases labeled
fold metrics labeled diagnostic, not true OOS
trades/day uses consistent opportunity engine
```

### Phase 6 — Analysis Bundle / SIP Handoff

Deliver:

```text
consolidated Parquet outputs
research.duckdb
bundle manifest
edge registry
data dictionary
SIP signal export
```

Acceptance:

```text
GPT can query all serious-candidate evidence from one bundle
bundle states whether replication/holdout were accessed
SIP export contains signals only
```

### Phase 7 — Performance / Reliability

Deliver:

```text
profiling
locality-aware tiling
target batching
bounded pinned staging if useful
GPU allocation reuse
feature-engine tuning
cache retention/compaction
stall watchdog
resource degradation/retry
```

Acceptance:

```text
no paging spiral
no repeated giant Windows-process copies
no hot-loop cache purge
safe OOM recovery
cold/warm/incremental benchmarks recorded
```

### Phase 8 — V2 Discovery Replay

Deliver:

```text
port all intended V2 canonical features/targets
full discovery-year V3 run
parity/reasoned-difference report
fresh V3 analysis bundle
```

Acceptance:

```text
2025-05-01 through 2026-04-30 discovery recreated
replication_accessed = false
final_holdout_accessed = false
known relationships can be located or differences explained
```

Only after Phase 8 should the project move into normal new-feature-factory
operation.

---

## 106. Sol/Codex Response Contract During the Build

For each requested phase, Sol should return a concise engineering report:

```text
PHASE:
STATUS:

FILES ADDED:
FILES MODIFIED:

TESTS:
- command
- pass/fail

BENCHMARKS:
- workload
- wall clock
- RAM
- VRAM
- throughput

PARITY:
- reference
- result

BLOCKERS:
- exact blocker or "none"

NEXT COMMAND:
- exact command
```

Do not spend large responses re-explaining the architecture already contained
in this file.

---

## 107. What Sol Must Not Do

Do not:

- create multiple competing pipeline entrypoints;
- silently use sealed OOS data;
- restore the `single_survivors` dual gate;
- discard negative relationships;
- pick r10 merely because it is the highest resolution;
- label discovery folds as true OOS;
- globally brute-force all variants against all variants;
- mix frequency-weighted contribution with active bp/state;
- count repeated active rows as independent trades;
- hide failed/missing trials;
- make `research.duckdb` the only source of truth;
- pass giant DataFrames through Windows multiprocessing queues;
- optimize GPU utilization while making wall clock worse;
- add distributed/cloud infrastructure to solve a single-machine problem;
- rewrite proven V2 timing/PIT logic without parity tests;
- perform execution/fill simulation in the discovery pipeline;
- output automated portfolio recommendations.

---

## 108. Definition of V3 Ready for Research

V3 is ready for normal feature research only when all of the following are true:

1. The clean repository builds from documented dependencies.
2. One canonical CLI starts the pipeline.
3. A crashed run resumes without recomputing valid completed artifacts.
4. The source snapshot and `obs_id` contracts are deterministic.
5. PIT membership and feature availability remain causal.
6. Sealed replication/holdout access is denied during discovery.
7. New feature packs can be added without editing orchestration code.
8. Canonical singles are fully recorded but do not gate canonical duals.
9. Every compatible canonical pair is accounted for.
10. r3/r5/r10 are retained independently.
11. Both positive and negative conditional effects survive discovery.
12. Full state surfaces are retained.
13. Hierarchical variant expansion is trial-accounted.
14. Specialist/global-cancellation structure is available.
15. Candidate definitions are frozen and hashable.
16. One common engine produces episodes/independent opportunity counts.
17. Serious candidates generate complete dossiers.
18. Discovery-year folds/cross-fitting are labeled diagnostics.
19. The analysis bundle can be inspected without traversing raw cache internals.
20. CPU/GPU optimized paths pass parity tests.
21. The system runs within the current 32 GB RAM / 12 GB VRAM constraints.
22. Cold/warm/incremental performance is measured honestly.
23. The full discovery run can complete unattended or recover from known
    resource failures.
24. The pipeline outputs research data rather than recommendations.
25. A candidate can be explicitly promoted to sealed replication without
    changing its definition.
26. The V3 repository runs from its own `.venv` with no runtime import or cache
    dependency on V2.
27. The existing candle/source-data root is referenced read-only and no V3
    generated artifact is written into it.

---


# PART III-B — COPY-READY REFERENCE IMPLEMENTATION

This section is intentionally different from the preceding contracts.

The preceding section defines **what the public interfaces and data contracts
are**. This section shows a concrete implementation that Sol can use as the
starting point for the real V3 repository.

The code is meant to eliminate architectural invention. It is not meant to
pre-optimize every numerical kernel before V2 parity tests exist.

The implementation strategy is:

```text
first make the entire V3 pipeline correct and runnable
    ↓
prove V2 parity where semantics are unchanged
    ↓
profile the real workload
    ↓
optimize the hot paths without changing public contracts
```

The following pieces are deliberately left to be ported from V2 rather than
invented here:

- exact market-data loader/provider adapters;
- exact PIT universe rules;
- exact corporate-action/research-price rules;
- exact V2 feature formulas;
- exact V2 target formulas;
- exact V2 bin/tie semantics;
- the final optimized CUDA kernel shape.

Everything surrounding those pieces can be implemented directly from this
section.

---

## 109. Concrete Package Tree

Build this tree first:

```text
Quant-Pipeline-V3/
├─ V3_MASTER_SPEC.md
├─ README.md
├─ pyproject.toml
├─ .gitignore
│
├─ configs/
│  ├─ research/
│  │  └─ v3_discovery.yaml
│  └─ machines/
│     └─ local.example.yaml
│
├─ feature_packs/
│  ├─ builtin/
│  │  └─ v2_port/
│  └─ experimental/
│
├─ src/
│  └─ quant_pipeline/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ config.py
│     ├─ contracts.py
│     ├─ hashing.py
│     ├─ errors.py
│     ├─ context.py
│     │
│     ├─ orchestration/
│     │  ├─ __init__.py
│     │  ├─ stage.py
│     │  ├─ dag.py
│     │  └─ runner.py
│     │
│     ├─ cache/
│     │  ├─ __init__.py
│     │  ├─ manifest.py
│     │  └─ store.py
│     │
│     ├─ telemetry/
│     │  ├─ __init__.py
│     │  └─ telemetry.py
│     │
│     ├─ governance/
│     │  ├─ __init__.py
│     │  └─ access.py
│     │
│     ├─ data/
│     │  ├─ __init__.py
│     │  ├─ snapshot.py
│     │  ├─ observation_index.py
│     │  └─ provider.py
│     │
│     ├─ registry/
│     │  ├─ __init__.py
│     │  ├─ features.py
│     │  └─ targets.py
│     │
│     ├─ features/
│     │  ├─ __init__.py
│     │  ├─ base.py
│     │  ├─ engine.py
│     │  └─ state_store.py
│     │
│     ├─ targets/
│     │  ├─ __init__.py
│     │  ├─ base.py
│     │  └─ engine.py
│     │
│     ├─ discovery/
│     │  ├─ __init__.py
│     │  ├─ planner.py
│     │  ├─ trials.py
│     │  ├─ single_scan.py
│     │  ├─ surface_cpu.py
│     │  ├─ surface_torch.py
│     │  ├─ dual_scan.py
│     │  ├─ specialist.py
│     │  └─ variants.py
│     │
│     ├─ candidates/
│     │  ├─ __init__.py
│     │  ├─ identity.py
│     │  └─ registry.py
│     │
│     ├─ forensics/
│     │  ├─ __init__.py
│     │  ├─ opportunities.py
│     │  ├─ distribution.py
│     │  ├─ chronology.py
│     │  ├─ interaction.py
│     │  ├─ dossier.py
│     │  └─ redundancy.py
│     │
│     ├─ analysis_bundle/
│     │  ├─ __init__.py
│     │  └─ builder.py
│     │
│     └─ execution_data/
│        ├─ __init__.py
│        └─ sip_export.py
│
└─ tests/
   ├─ unit/
   ├─ integration/
   └─ fixtures/
```

Do not add a second application package or a parallel "legacy runner".

---

## 110. `pyproject.toml`

Use a modern, boring dependency set.

```toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "quant-pipeline-v3"
version = "0.1.0"
requires-python = ">=3.12,<3.14"
dependencies = [
    "numpy>=2.1,<3",
    "pyarrow>=18,<23",
    "duckdb>=1.3,<2",
    "polars>=1.30,<2",
    "pydantic>=2.10,<3",
    "PyYAML>=6.0,<7",
    "psutil>=6,<8",
    "torch>=2.7,<3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8,<10",
    "pytest-xdist>=3,<4",
    "ruff>=0.11,<1",
]
numba = [
    "numba>=0.61,<1",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
line-length = 100
target-version = "py312"
```

The versions above are a compatibility starting point, not a claim about the
latest package releases. During the actual build, Codex should resolve a
mutually compatible current Python/NumPy/PyArrow/DuckDB/Polars/Torch set for
the workstation, record the resolved versions in the lock/environment output,
and verify that Torch sees the RTX 3080 Ti. Never install a CPU-only Torch build
by accident and never modify the global Python environment.

---

## 111. `errors.py`

```python
class QuantPipelineError(Exception):
    """Base V3 error."""


class ConfigurationError(QuantPipelineError):
    pass


class CausalityError(QuantPipelineError):
    pass


class SealedDataAccessError(QuantPipelineError):
    pass


class ArtifactCorruptionError(QuantPipelineError):
    pass


class SchemaCompatibilityError(QuantPipelineError):
    pass


class NumericalParityError(QuantPipelineError):
    pass


class InvalidFeatureDefinitionError(QuantPipelineError):
    pass


class RecoverableResourceError(QuantPipelineError):
    pass
```

---

## 112. Concrete `config.py`

Use Pydantic only for configuration/validation; do not put giant runtime arrays
inside Pydantic models.

```python
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PeriodConfig(StrictModel):
    start: date
    end: date | None = None
    sealed: bool = False


class PeriodsConfig(StrictModel):
    discovery: PeriodConfig
    replication: PeriodConfig
    final_holdout: PeriodConfig

    @model_validator(mode="after")
    def chronological(self):
        d = self.discovery
        r = self.replication
        h = self.final_holdout

        if d.end is None or r.end is None:
            raise ValueError("Discovery and replication must have finite end dates.")

        if not (d.start <= d.end < r.start <= r.end < h.start):
            raise ValueError("Discovery/replication/final holdout periods overlap or reorder.")

        if not r.sealed:
            raise ValueError("Replication period must be sealed in normal research config.")

        if not h.sealed:
            raise ValueError("Final holdout must be sealed in normal research config.")

        return self


class DiscoveryConfig(StrictModel):
    canonical_duals: Literal["exhaustive_compatible"] = "exhaustive_compatible"
    single_parent_gate: bool = False
    retain_negative_effects: bool = True


class ForensicsConfig(StrictModel):
    enabled: bool = True
    candidate_policy: str = "permissive_structural"


class ResearchConfig(StrictModel):
    run_name: str
    mode: Literal["incremental", "full-canonical"]

    periods: PeriodsConfig

    allow_replication_access: bool = False
    allow_final_holdout_access: bool = False

    resolutions: tuple[int, ...] = (3, 5, 10)

    feature_packs: tuple[str, ...]
    targets: tuple[str, ...]

    discovery: DiscoveryConfig = DiscoveryConfig()
    forensics: ForensicsConfig = ForensicsConfig()

    @model_validator(mode="after")
    def invariants(self):
        if self.discovery.single_parent_gate:
            raise ValueError(
                "V3 canonical dual discovery may not be gated by single survivors."
            )

        if set(self.resolutions) != {3, 5, 10}:
            raise ValueError("Initial V3 contract requires r3/r5/r10.")

        return self


class ResourceBudget(StrictModel):
    ram_gb: float = 32.0
    reserve_ram_gb: float = 6.0
    vram_soft_limit_gb: float = 10.0


class MachineConfig(StrictModel):
    data_root: Path
    cache_root: Path
    run_root: Path
    scratch_root: Path
    duckdb_temp: Path

    gpu_device: str = "cuda:0"

    resource_budget: ResourceBudget = ResourceBudget()

    feature_workers: int = Field(default=6, ge=1, le=16)
    duckdb_threads: int = Field(default=5, ge=1, le=16)
    duckdb_memory_limit_gb: float = Field(default=18, gt=1)

    blas_threads_per_worker: int = 1
    omp_threads_per_worker: int = 1


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        value = yaml.safe_load(f)

    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")

    return value


def load_research_config(path: Path) -> ResearchConfig:
    return ResearchConfig.model_validate(load_yaml(path))


def load_machine_config(path: Path) -> MachineConfig:
    return MachineConfig.model_validate(load_yaml(path))
```

---

## 113. Concrete `hashing.py`

```python
from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _canonical(dataclasses.asdict(value))

    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="json"))

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, Path):
        return value.as_posix()

    if isinstance(value, dict):
        return {
            str(k): _canonical(v)
            for k, v in sorted(value.items(), key=lambda x: str(x[0]))
        }

    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]

    if isinstance(value, set):
        return sorted(_canonical(v) for v in value)

    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        while block := f.read(block_size):
            h.update(block)

    return h.hexdigest()
```

---

## 114. Concrete `contracts.py`

Use the contracts from the previous section with this implementation-level
addition:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    feature_id: str
    concept_id: str
    family: str
    grid: str
    canonical: bool

    required_inputs: tuple[str, ...]
    required_history_bars: int

    availability_rule: str
    price_basis: str

    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()

    implementation_id: str = ""
    output_dtype: str = "float32"
    definition_hash: str = ""


@dataclass(frozen=True, slots=True)
class TargetSpec:
    target_id: str
    family: str
    grid: str
    horizon_minutes: int | None

    return_basis: str
    entry_rule: str
    exit_rule: str
    same_day_requirement: bool
    validity_rule: str

    benchmark_definition: str | None = None
    residual_definition: str | None = None

    implementation_id: str = ""
    output_dtype: str = "float32"
    definition_hash: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactKey:
    artifact_type: str
    semantic_id: str
    content_hash: str
    schema_version: int = 1

    @property
    def short_hash(self) -> str:
        return self.content_hash[:16]


@dataclass(frozen=True, slots=True)
class CandidateDefinition:
    candidate_id: str
    feature_a_id: str
    feature_b_id: str | None
    target_id: str
    grid: str
    resolution: int
    state_payload: Mapping[str, JsonValue]
    state_definition: str
    direction: int
    source_snapshot_hash: str
    selection_run_id: str
    selection_trial_id: str
    return_basis: str
    definition_hash: str


@dataclass(frozen=True, slots=True)
class StageResult:
    stage_name: str
    output_keys: tuple[ArtifactKey, ...]
    metrics: Mapping[str, JsonValue]
    warnings: tuple[str, ...] = ()
```

When a spec is compiled, compute `definition_hash` from all semantic fields
except the hash itself.

---

## 115. Concrete Artifact Store

`cache/store.py`:

```python
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from quant_pipeline.contracts import ArtifactKey
from quant_pipeline.errors import ArtifactCorruptionError
from quant_pipeline.hashing import sha256_file


class LocalArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, key: ArtifactKey) -> Path:
        return (
            self.root
            / key.artifact_type
            / key.content_hash[:2]
            / key.content_hash
        )

    def data_path(self, key: ArtifactKey, suffix: str) -> Path:
        return self._dir(key) / f"data{suffix}"

    def manifest_path(self, key: ArtifactKey) -> Path:
        return self._dir(key) / "manifest.json"

    def has_complete(self, key: ArtifactKey) -> bool:
        manifest = self.manifest_path(key)
        if not manifest.exists():
            return False

        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            return False

        return payload.get("status") == "complete"

    def begin_file(self, key: ArtifactKey, suffix: str) -> Path:
        final_dir = self._dir(key)
        final_dir.parent.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{key.short_hash}.",
                dir=final_dir.parent,
            )
        )

        return tmp_dir / f"data{suffix}.partial"

    def commit_file(
        self,
        *,
        key: ArtifactKey,
        partial_path: Path,
        suffix: str,
        manifest_payload: dict,
    ) -> Path:
        if not partial_path.exists():
            raise FileNotFoundError(partial_path)

        final_dir = self._dir(key)
        if final_dir.exists():
            if self.has_complete(key):
                shutil.rmtree(partial_path.parent, ignore_errors=True)
                return self.data_path(key, suffix)

            raise ArtifactCorruptionError(
                f"Incomplete/corrupt artifact directory already exists: {final_dir}"
            )

        tmp_dir = partial_path.parent
        data_name = f"data{suffix}"
        complete_data = tmp_dir / data_name
        os.replace(partial_path, complete_data)

        manifest_payload = dict(manifest_payload)
        manifest_payload.update(
            {
                "artifact_type": key.artifact_type,
                "semantic_id": key.semantic_id,
                "content_hash": key.content_hash,
                "schema_version": key.schema_version,
                "data_file": data_name,
                "checksum": sha256_file(complete_data),
                "status": "complete",
            }
        )

        manifest_tmp = tmp_dir / "manifest.json.partial"
        manifest_tmp.write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(manifest_tmp, tmp_dir / "manifest.json")

        # tmp_dir and final_dir share a parent/volume.
        os.replace(tmp_dir, final_dir)

        return final_dir / data_name

    def validate_file(
        self,
        key: ArtifactKey,
    ) -> Path:
        manifest_path = self.manifest_path(key)

        if not manifest_path.exists():
            raise ArtifactCorruptionError(f"Missing manifest: {manifest_path}")

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        if payload.get("status") != "complete":
            raise ArtifactCorruptionError(f"Artifact not complete: {key}")

        data = self._dir(key) / payload["data_file"]

        if not data.exists():
            raise ArtifactCorruptionError(f"Missing artifact data: {data}")

        observed = sha256_file(data)

        if observed != payload["checksum"]:
            raise ArtifactCorruptionError(
                f"Checksum mismatch for {data}: {observed} != {payload['checksum']}"
            )

        return data
```

This is enough for file artifacts. Add directory-artifact support only when a
real stage requires it.

---

## 116. Concrete Telemetry

`telemetry/telemetry.py`:

```python
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Telemetry:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.status_path = run_dir / "STATUS.json"
        self.events_path = run_dir / "events.jsonl"
        self.metrics_path = run_dir / "metrics.jsonl"

        self._lock = threading.Lock()

    def _append_jsonl(self, path: Path, payload: dict) -> None:
        line = json.dumps(payload, separators=(",", ":"), default=str)

        with self._lock:
            with path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
                f.flush()

    def event(self, event_type: str, **fields: Any) -> None:
        self._append_jsonl(
            self.events_path,
            {
                "ts_utc": utc_now(),
                "event_type": event_type,
                **fields,
            },
        )

    def metric(self, name: str, value: float, **labels: Any) -> None:
        self._append_jsonl(
            self.metrics_path,
            {
                "ts_utc": utc_now(),
                "name": name,
                "value": value,
                "labels": labels,
            },
        )

    def update_status(self, **fields: Any) -> None:
        rss = psutil.Process().memory_info().rss / (1024 ** 3)

        payload = {
            "updated_at_utc": utc_now(),
            "rss_gb": round(rss, 3),
            **fields,
        }

        tmp = self.status_path.with_suffix(".json.partial")
        tmp.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, self.status_path)

    def heartbeat(
        self,
        *,
        stage: str,
        completed: int,
        expected: int,
        shard_id: str | None = None,
        **fields: Any,
    ) -> None:
        self.update_status(
            status="running",
            stage=stage,
            completed=completed,
            expected=expected,
            current_shard=shard_id,
            **fields,
        )
```

GPU metrics can be added through Torch/NVML behind an optional provider. Do not
make telemetry failure crash the research run.

---

## 117. Concrete Sealed-Period Guard

`governance/access.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from quant_pipeline.errors import SealedDataAccessError


@dataclass(frozen=True, slots=True)
class PeriodPolicy:
    discovery_start: date
    discovery_end: date

    replication_start: date
    replication_end: date

    final_holdout_start: date

    allow_replication_access: bool = False
    allow_final_holdout_access: bool = False


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def assert_date_allowed(value: date | datetime, policy: PeriodPolicy) -> None:
    d = _as_date(value)

    if d >= policy.final_holdout_start:
        if not policy.allow_final_holdout_access:
            raise SealedDataAccessError(
                f"Final holdout access denied for {d}"
            )
        return

    if policy.replication_start <= d <= policy.replication_end:
        if not policy.allow_replication_access:
            raise SealedDataAccessError(
                f"Replication access denied for {d}"
            )
        return

    if not (policy.discovery_start <= d <= policy.discovery_end):
        raise SealedDataAccessError(
            f"Date {d} is outside currently authorized research periods"
        )


def authorized_date_range(policy: PeriodPolicy) -> tuple[date, date]:
    if policy.allow_final_holdout_access:
        raise ValueError(
            "Open-ended final-holdout range must be resolved explicitly by caller."
        )

    if policy.allow_replication_access:
        return policy.discovery_start, policy.replication_end

    return policy.discovery_start, policy.discovery_end
```

Data providers should receive the authorized range **before reading files**.

---

## 118. Concrete Observation Index Builder

`data/observation_index.py`:

The observation index must include both a global immutable `obs_id` and a
per-security/session sequence used for episode continuity. Do **not** infer
episode continuity from global `obs_id + 1`.

```python
from __future__ import annotations

import polars as pl
import pyarrow as pa


REQUIRED_INPUT_COLUMNS = (
    "security_id",
    "symbol",
    "session_id",
    "session_date",
    "decision_ts_utc",
    "grid_id",
    "universe_eligible",
)


def build_observation_index(rows: pa.Table) -> pa.Table:
    missing = [
        c
        for c in REQUIRED_INPUT_COLUMNS
        if c not in rows.column_names
    ]

    if missing:
        raise ValueError(
            f"Observation-index input missing columns: {missing}"
        )

    df = pl.from_arrow(rows)

    df = (
        df
        .filter(pl.col("universe_eligible").fill_null(False))
        .sort(
            [
                "security_id",
                "session_id",
                "grid_id",
                "decision_ts_utc",
            ]
        )
        .with_columns(
            pl.int_range(0, pl.len(), dtype=pl.Int32)
            .over(["security_id", "session_id", "grid_id"])
            .alias("security_session_seq")
        )
        .sort(
            [
                "decision_ts_utc",
                "security_id",
                "grid_id",
            ]
        )
        .with_row_index("obs_id")
        .with_columns(pl.col("obs_id").cast(pl.Int64))
    )

    desired = [
        "obs_id",
        "security_id",
        "symbol",
        "session_id",
        "security_session_seq",
        "session_date",
        "decision_ts_utc",
        "grid_id",
        "universe_eligible",
    ]

    if "entry_reference_ts_utc" in df.columns:
        desired.append("entry_reference_ts_utc")

    out = df.select(desired).to_arrow()

    validate_observation_index(out)
    return out


def validate_observation_index(table: pa.Table) -> None:
    n = table.num_rows

    if n == 0:
        raise ValueError("Observation index is empty")

    obs = (
        table["obs_id"]
        .combine_chunks()
        .to_numpy(zero_copy_only=False)
    )

    if obs[0] != 0 or obs[-1] != n - 1:
        raise ValueError(
            "obs_id must be contiguous from 0 to N-1"
        )

    if not (obs[1:] > obs[:-1]).all():
        raise ValueError(
            "obs_id must be strictly increasing"
        )

    required = {
        "session_id",
        "security_session_seq",
    }

    missing = required - set(table.column_names)

    if missing:
        raise ValueError(
            f"Observation index missing continuity columns: {sorted(missing)}"
        )
```

The production data provider is responsible for supplying the authoritative
PIT-eligible decision rows and stable `session_id` values using the ported V2
semantics. The index builder creates only row identities/order and
`security_session_seq`; it does not redefine what a valid trading session is.

All downstream feature/target/state arrays align to this index by `obs_id`.
Episode continuity uses `security_session_seq`, not global row adjacency.

---

## 119. Concrete Registry Compilation

`registry/features.py`:

```python
from __future__ import annotations

from dataclasses import replace

from quant_pipeline.contracts import FeatureSpec
from quant_pipeline.hashing import content_hash


SEMANTIC_FEATURE_FIELDS = (
    "feature_id",
    "concept_id",
    "family",
    "grid",
    "canonical",
    "required_inputs",
    "required_history_bars",
    "availability_rule",
    "price_basis",
    "parameters",
    "dependencies",
    "implementation_id",
    "output_dtype",
)


def compile_feature_spec(spec: FeatureSpec) -> FeatureSpec:
    payload = {
        field: getattr(spec, field)
        for field in SEMANTIC_FEATURE_FIELDS
    }

    return replace(spec, definition_hash=content_hash(payload))


class FeatureRegistry:
    def __init__(self):
        self._by_id: dict[str, FeatureSpec] = {}

    def register(self, spec: FeatureSpec) -> None:
        spec = compile_feature_spec(spec)

        existing = self._by_id.get(spec.feature_id)
        if existing is not None and existing.definition_hash != spec.definition_hash:
            raise ValueError(
                f"Feature ID collision with different semantics: {spec.feature_id}"
            )

        self._by_id[spec.feature_id] = spec

    def get(self, feature_id: str) -> FeatureSpec:
        return self._by_id[feature_id]

    def all(self) -> tuple[FeatureSpec, ...]:
        return tuple(self._by_id.values())

    def canonical(self) -> tuple[FeatureSpec, ...]:
        return tuple(x for x in self._by_id.values() if x.canonical)
```

Use the same pattern for `TargetRegistry`.

---

## 120. Concrete Feature-Pack Loader

Use explicit pack modules rather than auto-importing every Python file found on
disk.

`feature_packs/builtin/v2_port/specs.py` should expose:

```python
FEATURE_SPECS: tuple[FeatureSpec, ...] = (...)
FEATURE_IMPLEMENTATIONS: dict[str, object] = {...}
```

Loader:

```python
from __future__ import annotations

import importlib


PACK_MODULES = {
    "builtin_v2_port": "feature_packs.builtin.v2_port.specs",
}


def load_feature_pack(pack_id: str):
    try:
        module_name = PACK_MODULES[pack_id]
    except KeyError as exc:
        raise ValueError(f"Unknown feature pack: {pack_id}") from exc

    module = importlib.import_module(module_name)

    specs = tuple(module.FEATURE_SPECS)
    implementations = dict(module.FEATURE_IMPLEMENTATIONS)

    for spec in specs:
        if spec.implementation_id not in implementations:
            raise ValueError(
                f"{spec.feature_id} references missing implementation "
                f"{spec.implementation_id}"
            )

    return specs, implementations
```

Experimental packs can be added to a manifest/registry without editing
discovery code.

---

## 121. Concrete Feature Engine

`features/engine.py`:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np

from quant_pipeline.contracts import ArtifactKey, FeatureSpec
from quant_pipeline.hashing import content_hash


def feature_artifact_key(
    *,
    spec: FeatureSpec,
    source_snapshot_hash: str,
    observation_index_hash: str,
    dependency_hashes: tuple[str, ...],
    feature_engine_version: str,
) -> ArtifactKey:
    payload = {
        "source_snapshot_hash": source_snapshot_hash,
        "observation_index_hash": observation_index_hash,
        "feature_definition_hash": spec.definition_hash,
        "dependency_hashes": dependency_hashes,
        "feature_engine_version": feature_engine_version,
    }

    return ArtifactKey(
        artifact_type="feature",
        semantic_id=spec.feature_id,
        content_hash=content_hash(payload),
    )


def compute_feature(
    *,
    spec: FeatureSpec,
    implementation,
    observation_index,
    inputs: dict,
    output_path: Path,
) -> None:
    values = implementation.compute(
        spec=spec,
        observation_index=observation_index,
        inputs=inputs,
    )

    values = np.asarray(values)

    if values.ndim != 1:
        raise ValueError(f"{spec.feature_id}: expected one-dimensional output")

    if len(values) != observation_index.num_rows:
        raise ValueError(
            f"{spec.feature_id}: feature length does not match observation index"
        )

    if values.dtype != np.dtype(spec.output_dtype):
        values = values.astype(spec.output_dtype, copy=False)

    mm = np.lib.format.open_memmap(
        output_path,
        mode="w+",
        dtype=values.dtype,
        shape=values.shape,
    )
    mm[:] = values
    mm.flush()
```

The real engine should process dependencies topologically and avoid loading all
features simultaneously into RAM.

---

## 122. Concrete Target Engine

Use the same content-addressed pattern.

```python
def target_artifact_key(
    *,
    spec: TargetSpec,
    source_snapshot_hash: str,
    observation_index_hash: str,
    target_engine_version: str,
) -> ArtifactKey:
    return ArtifactKey(
        artifact_type="target",
        semantic_id=spec.target_id,
        content_hash=content_hash(
            {
                "source_snapshot_hash": source_snapshot_hash,
                "observation_index_hash": observation_index_hash,
                "target_definition_hash": spec.definition_hash,
                "target_engine_version": target_engine_version,
            }
        ),
    )
```

Persist target values and validity as separate compact arrays:

```text
target_<id>.npy
target_<id>.valid.npy
```

or one structured artifact if benchmarking shows that is faster.

Do not encode invalid observations as a magic numeric return.

---

## 123. Concrete Canonical State Store

Correctness first: support explicit states per resolution.

`features/state_store.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


INVALID_STATE = np.uint8(255)


@dataclass(frozen=True, slots=True)
class StatePaths:
    feature_id: str
    r3: Path
    r5: Path
    r10: Path


class StateStore:
    def __init__(self):
        self._paths: dict[str, StatePaths] = {}

    def register(self, paths: StatePaths) -> None:
        self._paths[paths.feature_id] = paths

    def open(
        self,
        feature_id: str,
        resolution: int,
        mode: str = "r",
    ) -> np.ndarray:
        paths = self._paths[feature_id]

        path = {
            3: paths.r3,
            5: paths.r5,
            10: paths.r10,
        }[resolution]

        return np.load(path, mmap_mode=mode)
```

After V2 parity is proven, V3 may replace three explicit arrays with one compact
rank/state representation **only if** derived r3/r5/r10 match the reference
states exactly under the declared parity contract.

---

## 124. Concrete Pair Planner

`discovery/planner.py`:

```python
from __future__ import annotations

from itertools import combinations

from quant_pipeline.contracts import FeatureSpec


def structurally_compatible(a: FeatureSpec, b: FeatureSpec) -> bool:
    if a.grid != b.grid:
        return False

    if a.feature_id == b.feature_id:
        return False

    # Add only genuine semantic incompatibilities here.
    # Never add "single was weak" as a compatibility rule.
    return True


def canonical_pair_id(a: str, b: str) -> str:
    left, right = sorted((a, b))
    return f"{left}__X__{right}"


def plan_canonical_pairs(
    features: tuple[FeatureSpec, ...],
) -> list[tuple[str, FeatureSpec, FeatureSpec]]:
    canonical = sorted(
        (x for x in features if x.canonical),
        key=lambda x: x.feature_id,
    )

    planned = []

    for a, b in combinations(canonical, 2):
        if structurally_compatible(a, b):
            planned.append((canonical_pair_id(a.feature_id, b.feature_id), a, b))

    return planned
```

The planner must also write structural exclusions to the trial ledger.

---

## 125. Concrete CPU Reference Surface Scanner

This is the correctness reference for one pair/target/resolution.

`discovery/surface_cpu.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

INVALID_STATE = np.uint8(255)


@dataclass(frozen=True, slots=True)
class SurfaceStats:
    resolution: int
    counts: np.ndarray
    sums_bps: np.ndarray
    means_bps: np.ndarray


def scan_surface_cpu(
    *,
    state_a: np.ndarray,
    state_b: np.ndarray,
    target_bps: np.ndarray,
    target_valid: np.ndarray,
    resolution: int,
) -> SurfaceStats:
    a = np.asarray(state_a)
    b = np.asarray(state_b)
    y = np.asarray(target_bps)
    valid_y = np.asarray(target_valid, dtype=bool)

    if not (len(a) == len(b) == len(y) == len(valid_y)):
        raise ValueError("Surface inputs must have identical observation length.")

    valid = (
        valid_y
        & (a != INVALID_STATE)
        & (b != INVALID_STATE)
        & (a < resolution)
        & (b < resolution)
        & np.isfinite(y)
    )

    cell_count = resolution * resolution

    if not valid.any():
        return SurfaceStats(
            resolution=resolution,
            counts=np.zeros((resolution, resolution), dtype=np.int64),
            sums_bps=np.zeros((resolution, resolution), dtype=np.float64),
            means_bps=np.full((resolution, resolution), np.nan, dtype=np.float64),
        )

    cell = (
        a[valid].astype(np.int64) * resolution
        + b[valid].astype(np.int64)
    )

    counts = np.bincount(
        cell,
        minlength=cell_count,
    ).astype(np.int64, copy=False)

    sums = np.bincount(
        cell,
        weights=y[valid].astype(np.float64, copy=False),
        minlength=cell_count,
    )

    means = np.full(cell_count, np.nan, dtype=np.float64)

    np.divide(
        sums,
        counts,
        out=means,
        where=counts > 0,
    )

    shape = (resolution, resolution)

    return SurfaceStats(
        resolution=resolution,
        counts=counts.reshape(shape),
        sums_bps=sums.reshape(shape),
        means_bps=means.reshape(shape),
    )
```

This scanner is simple enough to audit and must remain in the codebase even
after a faster GPU path exists.

---

## 126. Concrete Torch GPU Surface Scanner

This is a correct first GPU implementation. It is not claimed to be the final
highest-throughput kernel.

`discovery/surface_torch.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from quant_pipeline.discovery.surface_cpu import SurfaceStats


INVALID_STATE = 255


class TorchSurfaceScanner:
    def __init__(
        self,
        *,
        device: str = "cuda:0",
    ):
        self.device = torch.device(device)

        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")

    @torch.inference_mode()
    def scan_one(
        self,
        *,
        state_a: np.ndarray,
        state_b: np.ndarray,
        target_bps: np.ndarray,
        target_valid: np.ndarray,
        resolution: int,
    ) -> SurfaceStats:
        a = torch.as_tensor(state_a, device=self.device)
        b = torch.as_tensor(state_b, device=self.device)
        y = torch.as_tensor(target_bps, device=self.device, dtype=torch.float32)
        valid_y = torch.as_tensor(target_valid, device=self.device, dtype=torch.bool)

        valid = (
            valid_y
            & (a != INVALID_STATE)
            & (b != INVALID_STATE)
            & (a < resolution)
            & (b < resolution)
            & torch.isfinite(y)
        )

        cell_count = resolution * resolution

        if not bool(valid.any()):
            counts = torch.zeros(cell_count, device=self.device, dtype=torch.int64)
            sums = torch.zeros(cell_count, device=self.device, dtype=torch.float64)
        else:
            cell = (
                a[valid].to(torch.int64) * resolution
                + b[valid].to(torch.int64)
            )

            counts = torch.bincount(
                cell,
                minlength=cell_count,
            )

            sums = torch.bincount(
                cell,
                weights=y[valid].to(torch.float64),
                minlength=cell_count,
            )

        means = torch.full(
            (cell_count,),
            float("nan"),
            device=self.device,
            dtype=torch.float64,
        )

        nonzero = counts > 0
        means[nonzero] = sums[nonzero] / counts[nonzero]

        shape = (resolution, resolution)

        return SurfaceStats(
            resolution=resolution,
            counts=counts.reshape(shape).cpu().numpy(),
            sums_bps=sums.reshape(shape).cpu().numpy(),
            means_bps=means.reshape(shape).cpu().numpy(),
        )
```

First acceptance test:

```python
cpu = scan_surface_cpu(...)
gpu = TorchSurfaceScanner().scan_one(...)

np.testing.assert_array_equal(cpu.counts, gpu.counts)
np.testing.assert_allclose(cpu.sums_bps, gpu.sums_bps, rtol=1e-7, atol=1e-7)
np.testing.assert_allclose(
    cpu.means_bps,
    gpu.means_bps,
    rtol=1e-7,
    atol=1e-7,
    equal_nan=True,
)
```

---

## 127. Batched GPU Scanner Used for Real Discovery

The real scanner should batch feature pairs and stream observation chunks.

This implementation is concrete enough to start with and bounds GPU memory.

```python
from __future__ import annotations

import numpy as np
import torch


class BatchedTorchSurfaceScanner:
    def __init__(
        self,
        *,
        device: str = "cuda:0",
        observation_chunk: int = 1_000_000,
    ):
        self.device = torch.device(device)
        self.observation_chunk = observation_chunk

    @torch.inference_mode()
    def scan_pair_batch(
        self,
        *,
        states_a: np.ndarray,       # [P, N], uint8
        states_b: np.ndarray,       # [P, N], uint8
        target_bps: np.ndarray,     # [N]
        target_valid: np.ndarray,   # [N]
        resolution: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        if states_a.shape != states_b.shape:
            raise ValueError("Pair-batch state matrices must have same shape.")

        pair_count, obs_count = states_a.shape
        cells = resolution * resolution

        counts = torch.zeros(
            (pair_count, cells),
            dtype=torch.int64,
            device=self.device,
        )

        sums = torch.zeros(
            (pair_count, cells),
            dtype=torch.float64,
            device=self.device,
        )

        pair_offset = (
            torch.arange(pair_count, device=self.device, dtype=torch.int64)
            * cells
        ).unsqueeze(1)

        flat_count_size = pair_count * cells

        for start in range(0, obs_count, self.observation_chunk):
            stop = min(start + self.observation_chunk, obs_count)

            a = torch.as_tensor(
                states_a[:, start:stop],
                device=self.device,
                dtype=torch.uint8,
            )
            b = torch.as_tensor(
                states_b[:, start:stop],
                device=self.device,
                dtype=torch.uint8,
            )

            y = torch.as_tensor(
                target_bps[start:stop],
                device=self.device,
                dtype=torch.float32,
            )

            y_valid = torch.as_tensor(
                target_valid[start:stop],
                device=self.device,
                dtype=torch.bool,
            )

            valid = (
                y_valid.unsqueeze(0)
                & torch.isfinite(y).unsqueeze(0)
                & (a != 255)
                & (b != 255)
                & (a < resolution)
                & (b < resolution)
            )

            cell = (
                a.to(torch.int64) * resolution
                + b.to(torch.int64)
            )

            global_cell = pair_offset + cell

            idx = global_cell[valid]

            if idx.numel() == 0:
                continue

            expanded_y = y.unsqueeze(0).expand(pair_count, -1)
            weights = expanded_y[valid].to(torch.float64)

            chunk_counts = torch.bincount(
                idx,
                minlength=flat_count_size,
            ).reshape(pair_count, cells)

            chunk_sums = torch.bincount(
                idx,
                weights=weights,
                minlength=flat_count_size,
            ).reshape(pair_count, cells)

            counts += chunk_counts
            sums += chunk_sums

        return counts.cpu().numpy(), sums.cpu().numpy()
```

Important:

- this is a **starting production implementation**, not the final performance
  endpoint;
- benchmark pair-batch size and observation chunk size;
- reuse/preallocate staging buffers later if profiling shows transfers or
  allocations dominate;
- never use `torch.cuda.empty_cache()` inside this loop;
- target batching can be added later, but one target at a time is a valid,
  memory-bounded first implementation;
- preserve the CPU reference scanner permanently.

---

## 128. Surface Summarization

The scanner produces the complete surface. Selection/summarization is a
separate deterministic function.

```python
from __future__ import annotations

import numpy as np


def summarize_surface(
    *,
    counts: np.ndarray,
    sums_bps: np.ndarray,
    min_cell_n: int,
) -> dict:
    if counts.shape != sums_bps.shape:
        raise ValueError("counts/sums shape mismatch")

    means = np.full(counts.shape, np.nan, dtype=np.float64)

    np.divide(
        sums_bps,
        counts,
        out=means,
        where=counts > 0,
    )

    eligible = counts >= min_cell_n

    if not eligible.any():
        return {
            "best_cell": None,
            "worst_cell": None,
            "best_mean_bps": np.nan,
            "worst_mean_bps": np.nan,
            "spread_bps": np.nan,
        }

    score_for_max = np.where(eligible, means, -np.inf)
    score_for_min = np.where(eligible, means, np.inf)

    best_flat = int(np.argmax(score_for_max))
    worst_flat = int(np.argmin(score_for_min))

    best_cell = np.unravel_index(best_flat, means.shape)
    worst_cell = np.unravel_index(worst_flat, means.shape)

    best = float(means[best_cell])
    worst = float(means[worst_cell])

    return {
        "best_cell": best_cell,
        "worst_cell": worst_cell,
        "best_mean_bps": best,
        "worst_mean_bps": worst,
        "spread_bps": best - worst,
    }
```

Do **not** throw away the negative side.

The selected relationship may be long or short.

---

## 129. Concrete Trial Ledger

`discovery/trials.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True, slots=True)
class TrialRecord:
    trial_id: str
    trial_family_id: str
    run_id: str
    trial_type: str
    status: str

    feature_a_id: str | None = None
    feature_b_id: str | None = None
    target_id: str | None = None
    resolution: int | None = None
    variant_definition: str | None = None

    artifact_hash: str | None = None
    reason: str | None = None
    created_at_utc: str = ""


class TrialLedger:
    def __init__(self):
        self._rows: dict[str, TrialRecord] = {}

    def put(self, row: TrialRecord) -> None:
        if not row.created_at_utc:
            row = TrialRecord(
                **{
                    **asdict(row),
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )

        previous = self._rows.get(row.trial_id)

        if previous is not None and previous != row:
            raise ValueError(f"Conflicting trial record: {row.trial_id}")

        self._rows[row.trial_id] = row

    def records(self) -> list[TrialRecord]:
        return list(self._rows.values())

    def write_parquet(self, path: Path) -> None:
        rows = [asdict(x) for x in self.records()]
        table = pa.Table.from_pylist(rows)

        tmp = path.with_suffix(".parquet.partial")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(path)
```

For very large ledgers, write immutable stage shards and compact at bundle time
instead of keeping everything in memory.

---

## 130. Concrete Dual-Scan Execution Loop

A correct initial orchestration loop:

```python
def execute_dual_shard(
    *,
    pair_batch,
    target_id: str,
    target_values,
    target_valid,
    resolutions: tuple[int, ...],
    state_store,
    scanner,
    writer,
    telemetry,
):
    for resolution in resolutions:
        states_a = np.stack(
            [
                state_store.open(pair.feature_a_id, resolution)
                for pair in pair_batch
            ],
            axis=0,
        )

        states_b = np.stack(
            [
                state_store.open(pair.feature_b_id, resolution)
                for pair in pair_batch
            ],
            axis=0,
        )

        counts, sums = scanner.scan_pair_batch(
            states_a=states_a,
            states_b=states_b,
            target_bps=target_values,
            target_valid=target_valid,
            resolution=resolution,
        )

        writer.write_batch(
            pair_batch=pair_batch,
            target_id=target_id,
            resolution=resolution,
            counts=counts,
            sums_bps=sums,
        )

        telemetry.event(
            "dual_batch_complete",
            target_id=target_id,
            resolution=resolution,
            pairs=len(pair_batch),
        )
```

Do not literally use `np.stack` across a batch if profiling shows it causes
large copies. The optimized version should read locality-friendly contiguous
feature tiles or map them into a preallocated staging matrix. The public scanner
boundary can stay the same.

---

## 131. Locality-Aware Pair Tiling

The pair planner should order work to maximize reuse.

Concrete strategy:

1. assign each canonical feature a stable integer index;
2. group features into blocks, e.g. 8–32 features;
3. schedule block pairs `(block_i, block_j)`;
4. load each feature block once per target group/resolution when practical;
5. enumerate all valid unordered pairs within the block-pair;
6. persist one deterministic shard per block-pair × target-group.

Example shard ID:

```python
def shard_id(
    *,
    grid: str,
    block_a: int,
    block_b: int,
    target_block: int,
) -> str:
    return (
        f"dual__{grid}"
        f"__fa{block_a:04d}"
        f"__fb{block_b:04d}"
        f"__tb{target_block:04d}"
    )
```

Sharding must be deterministic so resume can calculate exactly what is missing.

---

## 132. Concrete Candidate Identity

`candidates/identity.py`:

```python
from __future__ import annotations

from quant_pipeline.contracts import CandidateDefinition
from quant_pipeline.hashing import content_hash


def make_candidate(
    *,
    feature_a,
    feature_b,
    target,
    grid: str,
    resolution: int,
    state_payload: dict,
    state_definition: str,
    direction: int,
    source_snapshot_hash: str,
    selection_run_id: str,
    selection_trial_id: str,
) -> CandidateDefinition:
    payload = {
        "feature_a_definition_hash": feature_a.definition_hash,
        "feature_b_definition_hash": (
            feature_b.definition_hash if feature_b is not None else None
        ),
        "target_definition_hash": target.definition_hash,
        "grid": grid,
        "resolution": resolution,
        "state_payload": state_payload,
        "direction": direction,
        "source_snapshot_hash": source_snapshot_hash,
        "return_basis": target.return_basis,
    }

    definition_hash = content_hash(payload)

    return CandidateDefinition(
        candidate_id=f"cand_{definition_hash[:16]}",
        feature_a_id=feature_a.feature_id,
        feature_b_id=(feature_b.feature_id if feature_b else None),
        target_id=target.target_id,
        grid=grid,
        resolution=resolution,
        state_payload=state_payload,
        state_definition=state_definition,
        direction=direction,
        source_snapshot_hash=source_snapshot_hash,
        selection_run_id=selection_run_id,
        selection_trial_id=selection_trial_id,
        return_basis=target.return_basis,
        definition_hash=definition_hash,
    )
```

---

## 133. Concrete Opportunity/Episode Engine

This solves the exact issue that caused confusion around "15 trades/day" versus
repeated active observations.

`forensics/opportunities.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Episode:
    security_id: int
    session_id: int
    start_obs_id: int
    end_obs_id: int
    start_ts_ns: int
    end_ts_ns: int
    observation_count: int


def build_episodes(
    *,
    obs_id: np.ndarray,
    security_id: np.ndarray,
    session_id: np.ndarray,
    security_session_seq: np.ndarray,
    decision_ts_ns: np.ndarray,
    active: np.ndarray,
) -> list[Episode]:
    obs_id = np.asarray(obs_id)
    security_id = np.asarray(security_id)
    session_id = np.asarray(session_id)
    security_session_seq = np.asarray(security_session_seq)
    decision_ts_ns = np.asarray(decision_ts_ns)
    active = np.asarray(active, dtype=bool)

    idx = np.flatnonzero(active)

    if idx.size == 0:
        return []

    # Sort by security, session, timestamp for deterministic grouping.
    order = np.lexsort(
        (
            decision_ts_ns[idx],
            session_id[idx],
            security_id[idx],
        )
    )
    idx = idx[order]

    episodes: list[Episode] = []

    start = idx[0]
    prev = idx[0]
    count = 1

    for current in idx[1:]:
        same_security = security_id[current] == security_id[prev]
        same_session = session_id[current] == session_id[prev]

        continues = (
            same_security
            and same_session
            and security_session_seq[current]
                == security_session_seq[prev] + 1
        )

        if continues:
            prev = current
            count += 1
            continue

        episodes.append(
            Episode(
                security_id=int(security_id[start]),
                session_id=int(session_id[start]),
                start_obs_id=int(obs_id[start]),
                end_obs_id=int(obs_id[prev]),
                start_ts_ns=int(decision_ts_ns[start]),
                end_ts_ns=int(decision_ts_ns[prev]),
                observation_count=count,
            )
        )

        start = current
        prev = current
        count = 1

    episodes.append(
        Episode(
            security_id=int(security_id[start]),
            session_id=int(session_id[start]),
            start_obs_id=int(obs_id[start]),
            end_obs_id=int(obs_id[prev]),
            start_ts_ns=int(decision_ts_ns[start]),
            end_ts_ns=int(decision_ts_ns[prev]),
            observation_count=count,
        )
    )

    return episodes
```

---

## 134. Independent Entry Calculation

For a fixed holding period, use episode starts as fresh signals and then apply
the candidate's re-entry rule.

```python
def independent_entries_fixed_hold(
    *,
    episodes: list[Episode],
    hold_ns: int,
) -> list[Episode]:
    accepted: list[Episode] = []
    next_allowed: dict[tuple[int, int], int] = {}

    for ep in sorted(
        episodes,
        key=lambda x: (x.start_ts_ns, x.security_id),
    ):
        key = (ep.security_id, ep.session_id)

        allowed_at = next_allowed.get(key, -1)

        if ep.start_ts_ns < allowed_at:
            continue

        accepted.append(ep)
        next_allowed[key] = ep.start_ts_ns + hold_ns

    return accepted
```

This prevents repeated re-entry into the same symbol while a prior fixed-hold
position would still be active.

Concurrency across different symbols remains allowed.

---

## 135. Concrete Distribution Statistics

`forensics/distribution.py`:

```python
from __future__ import annotations

import numpy as np


def distribution_stats(returns_bps: np.ndarray) -> dict:
    x = np.asarray(returns_bps, dtype=np.float64)
    x = x[np.isfinite(x)]

    if x.size == 0:
        return {"n": 0}

    winners = x[x > 0]
    losers = x[x < 0]

    return {
        "n": int(x.size),
        "mean_bps": float(np.mean(x)),
        "median_bps": float(np.median(x)),
        "std_bps": float(np.std(x, ddof=1)) if x.size > 1 else np.nan,
        "win_rate": float(np.mean(x > 0)),
        "p01": float(np.quantile(x, 0.01)),
        "p05": float(np.quantile(x, 0.05)),
        "p25": float(np.quantile(x, 0.25)),
        "p75": float(np.quantile(x, 0.75)),
        "p95": float(np.quantile(x, 0.95)),
        "p99": float(np.quantile(x, 0.99)),
        "avg_winner_bps": (
            float(np.mean(winners)) if winners.size else np.nan
        ),
        "avg_loser_bps": (
            float(np.mean(losers)) if losers.size else np.nan
        ),
    }


def contribution_concentration(returns_bps: np.ndarray) -> dict:
    x = np.asarray(returns_bps, dtype=np.float64)
    x = x[np.isfinite(x)]

    if x.size == 0:
        return {}

    total = x.sum()

    ranked = np.sort(x)[::-1]

    def top_fraction(frac: float) -> float:
        n = max(1, int(np.ceil(x.size * frac)))
        if total == 0:
            return np.nan
        return float(ranked[:n].sum() / total)

    return {
        "top_1pct_contribution_share": top_fraction(0.01),
        "top_5pct_contribution_share": top_fraction(0.05),
    }
```

Report both positive and negative concentration when needed; do not hide the
effect of a few extreme losers.

---

## 136. Concrete Chronological Diagnostics

```python
import numpy as np
import pyarrow as pa


def chunk_diagnostics(
    *,
    returns_bps: np.ndarray,
    chunk_id: np.ndarray,
) -> pa.Table:
    rows = []

    for c in np.unique(chunk_id):
        mask = chunk_id == c
        x = returns_bps[mask]
        x = x[np.isfinite(x)]

        rows.append(
            {
                "chunk_id": int(c),
                "n": int(x.size),
                "mean_bps": float(np.mean(x)) if x.size else np.nan,
                "median_bps": float(np.median(x)) if x.size else np.nan,
                "win_rate": float(np.mean(x > 0)) if x.size else np.nan,
            }
        )

    return pa.Table.from_pylist(rows)
```

Label this output `discovery_diagnostic=true`.

It is not OOS merely because a chunk was held out from a local calculation.

---

## 137. Interaction-Lift Decomposition

For a dual candidate, dossier construction should explicitly compare:

```text
unconditional target mean
A-state marginal mean
B-state marginal mean
A∩B candidate-state mean
incremental lift over simple marginal expectation
```

Reference arithmetic:

```python
def interaction_decomposition(
    *,
    target_bps,
    active_a,
    active_b,
) -> dict:
    y = np.asarray(target_bps, dtype=np.float64)
    valid = np.isfinite(y)

    a = np.asarray(active_a, dtype=bool) & valid
    b = np.asarray(active_b, dtype=bool) & valid
    ab = a & b

    unconditional = np.mean(y[valid]) if valid.any() else np.nan
    a_mean = np.mean(y[a]) if a.any() else np.nan
    b_mean = np.mean(y[b]) if b.any() else np.nan
    ab_mean = np.mean(y[ab]) if ab.any() else np.nan

    additive_expectation = a_mean + b_mean - unconditional

    return {
        "unconditional_bps": float(unconditional),
        "a_marginal_bps": float(a_mean),
        "b_marginal_bps": float(b_mean),
        "joint_bps": float(ab_mean),
        "additive_expectation_bps": float(additive_expectation),
        "interaction_lift_bps": float(ab_mean - additive_expectation),
    }
```

This is descriptive. It does not prove causality.

---

## 138. Candidate Dossier Builder — Concrete Control Flow

`forensics/dossier.py`:

```python
class DossierBuilder:
    def __init__(
        self,
        *,
        observation_index,
        feature_store,
        target_store,
        state_store,
        output_root,
    ):
        self.observation_index = observation_index
        self.feature_store = feature_store
        self.target_store = target_store
        self.state_store = state_store
        self.output_root = output_root

    def build(self, candidate: CandidateDefinition) -> Path:
        out = self.output_root / candidate.candidate_id
        out.mkdir(parents=True, exist_ok=True)

        signals = self._materialize_candidate_signal(candidate)
        episodes = self._build_episodes(candidate, signals)
        opportunities = self._independent_entries(candidate, episodes)

        returns = self._candidate_returns(candidate, opportunities)

        summary = {
            "candidate_id": candidate.candidate_id,
            "definition_hash": candidate.definition_hash,
            "return_basis": candidate.return_basis,
            "active_observations": int(signals.sum()),
            "episode_count": len(episodes),
            "independent_opportunity_count": len(opportunities),
            **distribution_stats(returns),
            **contribution_concentration(returns),
        }

        self._write_summary(out, summary)
        self._write_chronology(out, candidate, opportunities, returns)
        self._write_tail_ladder(out, candidate)
        self._write_horizon_ladder(out, candidate)
        self._write_event_path(out, candidate, opportunities)
        self._write_symbol_breakdown(out, candidate, opportunities, returns)
        self._write_interaction(out, candidate)
        self._write_surface_diagnostics(out, candidate)
        self._write_robustness(out, candidate)
        self._write_redundancy_inputs(out, candidate)

        return out
```

Every `_write_*` method should produce a deterministic Parquet/JSON artifact.
The builder should not choose a new "better" state during dossier generation.

---

## 139. Candidate-State Materialization

A candidate state should be represented as structured data, not reparsed from
English wherever possible.

For example:

```json
{
  "kind": "rectangular_cells",
  "resolution": 5,
  "cells": [[4, 4]],
  "direction": 1
}
```

or:

```json
{
  "kind": "cell_set",
  "resolution": 10,
  "cells": [[0, 9], [0, 8], [1, 9]],
  "direction": 1
}
```

The human-readable `state_definition` can be derived from the structured state.

Reference materializer:

```python
def cell_state_mask(
    *,
    state_a: np.ndarray,
    state_b: np.ndarray,
    cells: list[tuple[int, int]],
) -> np.ndarray:
    active = np.zeros(len(state_a), dtype=bool)

    for a_cell, b_cell in cells:
        active |= (state_a == a_cell) & (state_b == b_cell)

    return active
```

This avoids ambiguous string parsing.

`CandidateDefinition` therefore includes a canonical JSON-serializable
`state_payload` field in addition to the human-readable `state_definition`.
Candidate identity hashes the structured payload; the display string is not the
source of truth.

---

## 140. Candidate Materialization Policy

The policy belongs in configuration.

Example:

```yaml
forensics:
  enabled: true
  candidate_policy:
    min_active_n: 250
    min_abs_edge_bps: 1.0
    min_populated_fraction: 0.50
    keep_top_k_per_target_resolution: 250
    allow_specialist_trigger: true
    allow_resolution_structure_trigger: true
```

These are **example defaults only**, not research truth.

The selection code should emit `reason_codes`, such as:

```text
large_active_edge
large_surface_spread
neighbor_plateau
specialist_disagreement
cross_resolution_structure
manual_request
```

Candidate selection is a compute-management step inside discovery, not OOS
evidence.

---

## 141. Concrete Variant Expansion Planner

```python
def plan_variant_expansion(
    *,
    parent_pair,
    reason_codes,
    feature_registry,
    trial_family_id,
):
    a_variants = tuple(
        x.feature_id
        for x in feature_registry.all()
        if x.concept_id == parent_pair.feature_a.concept_id
    )

    b_variants = tuple(
        x.feature_id
        for x in feature_registry.all()
        if x.concept_id == parent_pair.feature_b.concept_id
    )

    return VariantExpansionRequest(
        parent_pair_id=parent_pair.pair_id,
        reason_codes=tuple(reason_codes),
        feature_a_variants=a_variants,
        feature_b_variants=b_variants,
        target_ids=parent_pair.target_ids,
        trial_family_id=trial_family_id,
    )
```

This is how V3 searches windows/representations **after** canonical concepts
show structure without brute-forcing every one of 6,000+ variants against every
other variant.

---

## 142. Specialist Probe — Concrete First Implementation

For a candidate pair/target/resolution:

1. materialize the selected active state;
2. group active returns by `security_id`;
3. calculate local N and local mean;
4. summarize sign agreement/dispersion/concentration.

```python
def specialist_probe(
    *,
    security_id: np.ndarray,
    active: np.ndarray,
    returns_bps: np.ndarray,
    min_local_n: int = 20,
) -> dict:
    sec = np.asarray(security_id)
    active = np.asarray(active, dtype=bool)
    y = np.asarray(returns_bps, dtype=np.float64)

    mask = active & np.isfinite(y)

    rows = []

    for s in np.unique(sec[mask]):
        local = mask & (sec == s)
        n = int(local.sum())

        if n == 0:
            continue

        rows.append(
            {
                "security_id": int(s),
                "n": n,
                "mean_bps": float(y[local].mean()),
            }
        )

    eligible = [r for r in rows if r["n"] >= min_local_n]

    if not eligible:
        return {
            "symbols_active": len(rows),
            "symbols_eligible": 0,
        }

    effects = np.array([r["mean_bps"] for r in eligible])

    contribution = np.array(
        [r["mean_bps"] * r["n"] for r in eligible],
        dtype=np.float64,
    )

    total_abs = np.abs(contribution).sum()

    shares = (
        np.sort(np.abs(contribution))[::-1] / total_abs
        if total_abs > 0
        else np.zeros_like(contribution)
    )

    return {
        "symbols_active": len(rows),
        "symbols_eligible": len(eligible),
        "fraction_positive": float(np.mean(effects > 0)),
        "fraction_negative": float(np.mean(effects < 0)),
        "effect_dispersion_bps": float(np.std(effects, ddof=1))
            if effects.size > 1 else np.nan,
        "top_symbol_share": float(shares[0]) if shares.size else np.nan,
        "top5_symbol_share": float(shares[:5].sum()) if shares.size else np.nan,
        "min_local_active_n": min(r["n"] for r in eligible),
        "median_local_active_n": float(
            np.median([r["n"] for r in eligible])
        ),
        "max_local_active_n": max(r["n"] for r in eligible),
    }
```

For the full exhaustive scan, this probe may need a more vectorized version.
The semantics above are the reference behavior.

---

## 143. Cross-Fitted Discovery Diagnostic

This is deliberately **not** the real OOS test.

Reference algorithm for a candidate family:

```text
for each chronological discovery fold:
    use the other discovery folds to estimate/select the state/surface
    freeze that fold-local state
    evaluate it on the held-out discovery fold
combine held-out discovery-fold outcomes
report degradation vs full-discovery selection
label result discovery_cross_fitted_diagnostic
```

Pseudo-code:

```python
def cross_fitted_discovery_diagnostic(
    *,
    fold_id,
    fit_state_fn,
    evaluate_state_fn,
):
    outputs = []

    for held_out in np.unique(fold_id):
        train = fold_id != held_out
        test = fold_id == held_out

        frozen_state = fit_state_fn(train)

        outputs.append(
            evaluate_state_fn(
                frozen_state=frozen_state,
                mask=test,
            )
        )

    return outputs
```

Never label the combined result `replication` or `oos`.

---

## 144. Statistical Uncertainty for Intraday Candidates

Because minute observations are serially/cross-sectionally dependent, do not
treat every row as IID.

A simple first implementation should aggregate candidate outcomes to a
session-level statistic and estimate uncertainty across sessions.

Example:

```python
def session_clustered_mean_se(
    *,
    returns_bps: np.ndarray,
    session_id: np.ndarray,
) -> dict:
    y = np.asarray(returns_bps, dtype=np.float64)
    sid = np.asarray(session_id)

    valid = np.isfinite(y)

    sessions = []

    for s in np.unique(sid[valid]):
        x = y[valid & (sid == s)]

        if x.size:
            sessions.append(float(np.mean(x)))

    session_means = np.asarray(sessions, dtype=np.float64)

    if session_means.size < 2:
        return {
            "session_n": int(session_means.size),
            "mean_bps": float(np.mean(y[valid])) if valid.any() else np.nan,
            "session_clustered_se": np.nan,
            "t_stat": np.nan,
        }

    mean = float(np.mean(session_means))
    se = float(
        np.std(session_means, ddof=1)
        / np.sqrt(session_means.size)
    )

    return {
        "session_n": int(session_means.size),
        "mean_bps": mean,
        "session_clustered_se": se,
        "t_stat": mean / se if se > 0 else np.nan,
    }
```

For overlapping 240-minute holds, dossier inference should also report episode
and session counts so the effective sample size is not mistaken for raw minute
N.

A more sophisticated clustered/bootstrap estimator may replace this later
without changing the dossier schema.

---

## 145. Concrete Analysis Bundle Builder

`analysis_bundle/builder.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import duckdb


class AnalysisBundleBuilder:
    def __init__(self, bundle_dir: Path):
        self.bundle_dir = bundle_dir
        self.bundle_dir.mkdir(parents=True, exist_ok=True)

    def build_duckdb(self) -> Path:
        db_path = self.bundle_dir / "research.duckdb"

        con = duckdb.connect(str(db_path))

        try:
            self._create_view_if_exists(
                con,
                "single_summary",
                self.bundle_dir / "single_summary.parquet",
            )
            self._create_view_if_exists(
                con,
                "dual_summary",
                self.bundle_dir / "dual_summary.parquet",
            )
            self._create_view_if_exists(
                con,
                "trial_ledger",
                self.bundle_dir / "trial_ledger.parquet",
            )
            self._create_view_if_exists(
                con,
                "specialist_summary",
                self.bundle_dir / "specialist_summary.parquet",
            )
            self._create_view_if_exists(
                con,
                "edge_registry",
                self.bundle_dir / "edge_registry.parquet",
            )
        finally:
            con.close()

        return db_path

    @staticmethod
    def _create_view_if_exists(
        con,
        view_name: str,
        parquet_path: Path,
    ) -> None:
        if not parquet_path.exists():
            return

        path_sql = str(parquet_path).replace("'", "''")

        con.execute(
            f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT * FROM read_parquet('{path_sql}')
            """
        )

    def write_manifest(self, payload: dict) -> Path:
        path = self.bundle_dir / "bundle_manifest.json"

        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

        return path
```

For dossier glob views, use paths relative to the bundle and test on Windows.

---

## 146. Concrete SIP Export

`execution_data/sip_export.py`:

```python
from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def write_sip_signal_export(
    *,
    candidate,
    rows: list[dict],
    output_path: Path,
) -> Path:
    required = {
        "candidate_id",
        "security_id",
        "symbol",
        "signal_ts_utc",
        "direction",
        "reference_exit_ts_utc",
        "state_definition",
        "resolution",
    }

    for row in rows:
        missing = required - row.keys()

        if missing:
            raise ValueError(f"SIP export row missing {sorted(missing)}")

        if row["candidate_id"] != candidate.candidate_id:
            raise ValueError("Mixed candidate IDs in SIP export")

    table = pa.Table.from_pylist(rows)

    tmp = output_path.with_suffix(".parquet.partial")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(output_path)

    return output_path
```

No fill prices, spread assumptions, P&L, or recommendations belong here.

---

## 147. Concrete DAG Runner

`orchestration/runner.py`:

```python
from __future__ import annotations

from collections import deque


class DagRunner:
    def __init__(self, *, stages: dict, dependencies: dict):
        self.stages = stages
        self.dependencies = dependencies

    def ordered_stages(self, requested: tuple[str, ...] | None = None) -> list[str]:
        wanted = set(requested or self.stages.keys())

        # Pull in transitive dependencies.
        changed = True
        while changed:
            changed = False
            for stage in tuple(wanted):
                for dep in self.dependencies.get(stage, ()):
                    if dep not in wanted:
                        wanted.add(dep)
                        changed = True

        indegree = {name: 0 for name in wanted}
        children = {name: [] for name in wanted}

        for name in wanted:
            for dep in self.dependencies.get(name, ()):
                if dep not in wanted:
                    continue

                indegree[name] += 1
                children[dep].append(name)

        queue = deque(sorted(k for k, v in indegree.items() if v == 0))
        order = []

        while queue:
            node = queue.popleft()
            order.append(node)

            for child in sorted(children[node]):
                indegree[child] -= 1

                if indegree[child] == 0:
                    queue.append(child)

        if len(order) != len(wanted):
            raise RuntimeError("Pipeline stage graph contains a cycle")

        return order

    def run(self, ctx, requested: tuple[str, ...] | None = None):
        results = []

        for name in self.ordered_stages(requested):
            stage = self.stages[name]

            ctx.telemetry.event("stage_start", stage=name)

            result = stage.run(ctx)

            ctx.telemetry.event(
                "stage_complete",
                stage=name,
                metrics=dict(result.metrics),
            )

            results.append(result)

        return results
```

Each stage itself decides whether its expected artifacts are already valid and
can be reused.

---

## 148. Concrete Resume Logic

The simplest reliable resume model is **artifact-derived resume**.

```python
def should_execute(
    *,
    store,
    expected_outputs: tuple[ArtifactKey, ...],
) -> bool:
    for key in expected_outputs:
        if not store.has_complete(key):
            return True

        store.validate_file(key)

    return False
```

For sharded stages:

```python
for shard in planned_shards:
    outputs = shard.expected_outputs(ctx)

    if should_execute(
        store=ctx.artifacts,
        expected_outputs=outputs,
    ):
        execute(shard)
    else:
        trial_ledger.mark_reused(shard)
```

Do not depend on a single mutable `checkpoint.pkl`.

---

## 149. Concrete Resource Preflight

```python
from __future__ import annotations

import shutil

import psutil
import torch


def preflight_resources(machine) -> dict:
    vm = psutil.virtual_memory()

    available_ram_gb = vm.available / (1024 ** 3)

    if available_ram_gb < machine.resource_budget.reserve_ram_gb:
        raise RuntimeError(
            f"Only {available_ram_gb:.1f} GB RAM available before run"
        )

    free_disk = shutil.disk_usage(machine.scratch_root).free / (1024 ** 3)

    gpu = {
        "available": torch.cuda.is_available(),
        "free_vram_gb": None,
        "total_vram_gb": None,
    }

    if torch.cuda.is_available():
        free_b, total_b = torch.cuda.mem_get_info()
        gpu["free_vram_gb"] = free_b / (1024 ** 3)
        gpu["total_vram_gb"] = total_b / (1024 ** 3)

    return {
        "available_ram_gb": available_ram_gb,
        "scratch_free_gb": free_disk,
        **gpu,
    }
```

Before a full run, estimate expected scratch/cache growth from the registered
feature/target counts and refuse to start if the reserve would obviously be
violated.

---

## 150. Concrete Windows Worker Bootstrap

At process startup:

```python
import os


def configure_worker_threads(
    *,
    blas_threads: int,
    omp_threads: int,
) -> None:
    os.environ["OMP_NUM_THREADS"] = str(omp_threads)
    os.environ["MKL_NUM_THREADS"] = str(blas_threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(blas_threads)
    os.environ["NUMEXPR_NUM_THREADS"] = str(blas_threads)
```

Call before heavy numerical libraries initialize inside spawned workers.

Work item:

```python
@dataclass(frozen=True, slots=True)
class FeatureWorkItem:
    feature_id: str
    observation_index_path: str
    input_paths: tuple[str, ...]
    output_content_hash: str
```

The work item stays tiny; workers open files themselves.

---

## 151. Concrete CLI

`__main__.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from quant_pipeline.config import (
    load_machine_config,
    load_research_config,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant_pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--machine", type=Path, required=True)

    resume = sub.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--machine", type=Path, required=True)

    status = sub.add_parser("status")
    status.add_argument("--run-id", required=True)
    status.add_argument("--machine", type=Path, required=True)

    replicate = sub.add_parser("replicate")
    replicate.add_argument("--candidate-id", required=True)
    replicate.add_argument("--machine", type=Path, required=True)

    sip = sub.add_parser("export-sip")
    sip.add_argument("--candidate-id", required=True)
    sip.add_argument("--machine", type=Path, required=True)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "run":
        research = load_research_config(args.request)
        machine = load_machine_config(args.machine)
        return run_pipeline(research=research, machine=machine)

    if args.command == "resume":
        machine = load_machine_config(args.machine)
        return resume_run(run_id=args.run_id, machine=machine)

    if args.command == "status":
        machine = load_machine_config(args.machine)
        return print_status(run_id=args.run_id, machine=machine)

    if args.command == "replicate":
        machine = load_machine_config(args.machine)
        return replicate_candidate(
            candidate_id=args.candidate_id,
            machine=machine,
        )

    if args.command == "export-sip":
        machine = load_machine_config(args.machine)
        return export_sip(
            candidate_id=args.candidate_id,
            machine=machine,
        )

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
```

The functions referenced here are thin application-service wrappers around the
same DAG/artifact system, not alternate pipeline implementations.

---

## 152. Stage Implementation Pattern

Every stage should look roughly like this:

```python
class ObservationIndexStage:
    name = "observation_index"

    def planned_outputs(self, ctx):
        key = observation_index_artifact_key(ctx)
        return (key,)

    def run(self, ctx):
        key = self.planned_outputs(ctx)[0]

        if ctx.artifacts.has_complete(key):
            path = ctx.artifacts.validate_file(key)

            return StageResult(
                stage_name=self.name,
                output_keys=(key,),
                metrics={"cache_hit": True},
            )

        source_rows = load_authorized_decision_rows(ctx)
        table = build_observation_index(source_rows)

        partial = ctx.artifacts.begin_file(key, ".parquet")

        import pyarrow.parquet as pq
        pq.write_table(table, partial, compression="zstd")

        final = ctx.artifacts.commit_file(
            key=key,
            partial_path=partial,
            suffix=".parquet",
            manifest_payload={
                "row_count": table.num_rows,
                "definition_hash": key.content_hash,
                "implementation_hash": ctx.implementation_hash,
            },
        )

        return StageResult(
            stage_name=self.name,
            output_keys=(key,),
            metrics={
                "cache_hit": False,
                "rows": table.num_rows,
                "path": str(final),
            },
        )
```

Use this pattern consistently rather than inventing ad hoc cache/resume logic in
every stage.

---

## 153. Exact First V3 Build Strategy

Sol should **not** attempt to build the whole 6,000-line design in one giant
unreviewed change.

The implementation sequence should be:

```text
commit 1
package + config + contracts + hashing + errors

commit 2
artifact store + telemetry + canonical CLI + DAG

commit 3
sealed-data governance + observation index + data provider interface

commit 4
feature/target registries + one toy feature/target + cache

commit 5
CPU surface scanner + tests

commit 6
Torch scanner + CPU/GPU parity

commit 7
pair planner + singles + dual shard runner + trial ledger

commit 8
candidate identity + opportunity engine + minimal dossier

commit 9
analysis bundle + DuckDB + SIP export

commit 10+
port V2 real feature/target/data semantics, then optimize
```

Every commit should leave the test suite green.

---

## 154. What “Port V2” Technically Means

For each V2 subsystem being preserved:

1. identify the authoritative V2 function/module;
2. write a small deterministic fixture around current V2 behavior;
3. port the logic into the V3 contract;
4. run V2 and V3 on the same fixture;
5. compare exact or tolerance-bounded outputs;
6. only then delete/rewrite temporary compatibility code.

Required parity categories:

```text
security identity
PIT universe membership
research-price/corporate-action behavior
decision timestamps
feature availability
feature values
target values
target validity
bin/tie behavior
sealed-period access behavior
```

Do not "clean up" semantics before parity proves what changed.

---

## 155. First End-to-End Smoke Fixture

Create a deterministic fixture with approximately:

```text
5 symbols
10 sessions
1-minute bars
3 canonical features
1 non-canonical variant per concept
3 targets
r3/r5/r10
one intentionally weak single
one intentionally strong interaction-only dual
one negative/short interaction
one repeated-state episode
```

The fixture should guarantee:

```text
weak singles still produce their dual
positive and negative surfaces both survive
r5 can win while r10 fails
episode counting differs from raw active-row counting
sealed replication rows are rejected
resume reuses completed dual shards
```

This fixture is the most important early test because it directly prevents the
V2 mistakes V3 is being designed to remove.

---

## 156. Concrete Performance Evolution

Do not start by writing custom CUDA.

### Correctness baseline

```text
NumPy CPU reference
Torch GPU one-pair reference
memmapped feature states
deterministic shards
```

### First production optimization

```text
pair batching
observation chunking
locality-aware feature block order
reuse GPU allocations
one coordinated writer
bounded host staging
```

### Only if profiling still justifies it

```text
multiple CUDA streams
pinned double buffers
target batching
torch.compile / CUDA graph where static and useful
Triton/custom CUDA
```

For each optimization, record:

```text
before wall clock
after wall clock
peak RAM
peak VRAM
pair-targets/sec
CPU/GPU parity result
```

Higher GPU utilization alone is not a win.

---

## 157. Expected Full-Run Memory Model

For planning on the current machine:

```text
32 GB physical RAM
- ~6 GB OS/safety reserve
= ~26 GB maximum research working envelope
```

Do not try to hold all 44.7M observations × hundreds of features in RAM.

Expected pattern:

```text
disk/memmap canonical states
    ↓
small feature tile mapped/read
    ↓
bounded host staging
    ↓
~10 GB GPU working set ceiling
    ↓
small result arrays written/compacted
```

DuckDB-heavy stages should use the majority of available RAM only when Python
worker pools are not simultaneously consuming it.

---

## 158. Expected Full-Run Disk Model

The V2 float32 feature cache was roughly hundreds of GiB. V3 should avoid
replicating that as the discovery hot plane.

Use:

```text
raw/forensic feature cache
    only for reusable values actually required later

compact canonical-state cache
    exhaustive discovery hot plane

target arrays
    reusable float32 + validity

surface results
    compact counts/sums/cell summaries

analysis bundle
    compacted Parquet + DuckDB
```

Cache cleanup must be lineage-aware, never "delete everything older than N
days".

---

## 159. Required Logs During a Real Full Run

At minimum, the user should be able to open `STATUS.json` and see:

```text
current stage
current shard
expected shards
completed shards
elapsed
estimated throughput (not fake ETA)
cache hit rate
RAM
VRAM
GPU utilization if available
disk free
last completed artifact
last error
heartbeat
```

For the dual scanner also expose:

```text
pair_targets_per_sec
resolution_tests_per_sec
pairs completed
targets completed
```

Do not multiply fused r3/r5/r10 by three and call that
`pair_targets_per_sec`.

---

## 160. Concrete Acceptance Commands

Phase 1:

```bash
python -m pytest tests/unit -q
python -m quant_pipeline --help
```

Smoke run:

```bash
python -m quant_pipeline run \
  --request configs/research/smoke.yaml \
  --machine configs/machines/local.yaml
```

Resume test:

```bash
python -m quant_pipeline resume \
  --run-id <smoke_run_id> \
  --machine configs/machines/local.yaml
```

Full discovery only after smoke/parity:

```bash
python -m quant_pipeline run \
  --request configs/research/v3_discovery.yaml \
  --machine configs/machines/local.yaml
```

Expected bundle assertions:

```text
replication_accessed == false
final_holdout_accessed == false
all expected canonical dual trials reconciled
r3/r5/r10 present
negative effects present
trial ledger complete
edge registry generated
research.duckdb opens
```

---

## 161. What Is Still Intentionally Not “Implemented” in This Markdown

The following should be implemented by Sol **inside the real repository after
opening V2**, not invented here:

### V2 market-data adapter

Because this spec does not contain the actual V2 source schemas/provider code.

### PIT universe engine

Because correctness depends on the exact V2 identity and membership semantics.

### Corporate-action/research-price engine

Because changing this from memory would be dangerous.

### Every feature formula

Because V3 should port/test the actual definitions and then add new feature
packs.

### Every target formula

Same reason.

### Exact bin/tie implementation

This must match V2/reference semantics before the compact representation is
optimized.

### Final GPU kernel

The correct shape depends on profiling actual state/target storage and the RTX
3080 Ti.

This is not a gap in the design. It is the boundary between **safe
pre-specification** and **code that must be written/tested against the actual
repository**.

Everything else above is meant to be sufficiently concrete that Sol can start
building immediately rather than designing from scratch.

---


# PART IV — SINGLE-FILE OPERATING INSTRUCTIONS FOR SOL/CODEX

This Markdown file is the **single authoritative V3 planning/specification
document**.

There should not be a separate requirements document, architecture document,
or implementation-guide document once this file is placed into the V3 repo.

Recommended repository filename:

```text
V3_MASTER_SPEC.md
```

## First instruction to Sol

Use:

```text
Read V3_MASTER_SPEC.md completely before making architectural changes.

It is the single source of truth for Quant-Pipeline V3.

Implement only the requested build phase. Preserve all completed contracts and
tests. If an implementation detail is unspecified, choose the simplest
single-machine solution consistent with this file and prove it with tests or
benchmarks.

Do not redesign unrelated components.

At the end of the phase, return only the engineering report format specified in
the master spec.
```

## Conflict rule

Within this file, priority is:

```text
non-negotiable causality / sealed-data invariants
    >
explicit research requirements
    >
public implementation contracts
    >
recommended architecture
    >
performance suggestions
```

If Sol discovers a genuine contradiction:

1. do not silently choose one side;
2. preserve the higher-priority requirement;
3. make the smallest necessary implementation deviation;
4. document it;
5. add a regression test preventing accidental reversal.

## Final project philosophy

V3 is not supposed to be an enterprise quant platform.

It is a powerful, reliable research machine for one workstation.

The intended loop is:

```text
GPT proposes economically distinct feature ideas
    ↓
V3 computes them reproducibly
    ↓
V3 searches canonical interactions broadly
    ↓
V3 expands interesting families selectively
    ↓
V3 characterizes serious edges deeply
    ↓
GPT analyzes standardized evidence
    ↓
selected frozen candidates move to SIP / sealed replication
    ↓
new hypotheses are generated
```

Once V3 is stable, **feature/concept research becomes the primary recurring
work**, not rebuilding the pipeline.

---

# FINAL REVIEW STATUS

This consolidated file was assembled from the reviewed V3 requirements and the
reviewed technical implementation specification, then extended with concrete
code-level contracts.

Before the full V3 build, this should be treated as the last planning artifact.
Further architectural ideas should normally be implemented/tested directly
rather than spawning additional planning documents.

The specification deliberately does **not** prewrite every feature kernel or
GPU kernel. Those are implementation details whose correct shape depends on
parity tests and profiling on the actual RTX 3080 Ti / i9-11900KF / 32 GB
Windows workstation.

The public contracts, validation semantics, data schemas, sealed-data rules,
build phases, and acceptance criteria are intended to be stable enough for Sol
to begin implementation.
