# Research handoff implementation status (2026-09-22)

The attached 19-task handoff is **not complete**. The full comprehensive request is blocked before core execution. Existing discovery runs remain legacy evidence; none was relabeled as comprehensive.

| Tasks | Status | Evidence / remaining work |
|---|---|---|
| 1 | Implemented | Baseline `675e38d` inspected; nine reference modules and focused reference tests added. |
| 2 | Implemented for explicit core scope | Exact feature/target selectors reach feature construction, target ledger/alignment, dual scope, and audit. Governed discovery subranges validate. A full production-path selected-scope fixture remains to be run. |
| 3-4 | Partial | Stage-specific checkpoint IDs, packed-bin observation/definition lineage, and stage-namespaced specialist/temporal partials added. Fused tile resume and OOM parent/child reconciliation still need replacement. |
| 5 | Partial | Production and worker use one machine numerical lock. Shared memory admission across all feature/zoom/query entrypoints remains. |
| 6-8 | Partial | Verified array importer, group dictionaries, exact logical task planner, and bounded task executor work in a small integration fixture. Full-scale streaming plan and condition predicates remain. |
| 9-10 | Blocked | Existing specialist/temporal passes still duplicate subgroup work. Streaming reducer, eviction, recomputation, and query pins are needed for the configured full scope. |
| 11-12 | Partial | Local describe/query/search and durable queue/CLI work for committed materialized evidence. Full-scope recomputation, journal, and real neighbor/backtest handlers remain. |
| 13-15 | Pending | Batched zoom integration, independent full diagnostics, and replay adapter remain. These are explicitly unavailable in the new service. |
| 16 | Partial | Opportunity overlap calculation and bounded legacy target/rank caches improved; measured production optimizations remain. |
| 17 | Partial | Comprehensive and legacy completion meanings are separate. README/manual still need a complete workflow revision after handlers are integrated. |
| 18-19 | Blocked | Small publication→coverage→query→search fixture passes. Full production-path, CUDA parity, interruption, streaming, and execution-aware replay gates have not passed. The full request is **not ready to run**. |

## Actual workstation preflight

`configs/research/v3_comprehensive_20260922.yaml` resolves to the discovery year only. The local source catalog exists and CUDA reports an RTX 3080 Ti. The output drive had 213.7 GiB free. The pre-core estimate for **security grouping alone** is 2,721,032,244,000 dense bytes, versus an 86,040,176,640-byte conservative output budget. Alias exclusions and compression are not yet measured. `D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260922/evidence/preflight_storage.json` records the estimate. No core/production workload was launched for this request.

The full request stops with `blocked_storage` until a streaming reducer, eviction and recomputation path is integrated and verified. Do not interpret the reference-module tests or the small publication fixture as full-run readiness.

## Focused checks

`python -m pytest tests/unit/test_research_evidence_reference.py tests/integration/test_research_publication.py tests/unit/test_explicit_zoom.py tests/unit/test_production_repair.py tests/unit/test_cell_evidence.py -q` — 37 passed after the compatibility fix.
