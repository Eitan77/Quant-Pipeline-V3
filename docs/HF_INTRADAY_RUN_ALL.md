# HF intraday run-all pack

Status: the original scan was stopped after zero-coverage defects were
diagnosed. Active targeted run: `hf_intraday_run_all_20261001_targetedfix`.
The full rebuild (`hf_intraday_run_all_20261001_coveragefix`) is stopped.
Targeted repair retains 97 feature values, 95 feature bins and 19 targets from
all 251 completed days. It recomputes only 20 PCA/peer feature values, their
bins, two recovery bins and 12 PCA targets. The 81 completed warmup sessions
are reused. Scanning is blocked until every requested column has finite coverage.

This is a feature/target/pair contract in the existing V3 `run`, `resume`, and
`status` entry points. The scan executor uses the existing production
`FusedSegmentedBatch`, `ResourcePolicy`, and `AdaptiveFeatureConcurrency`.
There is one runtime scan path; the former scanner exists only as a test oracle. It reuses V3's read-only source bridge, PIT universe,
split-consistent research prices, owned run folders, and numerical-owner lock.
It does not change the existing canonical run or include execution modeling.

The exact source is preserved in `HF_INTRADAY_SOURCE.md` and its SHA-256 is
recorded in `hf_intraday/spec.json`. All 117 singles, 305 numbered pairs, and
31 targets are retained. Reversed/redundant listed pairs are retained as distinct
requests; no unlisted pairs are generated.

## Run and resume

Read-only configuration/coverage check:

```powershell
.\.venv\Scripts\python.exe -m quant_pipeline hf-preflight --request configs\research\hf_intraday_run_all.yaml --machine configs\machines\hf_local.yaml
```

Start only if no run artifacts already exist:

```powershell
.\.venv\Scripts\python.exe -m quant_pipeline run --request configs\research\hf_intraday_run_all.yaml --machine configs\machines\hf_local.yaml
```

Run ID: `hf_intraday_run_all_20260930`. Discovery remains 2025-05-01 through
2026-04-30. Replication and final holdout remain sealed. Build warmup starts
2024-04-01, allowing sequential model, TOD, and feature-bin baseline formation.
No warmup observations enter the discovery results.

## Fixed choices for underspecified definitions

- SPY is the benchmark. Beta is prior-20-session OLS with an intercept
  (covariance/variance); no beta clipping. At least 1,000 finite training rows.
  Daily model eligibility is determined from PIT membership and prior-session
  price/liquidity data, including eligible names without current-day bars.
  Today's bar presence does not choose the training universe.
- PCA uses prior-20-session pairwise centered return covariance, five leading eigenvectors,
  and current-day eligible names with sufficient prior observations. Fitting
  requires at least 1,000 observed prior rows per covariance pair. Poorly overlapping
  names are removed deterministically using prior missingness only. Returns are
  never imputed; pairwise covariance uses each pair's own observed means. Peer
  correlations likewise use jointly observed residual rows. Contemporaneous factor scores use
  least squares on the observed subset of the frozen loadings; no future
  loadings, filling missing returns, or overnight labels.
- Peer sets contain up to 10 other names, selected by absolute correlation of
  prior residuals under the frozen PCA model. Basket weights are proportional
  to absolute correlations and sum to one. Lead models use ridge regression,
  no intercept, standardized predictors, penalty `0.001 * training_rows`.
  The 1-minute prediction uses peers at t; the 2-minute prediction uses
  peers at t and t-1. Responses and lags never cross sessions.
- Network incoming/outgoing strengths sum absolute 1-minute lead coefficients.
  Leader contributions use predictor-specific coefficients. Peer dispersion
  is the weighted population standard deviation. Invalid predictions remain NA.
  Peer selection excludes nonfinite correlations and normalizes valid weights
  exactly. Names outside the fitted model retain NA network strength.
- Factor common-share cap is 10. Epsilon is `1e-12`; return standard deviations
  use sample ddof=1. Cross-sectional ranks and empirical percentiles use tie
  midranks. TOD needs 60 finite prior-session values at the identical minute.
