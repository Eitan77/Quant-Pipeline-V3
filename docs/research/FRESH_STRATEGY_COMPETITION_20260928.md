# Fresh strategy competition research record

Date: 2026-09-28  
Run: `v3_comprehensive_20260923`  
Scope: discovery only (2025-05-01 through 2026-04-30); replication and final holdout were not accessed.

## Verdict

The best strategy found in this fresh pass is an **overnight long**:

- Pair `e669d83e43b3cea8b148779a`
- `trend_slope__20d__raw__preclose_1555` x `window_max_drawdown__20d__raw__preclose_1555`
- Target `target_overnight__raw__preclose_1555`
- State: r10 cells `[80, 90]` (top two trend-slope deciles, lowest max-drawdown decile)
- Enter at the governed pre-close reference; exit at the governed next-session reference.

This is a coherent r10 subregion of r5 cell 20. Its two cells return 49.5 and 53.8 bps; the broader equivalent r10 region `[80,81,90,91]` exactly reconstructs r5 cell 20 (N=1,726, 37.86 bps).

## Leader evidence

- Active N / independent opportunities: 751 / 751
- Frequency: 0.67% of valid pair-target observations (subset of the 1.55% r5 region)
- Sessions: 217; 3.46 opportunities/session
- Simultaneous signals: median 3, p90 6.4, maximum 15
- Active edge: 52.43 bps; median trade 38.53 bps; win rate 58.6%
- Broader r5 interaction lift: +26.09 bps
- Months: 11/12 positive; August 2025 was negative
- Equal-weight active-day result: +1.113 additive at 0 bp, max additive drawdown -0.106; +0.895 at +5 bp/side, max drawdown -0.122
- Random finite-slot checks remained positive. At +5 bp/side, 500 random trials produced additive active-day results:
  - 1 slot: mean +0.890, p05 +0.595, p95 +1.184
  - 3 slots: mean +0.897, p05 +0.805, p95 +0.995
  - 5 slots: mean +0.895, p05 +0.860, p95 +0.926

### BPS sensitivity

| BPS/side | Trades | Mean bps | Median bps | Win rate | Additive trade return |
|---:|---:|---:|---:|---:|---:|
| -1 | 751 | 54.45 | 40.54 | 59.5% | 4.089 |
| 0 | 751 | 52.43 | 38.53 | 58.6% | 3.938 |
| 1 | 751 | 50.42 | 36.52 | 58.2% | 3.787 |
| 2 | 751 | 48.41 | 34.52 | 57.7% | 3.636 |
| 3 | 751 | 46.41 | 32.51 | 57.3% | 3.485 |
| 4 | 751 | 44.40 | 30.50 | 56.6% | 3.334 |
| 5 | 751 | 42.39 | 28.50 | 55.8% | 3.183 |

### Exact SIP quote replay

Quotes were downloaded only for the 751 strategy trades. Each entry and exit limit was active for a fixed 60-second window beginning at its governed timestamp. All 1,502 leg windows have SIP quote coverage; ticker-history aliases `FB -> META` and `CDAY -> DAY` were reconciled by stable security ID. No bars were substituted for quotes.

| BPS/side | Entry fills | Exit attempts | Exit fills / completed | Both-side rate | Mean completed bps | Completed additive return |
|---:|---:|---:|---:|---:|---:|---:|
| -1 | 533 | 533 | 389 | 51.8% | 57.15 | 2.223 |
| 0 | 618 | 618 | 472 | 62.8% | 56.43 | 2.663 |
| 1 | 651 | 651 | 509 | 67.8% | 51.81 | 2.637 |
| 2 | 690 | 690 | 545 | 72.6% | 51.86 | 2.827 |
| 3 | 714 | 714 | 573 | 76.3% | 49.82 | 2.855 |
| 4 | 725 | 725 | 586 | 78.0% | 49.03 | 2.873 |
| 5 | 734 | 734 | 602 | 80.2% | 45.97 | 2.767 |

The assumed execution prices are historically attainable often enough to support the execution premise.

### Full-position quote accounting

Every filled entry was subsequently closed. A missed 60-second exit limit is sold at the final valid SIP bid inside that same exit window; an unfilled entry remains cash. Capital is allocated equally across that session's attempted entries.

| BPS/side | Filled entries | Limit exits | Forced exits | Mean filled-trade bps | Additive portfolio return | Compounded return | Max drawdown | Positive months |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -1 | 533 | 389 | 144 | 35.85 | 52.35% | 63.87% | -9.17% | 9/12 |
| 0 | 618 | 472 | 146 | 35.67 | 60.18% | 76.54% | -12.53% | 10/12 |
| 1 | 651 | 509 | 142 | 33.79 | 61.30% | 78.44% | -12.42% | 10/12 |
| 2 | 690 | 545 | 145 | 33.67 | 63.55% | 82.10% | -13.15% | 10/12 |
| 3 | 714 | 573 | 141 | 32.46 | 63.76% | 82.38% | -13.16% | 10/12 |
| 4 | 725 | 586 | 139 | 32.24 | 63.41% | 81.55% | -13.58% | 10/12 |
| 5 | 734 | 602 | 132 | 30.59 | 60.12% | 75.66% | -14.00% | 10/12 |

