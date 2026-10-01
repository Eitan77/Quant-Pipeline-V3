# Frozen-state timing comparisons, 2026-09-30

Conclusion: retain close entry and following-close exit. Overnight-only is weak and concentrated; intraday-only variants lose after limit attainability. Green opening conditions do not rescue intraday trades or improve carry performance.

Same May 2025-April 2026 discovery year, prior-session state and fine-bin rank, ten cash-funded positions, zero fees, all prescribed offsets [-1,0,1,2,3,4,5] per side. These are additional discovery hypotheses, with no OOS accessed or frozen strategy changed.

At +1 bp per side, full-year quote replay:

| Timing / condition | Cash-funded return | Completed fills | Positive months | Minute-close drawdown |
| --- | --- | --- | --- | --- |
| Current: close to next close | +64.35% | 856 | 12/12 | 3.48% |
| Close to following open | +7.56% | 979 | 7/12 | 7.87% |
| First open to same close | -8.51% | 619 | 5/12 | 9.89% |
| First open to following close | +20.48% | 494 | 7/12 | 6.32% |
| Following open to same close | -5.11% | 613 | 3/12 | 8.99% |
| Gap-green first open to same close | -9.81% | 424 | 4/12 | 11.41% |
| Green-first-minute open to same close | -2.60% | 420 | 6/12 | 7.86% |
| Gap-green first open to following close | +6.31% | 369 | 6/12 | 7.49% |
| Green-first-minute open to following close | +18.86% | 366 | 8/12 | 6.05% |

Clock example, Monday signal: current buys Tuesday near close and sells Wednesday near close. First-open variants buy Tuesday at 09:31; following-open variants buy Wednesday at 09:31. Opening reference is the latest completed minute, available by 09:31, never an opening-bar value read before completion. Orders activate at entry +5 seconds and exit +1 second. Scheduled close means official close minus one minute, including early closes. Holding stays strictly below 48 hours; weekend/holiday crossings remain excluded as in the frozen candidate.

Green gap means Tuesday's completed first-minute close is above Monday's completed regular-session close. Green first minute means Tuesday's completed first-minute close is above Tuesday's first-minute opening price. Both are known before 09:31:05. No fitted green thresholds or combined filters were searched.

Common starting pool: 1,974 frozen calendar/priced intentions. Gap green retains 1,075; green first minute 952. Buying at the following open has six missing causal entry references, so 1,968 intentions remain. Missing references are known abstentions, not future-outcome filters. A missing opening exit reference uses the known prior closing entry reference, with exact prescribed offsets; an existing holding is never dropped. Quote router uses touched bars and missing-bar coverage exceptions. Positive sizes, noncrossed markets and a pre-window as-of NBBO with maximum age two seconds govern attainability.

Entry misses remain zero-return attempts and consume the window. Allocation precedes fills. Sell limits cancel at second 54, assume acknowledgement at 55, and force from 56, capped at the limit conservatively. Opening liquidation can wait for the first valid quote within 180 seconds of the planned minute; all reported ten-slot ranked liabilities are priced. One MPWR overnight exit remains unresolved in nonselected controls at nonnegative offsets; those controls are not reported as completed portfolios. Closing exits stay before market close.

Paired check removes the changed stock-selection/slot effect: all original 856 +1bp filled entries have identical attainable entry prices in the overnight replay and fully priced morning exits. Using the original actual capital budgets, their morning-exit profit is 9.60% of initial capital, versus 64.35% through the next close. This is fixed-budget timing attribution, not a separately reallocated morning-exit portfolio. On 854/856 names with opening reference coverage, gross reference-price moves average 30.83bp overnight and 31.60bp during the following session. Those reference paths are not executable profits; morning quote fills and liquidation materially weaken the overnight result.

Stage A and all seven exact quote offsets are saved in stage_a_comparison.parquet and comparison.parquet. All same-day opening variants lose at zero and +1bp; their zero-fee bar assumptions were positive, demonstrating why quote replay matters. Close-to-next-open is +7.99% at zero, +7.56% at +1 and -3.17% at +5, with ex-top-five mean return negative even at zero/+1. Current close-to-next-close stays +60.06%, +64.35%, +56.84% at those offsets. Green filters reduce sample without providing a superior policy.

Limits: historical quote attainability is not live order-fill proof. Notional/depth, market impact and actual cancellation acknowledgements remain unvalidated. Drawdown uses minute-close marks. Later OOS remains sealed. Keep the frozen policy unchanged for the next test.

Reproduce: tools/competition_timing_variants.py prepare (or build from cached source references), screen, replay --variant NAME, report. Exact attempts, fills, outcomes, funded equity/months and source reference provenance are under the timing_variants_20260930 folder. The original FROZEN_STRATEGY.json is unchanged.