- Single and ordinary dual surfaces use independent 3/5/10 equal-percentile
  bins of each feature against its prior60 same-clock history. Feature values
  are never overwritten by binning. Conditional recovery features retain NA off
  events; after a full 60-session same-clock window, bins use the finite prior
  events (minimum one). Their number of events may be small, so rank granularity
  varies. The 60-finite-observation requirement remains for TOD feature formulas.
- The six requested tail variables use their empirical prior60 same-clock
  percentiles. All six thresholds are run in both directions. A listed pair
  receives a dual tail surface when its listed first leg is a tail variable;
  its second leg receives both 5- and 10-bin resolutions. Pair orientation is
  preserved. There are 6,210 surfaces and 2,467,228 aggregate cell/target rows,
  including empty cells.
- Recent5/prior30 ratios use disjoint windows: t-4..t versus t-34..t-5.
  Session range expansion divides the current high-low range by the prior60
  same-clock median high-low range. The 5/30 range ratio sums bar high-minus-low
  widths; the prior-20-session liquidity statistic pools actual minute dollar
  volumes before taking the median. Opening range uses the actual first five clock minutes and is
  available at the 09:35 completed-minute decision.
- Session open is the first bar's **open**. Prior close is the previous
  exchange-calendar session-end close, not an earlier stale stock print.
  Calendar open/close bounds exclude after-hours bars on early-close days;
  a missing scheduled closing stock print leaves prior close unavailable.
  Missing bars occupy their exact clock slot. Invalid rolling windows stay NA;
  session accumulations are conservatively unavailable after a missing bar.
- Dollar activity uses raw VWAP × raw volume, reconstructed as research VWAP ×
  split factor × raw volume. Returns and price locations use research prices.
  Session VWAP uses research VWAP and actual volume.
- Peer HHI normalizes absolute contributions by their positive total; an
  all-zero or unavailable contribution vector has no defined HHI and stays NA.
- VWAP and breakout ages count elapsed clock minutes and reset each session.
  Tail-event age excludes the current event and caps at 30; shock clustering
  includes prior minutes 1..15. Recovery uses the most recent prior shock.
  An unknown event minute makes capped age/recovery unavailable until a newer
  known shock restores the state or the unknown minute leaves the age window.
- The source's `wit1`..`wit30` target text is interpreted as “with the same
  daily-frozen PCA loadings.” Raw p1 intentionally duplicates raw forward1.

Empirical tails at 0.1%, 0.25%, 0.5%, and 1% can coincide with only 60 same-clock
historical values, especially with ties. They are all persisted; this is not
evidence of distinct threshold robustness.

## Evidence and resumability

The two registries are ordinary Parquet files. The five required result outputs
(`single_results.parquet`, `dual_results.parquet`, `tail_results.parquet`,
`candidate_summary.parquet`, `candidate_event_paths.parquet`) are **partitioned
Parquet directories**, one atomic file per surface. Read with `name/*.parquet`.
This retains complete evidence without one giant in-memory result table.

Each surface/target/cell preserves all/month/symbol groupings, observation count,
contiguous eligible episode count, symbol count, mean/median bps, positive-return
win rate, sample dispersion, descriptive observation SE and t-stat, return basis,
direction, bin/tail definition, and state indices. Positive/negative mean direction
is descriptive. SE is not claimed to correct dependence from overlapping labels.

Candidate summaries preserve every aggregate cell, including empty/NA cells.
Event-path output preserves 1/2/3/5/10-minute means and distribution statistics
for raw, beta, and PCA bases. Each horizon reports its own finite-label count.
No sample/effect gates discard strange cells.

Feature values, finite-coverage diagnostics, daily model coverage, PCA/beta arrays,
peer choices/coefficients, and prior-session training dates are also persisted.
Production fused CUDA FP64 moments reconcile against exact DuckDB counts, means,
and dispersion; DuckDB supplies the pack-required medians and grouped episodes.
Shared resource admission bounds concurrency.
CUDA is selected when available. Reads and scan state are bounded. The full run's
throughput/storage requirements are not measured by the synthetic build checks.