At +5 bp/side, the 132 forced exits averaged -39.54 bps and reduced the result materially. The early half returned +18.44% additive; the later half returned +41.68%. This is now complete position accounting under the declared 60-second policy, but it remains discovery-only and does not model quote depth, borrow availability, or taxes.

### Conditional morning exit discovery

A fixed 24-rule bar screen tested two causal momentum gates, three trailing stops, three take-profits, and 10:00/10:30 hard exits. The strongest plateau required the first five morning minutes to be positive and above the executed entry, then used a 100 bp trailing stop; otherwise it exited after the gate. The 10:00 and 10:30 variants were similar, while fixed take-profits were materially worse.

For the selected 10:30 variant, one-minute bars identified only the candidate exit minute and SIP quotes priced the actual exit. All 734 filled positions had quote coverage across 438 distinct event windows, with zero download errors. Results were 46.86 bps per filled trade, +86.23% additive, +125.20% compounded, -13.50% max drawdown, and 9/12 positive months. Exit counts were 457 gate exits, 245 quote-confirmed trailing stops, and 32 hard exits. The later half averaged 68.07 bps per filled trade. This improves the original +60.12% additive result by 26.12 percentage points, but it is an in-sample discovery-selected exit rule, not an independent validation.

### Counterevidence

- Symbol concentration is material: WDC, SNDK, STX, SMCI, and TER contribute 57.9% of aggregate trade return.
- Excluding those five leaves 552 trades over 199 sessions, 30.02 bps/trade, and 9/12 positive months. The effect survives, but is weaker.
- Benchmark-adjusted return for the broader identical r5 state is +25.98 bps versus +37.86 raw, so the effect is partly market-driven but not only market drift.
- The state is selected on discovery data. It is not authorized for replication, final holdout, or promotion.
- Quote replay uses a declared 60-second order lifetime. Other lifetimes were not searched or optimized.

### Overnight alternative screen

Twenty-five distinct r10 mechanisms were replayed with +5 bp/side Stage-A execution, chronological halves, monthly consistency, concentration, ex-top-five results, and 100 randomized five-slot selections.

- No alternative beat the current trend-slope/drawdown strategy on clean profitability or monthly consistency. It remains 10/12 positive months and +89.50% theoretical additive return before quote replay.
- The highest-frequency broad alternative, beta plus prior-low-reclaim, produced 9,864 trades across 218 sessions but only +25.57% additive return, 7/12 positive months, and 11.88 bps/trade.
- ATR plus downside-beta produced 4,577 trades across 249 sessions, +30.28% additive return, 8/12 positive months, and 17.50 bps/trade.
- Opening-gap plus upside-vol-acceleration produced 1,923 clean trades across 245 sessions, +24.03% additive return, 9/12 positive months, -8.85% max drawdown, and only 0.18 daily correlation with the current strategy. It is a possible diversifier, not a superior standalone strategy.
- Several apparent +75% to +232% challengers were driven by one AMCR raw-price discontinuity from $8.825 to $44.56 overnight. Removing only that greater-than-100% discontinuity reduced the best of them to roughly +30%; they were not sent to quote replay.
- A theoretical 50/50 blend of the current strategy and the clean opening-gap alternative returned +56.77% additive with -6.24% max drawdown and 10/12 positive months. It improves smoothness but sacrifices substantial return and remains unquoted.

## Main challenger: broad intraday short

- Pair `49ba1886c98f4effe309482b`
- `market_beta__30m__raw__intraday_5m` x `positive_jump_fraction__30m__raw__intraday_5m`
- Target `target_240m__raw__intraday_5m`
- State: r5 cell 23, exactly equal to r10 union `[86,87,96,97]`
- Surface: -23.04 bps active return, -11.77 bps interaction lift, N=10,416, frequency 0.478%
- Cross-section: 139 eligible symbols; 82% negative; top-5 contribution share 13%
- Temporal: all folds negative; 9/12 profitable short months
- Opportunities: 3,967 across 122 sessions (32.5/session); simultaneous median 5, p90 23, maximum 72
- Return basis: -12.24 bps benchmark-adjusted and -6.40 bps beta-residual in the same cell; the raw edge contains a market component but retains stock-specific direction.
- Horizon: approximately flat through 60m, -3.41 bps at 120m, -23.04 bps at 240m. This is delayed, not immediate alpha.

| BPS/side | Mean bps | Median bps | Win rate |
|---:|---:|---:|---:|
| -1 | 22.55 | 14.68 | 56.2% |
| 0 | 20.55 | 12.67 | 55.3% |
| 1 | 18.55 | 10.67 | 54.6% |
| 2 | 16.54 | 8.67 | 53.6% |
| 3 | 14.54 | 6.67 | 52.8% |
| 4 | 12.54 | 4.67 | 52.0% |
| 5 | 10.53 | 2.67 | 51.2% |

