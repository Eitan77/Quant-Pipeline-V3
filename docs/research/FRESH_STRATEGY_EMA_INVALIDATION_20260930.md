# Original top-ten discovery result invalidated

The requested May 2026 replication was stopped before reading May prices. Its candidate was authorized and frozen, but the feature reconstruction check exposed a discovery input error. This is an input-validity failure, not a May performance result.

`FeatureBuilder` sorted each security's rows by timestamp while preserving the original Parquet row index. The EMA computation then discarded that index with `reset_index(level=0, drop=True)`. Pandas aligned the EMA denominators to other rows. The stored signal was consequently not the stated close/20-day-EMA signal, and some denominators used future prices.

Discovery-only audit:

- 125,082 emitted daily observations; 88,033 incorrect EMA quintile bins and 104,469 incorrect EMA decile bins relative to the stated formula.
- The older-momentum feature reproduces exactly at both resolutions, isolating this issue to the EMA input.
- 125,050 stored EMA-distance values match an EMA from another date within relative error 1e-6; 28,679 matches are future-dated.
- Of the original 856 filled +1bp/top-ten trades, **385 match only a future-date EMA**. An additional exact float32 audit found zero matching causal dates for those 385 trades. For example, CAH and BG on 2025-05-07 use the EMA from 2026-04-30.
- The original 64.35% discovery return, timing alternatives, and concentrated-slot results therefore cannot support strategy selection or an unchanged forward replication.

The implementation now uses grouped `transform` and preserves the EMA row index. A regression test with shuffled security/date rows and appended future-price spikes failed before the fix and passes afterward.

The stated mathematical rule was recalculated on the same full discovery year, with the same lag, PIT membership, calendar exclusions, rank, ten slots, reference prices, and zero fees. This is a **bar-assumed diagnostic**, not quote-validated performance: 1,470 assumed trades yield +18.21%, +14.79%, +11.46%, +8.23%, +5.10%, +2.05%, and -0.91% funded returns at -1/0/1/2/3/4/5bp per side respectively. It assumes every entry and exit limit fills at the reference offset; historical quote replay is required before treating any of these numbers as executable. No filtering, price optimization, or replacement strategy was introduced.

The original artifacts and freeze remain intact for audit. This invalidation supersedes their strategy-validity claims. May price/quote outcomes and later holdouts remain untouched. The corrected discovery candidate needs quote revalidation before spending the holdout on it.

Evidence: `D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_oos_top10_may2026_20260930/DISCOVERY_ALIGNMENT_FAILURE.json`, `discovery_ema_alignment_audit.parquet`, `discovery_filled_alignment_audit.parquet`, `corrected_discovery_bar_diagnostic.json`, and `corrected_discovery/`.

Reproduce: `.venv/Scripts/python.exe tools/competition_may_replication.py audit`; `corrected_bars`; `.venv/Scripts/python.exe -m pytest tests/unit/test_ema_alignment.py -q`.
