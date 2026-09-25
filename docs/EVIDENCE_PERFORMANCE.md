# Evidence acceleration validation

Measured on 2026-09-25 using the RTX 3080 Ti (12 GiB), Torch 2.5.1/CUDA 12.1,
and discovery-only run `v3_comprehensive_20260923`.

| Measurement | Previous path | Fused resident path |
| --- | ---: | ---: |
| Live durable task throughput | 4.05 tasks/s | 31.68 tasks/s |
| Tasks committed in the sample | 123 in 30.35 s | 1,599 in 50.48 s |
| Identical 123-task group | 25.379 s | 4.037 s |

The short live samples showed **7.82x** higher throughput; the identical-group
benchmark showed **6.29x**. Adjacent live groups differ, so neither establishes
a fixed whole-run speedup. The benchmark scanned 9,109,116 observations on the
intraday grid. Staging inputs once took 22.8 seconds and is excluded from its
steady-state timing. Its summaries matched, with FP64 tolerance for means.

The implementation removes repeated CUDA masking/temporary tensors, keeps verified
inputs resident when memory permits, and reuses a joint packed-bin histogram across
resolutions when the entire grid's alphabet and actual state size admit it.
Coverage and task identities are unchanged. The ordinary Torch path remains the
default; see the README for enabling the optional CUDA backend.

Validation: **18 focused tests passed** using:

```powershell
.\.venv\Scripts\python -m pytest tests/unit/test_segmented_cuda.py tests/unit/test_research_evidence_reference.py tests/integration/test_research_publication.py -q
```

Tests cover exact counts, FP64 moments, resolution projection, arbitrary packed
alphabets, nonfinite targets, missing bins, excluded/empty groups, partial resolution
batches, cancellation, admission, and publication/resume. GPU tests require the
optional CUDA dependencies and a CUDA device.
