# V3 canonical discovery completion

Run `v3_discovery` completed successfully on 2026-09-19 UTC. This document is a compact publication-safe completion record; the licensed source data, caches, scratch files, and multi-gigabyte evidence artifacts remain local and are intentionally excluded from Git.

## Governed scope

- Discovery period: 2025-05-01 through 2026-04-30
- Canonical dual scope: exhaustive structurally compatible pairs
- Resolutions: r3, r5, and r10
- Optional zoom stage: disabled
- Replication accessed: false
- Final holdout accessed: false
- Source manifest: `a028fb0826cff88ad18b233e0c2aaef3124dfc415504caf700ae9dc3f1a23727`

## Verified evidence

| Evidence family | Verified rows/work units |
| --- | ---: |
| Canonical singles reused | 11,280 |
| Canonical singles unavailable | 2,820 |
| Canonical dual r3 | 1,008,890 |
| Canonical dual r5 | 1,008,890 |
| Canonical dual r10 | 1,008,890 |
| Cell specialist surfaces | 3,026,670 |
| Cell temporal surfaces | 3,026,670 |
| Trial-ledger rows | 3,037,956 |
| Structurally excluded dual work units | 93,662,250 |
| Unavailable dual work units | 278,680 |
| Failed work units | 0 |

The three durable surface tables reconcile exactly at 3,026,670 rows each: resolution evidence, specialist evidence, and temporal evidence. Each resolution contains exactly 1,008,890 pair-target surfaces.

## Completion checks

- `STATUS.json` reports `stage: complete`.
- `EVIDENCE_COMPLETE.json` reports `status: complete`.
- `bundle_manifest.json` reports `evidence_complete: true`.
- The bundle declares r3, r5, and r10 coverage.
- The trial ledger contains no failed work.
- Required Parquet artifacts are readable.
- The DuckDB analysis bundle is readable and exposes the expected evidence and coverage interfaces.
- `replication_accessed` and `final_holdout_accessed` are both false in the completion evidence and bundle manifest.

## Local analysis interface

The primary local follow-up interface is:

```text
D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_discovery\analysis_bundle\research.duckdb
```

Use it read-only for subsequent interpretation. Because `zoom.enabled` was false, zero candidates and dossiers is expected; the completed run is the exhaustive canonical evidence base from which later governed analysis or zoom work can be requested.