The tempting r10 subregion `[86,96]` produced 64.2 bps/trade, but only on 13 sessions with massive same-time clustering. It is rejected as a shock-cluster artifact.

## Intraday continuation: selectable high-frequency candidate

The broad short mechanism was refined without opening replication or final holdout. The candidate is:

- SHORT at the first 5-minute crossing of at least 6 of 8 predeclared r5 pair states; hold 240 minutes.
- The common prerequisite is `positive_jump_fraction__30m` bin 3. The paired bins are market beta 4, upside beta 4, market-lead response 0, vol-of-vol 4, recovery-in-downtrend 1, roll-spread proxy 4, market correlation 4, and negative-return-sum-absolute 4.
- Suppress same-symbol overlap. Allow at most 10 simultaneous positions. Rank conflicts by confirmation count, then the frozen pair-edge score.

This produces 661 attempted trades on 113 active sessions out of 251 governed sessions: 5.85 attempts per active session and 2.63 per calendar session. There are 173 symbols and the five most frequent account for 11.2% of attempts.

The unallocated threshold event set has a 240-minute short edge of 47.99 bps raw, 29.11 bps benchmark-adjusted, and 16.17 bps beta-residual. Its raw path is 17.91 bps at 30m, 15.19 at 60m, 39.70 at 120m, 47.99 at 240m, and 46.30 at EOD, so 240m is a real delayed peak rather than an immediate reaction.

### Finite-slot BPS sensitivity

| BPS/side | Trades | Mean bps | Median bps | Win rate | Additive trade return | Positive months |
|---:|---:|---:|---:|---:|---:|---:|
| -1 | 661 | 28.01 | 21.63 | 56.7% | 1.852 | 10/12 |
| 0 | 661 | 26.01 | 19.63 | 56.1% | 1.719 | 9/12 |
| 1 | 661 | 24.00 | 17.62 | 55.2% | 1.587 | 9/12 |
| 2 | 661 | 22.00 | 15.62 | 54.6% | 1.454 | 9/12 |
| 3 | 661 | 19.99 | 13.62 | 54.5% | 1.322 | 9/12 |
| 4 | 661 | 17.99 | 11.61 | 54.2% | 1.189 | 9/12 |
| 5 | 661 | 15.99 | 9.61 | 53.6% | 1.057 | 9/12 |

The later chronological half remains positive at +5 bp/side: 427 trades, 10.26 bps/trade, versus 26.43 bps in the earlier half. Twenty randomized equal-score tie selections at +5 bp/side stayed between 13.61 and 16.12 bps/trade and had at least 9/12 positive months. This reduces, but does not remove, discovery-selection risk.

### Exact 60-second SIP quote replay

Only the 661 frozen trades were downloaded. All entry and exit windows had quote coverage and there were zero download errors. No bar touches or fallback prices were used.

| BPS/side | Entry fills | Exit attempts | Completed | Both-side rate | Mean completed bps | Completed additive return |
|---:|---:|---:|---:|---:|---:|---:|
| -1 | 344 | 344 | 210 | 31.8% | 29.86 | 0.627 |
| 0 | 444 | 444 | 316 | 47.8% | 19.71 | 0.623 |
| 1 | 464 | 464 | 340 | 51.4% | 15.73 | 0.535 |
| 2 | 491 | 491 | 396 | 59.9% | 16.23 | 0.643 |
| 3 | 525 | 525 | 456 | 69.0% | 16.70 | 0.762 |
| 4 | 543 | 543 | 495 | 74.9% | 17.87 | 0.885 |
| 5 | 560 | 560 | 527 | 79.7% | 15.97 | 0.842 |

At +5 bp/side this is 2.10 completed trades per governed calendar session. The later half has 333 completed trades at 10.33 bps/trade. Quote replay reports completed-limit performance exactly as requested; 33 entry-filled positions did not obtain the +5 bp exit limit inside 60 seconds and require a separately frozen exit fallback before deployment.

Verdict: this is the current intraday leader and is materially more useful than a rare jackpot trade. It remains a discovery candidate, not a promoted strategy, because the pair cells and confirmation threshold were selected on the same discovery year.

## Informative failures

- Broad intraday long `6bf8967f0709f3d05b861133`, r5 region `[20,21]`: 64,630 independent opportunities, but only 5.49 bps at 0 bp/side; turns negative at +3 bp/side. Rejected on execution sensitivity.
- Daily long `9bb3d43524171f3de28b77fa`, 63d target, r5 cell 4: large descriptive return, but only 409 non-overlapping opportunities, very long capital lockup, incomplete late-window signal calendar, and extreme winner concentration. Not preferred to the overnight state.
- Exact r10 spikes without session breadth were treated as failures even when their average return was high.

## Next tests

1. Add a predeclared concentration guard (top-five semiconductor/storage names) and compare the full and ex-top-five variants without optimizing a new threshold.
2. If authorized, freeze the leader definition and run governed replication. Do not inspect replication before the definition hash and authorization are recorded.
3. Before governed replication, freeze an exit policy for entry-filled orders whose 60-second exit limit is not attained; do not silently discard those live positions.