Resume checks implementation/request/source identity and verifies
`build_complete.json` against every completed session, required column, row count,
and artifact signature. Complete builds skip all warmup/model/feature calculation.
Partial builds retain causal replay. Committed surfaces and prepared inputs are reused. Missing companion outputs regenerate
before task completion. Completion requires all 6,210 committed surfaces and
the exact aggregate cell-target count, then writes `EVIDENCE_COMPLETE.json`.

After discovery, cost sensitivity at -1/0/1/2/3/4/5 bps and quote replay remain
separate research steps. These bar-close targets do not assert achievable fills.

Production launch uses `hf_local.yaml` (6 GB DuckDB cap). The 60-session float64 history is disk-backed under the owned run cache; eviction and cleanup preserve exact feature/rank parity.

Ticker alias repair (2026-10-01): training/history axes use unique stable security IDs; saved rows retain each observed bar ticker. The same run resumed after an audited identity transition before any HF numerical output existed, reusing unchanged prep panels.

Execution cleanup (2026-10-01) preserves all 251 built sessions, 45,404,726
observations and 97 committed surfaces through the recorded identity transition
in `execution_cleanup_audit.json`. Feature/model/formula files and the request
are unchanged. Empty evidence remains explicit: 22 feature columns and 12 PCA
target columns had zero finite observations in the completed build.

The original run is retained as evidence and a validated column source; never
resume it.

Coverage repair (2026-10-01): sampled real prior20 data restored 489 PCA models,
443 one-minute peer models and 387 two-minute peer models out of 503 eligible
names on 2025-05-01. Former globally complete-case fitting produced zero.
Recovery feature values existed (460,739 and 1,164,713 observations), but their
event-conditioned bins were empty under the former daily-event requirement.
The new run retains all 117 features, 31 targets and 305 exact pairs; old outputs
are preserved separately. `coverage_repair_audit.json` records reused source and
panel identity and focused validation.

The full corrected rebuild is stopped in favor of targeted repair. Its last
60 completed warmup history maps seed the targeted run; the preceding 20 raw
return/market/liquidity sessions restore the model state. Selected columns are
copied into the new owned history cache without modifying the seed maps.
Unchanged observation keys, feature values, bins and raw/beta targets are copied
from the validated original files; beta fits must reconcile before publication.
For already committed surfaces with unchanged feature bins, 19 raw/beta target
rows are reused and only 12 PCA targets are scanned. Other surfaces use the
same shared production scanner with all targets. No formulas, settings, requested
features or pairs are added. `targeted_repair_audit.json` records provenance.

```powershell
.\.venv\Scripts\python -m quant_pipeline resume --run-id hf_intraday_run_all_20261001_targetedfix --machine configs\machines\hf_local.yaml
```

Execution batching repair (2026-10-01) preserves all completed builds, prepared
inputs and 169 committed surfaces through `execution_batching_upgrade_audit.json`.
It uses the existing production fused kernel with a one-pair tile for small
batches, admits a partial FP64 target cache when all 31 targets do not fit VRAM,
and double-buffers pinned host transfers without synchronizing each chunk.
CPU target batches use the actual selected row count. Two shared episode-window
lags encode per-target start masks without changing missing-label semantics.
The shared scaler readmits sparse tails separately from dense surfaces with
different query-memory budgets and the same host reserve.

Nine focused CPU/CUDA/reference tests passed, including full, partial and absent
GPU caches. Two real full-discovery surface comparisons matched committed
evidence: 65.71 to 56.31 seconds and 16.68 to 13.80 seconds, excluding 31.40 seconds
of reusable target staging. These are component measurements, not a whole-run
ETA. Exact medians and episodes remain CPU work; GPU residency does not imply
continuous GPU compute saturation.
