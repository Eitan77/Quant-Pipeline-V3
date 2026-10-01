# V3 intraday and overnight: first research pass

Run: `v3_comprehensive_20260923` (`D:\AlgoResearch\Quant-Pipeline-V3\runs`). Evidence ID: `743cef95216bf960c67ebbf38a760a4b9c27fe5458bef32519c2a4c8c83c60e7`.

The discovery window is 2025-05-01 through 2026-04-30. `EVIDENCE_COMPLETE.json` reports 469,311/469,311 mandatory tasks complete; replication and final holdout access are both false. This run has no `analysis_bundle/research.duckdb`, so the first pass queries the canonical Parquet summaries in place. No sealed data or execution replay was used.

## Intraday lead: EMA distance / distance from low

Pair `6bf8967f0709f3d05b861133`, 30-minute features on the 5-minute grid, targeting 240 minutes. The selected corner region is directionally coherent across r3/r5/r10:

| Resolution | Cell | N | Frequency | Raw bps | Benchmark-adjusted bps | Adjusted interaction bps | Positive symbols | Positive folds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| r3 | 6 | 352,263 | 11.9% | 5.99 | 3.72 | 0.92 | 67.8% of 516 | 4/5 |
| r5 | 20 | 145,472 | 4.9% | 8.34 | 5.77 | 1.90 | 68.0% of 453 | 5/5 |
| r10 | 90 | 47,151 | 1.6% | 12.32 | 9.36 | 4.08 | 65.9% of 261 | 5/5 |

The top five symbols contribute 7.4%, 9.7%, and 15.2% of the adjusted selected-cell contribution at r3/r5/r10. The r3 adjusted 3×3 surface is `[0.13, -0.77, -2.80; 1.22, -0.31, -1.83; 3.72, 0.28, -1.64]` bps. This is a corner effect, not a broad plateau (`plateau_area=1` at each resolution). The raw 60-minute and 120-minute target effects are smaller and less stable. The family appears in many closely related EMA / price-location pairs, so these are correlated variants, not independent confirmations.

**Next test:** exact time-bucket, month, and security×time decomposition for the r3 parent region; then non-overlapping governed exits and explicit entry delay/cost replay. Check whether the 240-minute effect survives excluding the open and a few high-volatility dates. Do not infer independent opportunity count from the large overlapping observation N.

## Overnight lead: downside beta / momentum acceleration

Pair `a4df35c8f33c8835a7d9e0f7`, 20-day preclose features, target overnight. At r3 cell 8: N=14,142, frequency=12.7%, raw +17.10 bps, benchmark-adjusted +10.32 bps, adjusted interaction +2.97 bps. Of 282 eligible symbols, 63.5% are positive; 4/5 folds are positive; the top five symbols contribute 9.6%. Related downside-beta / momentum-deceleration and trend variants show the same coarse-grid neighborhood.

The r3 adjusted surface rises into the high/high corner (`[-7.99, -7.55, -7.84; -5.42, -4.48, -3.57; 1.21, 0.82, 10.32]` bps). However, the selected r5 cell has only 33 eligible symbols, its top five contribute 42.6%, and only 2/5 folds are positive. The selected r10 cell has N=1,102 and no eligible-symbol breadth under the summary's eligibility rule. The coarse region needs exact region aggregation before claiming resolution agreement.

**Next test:** query the full high/high parent region at r5/r10 rather than those resolutions' independently selected winners, and decompose by month and security. Then replay the precisely frozen long rule through the governed overnight entry/exit path with costs and slippage.

## Ruled out as a direct trade lead

The overnight `min_subreturn` / `positive_jump_fraction` pair (`df91ffb944441cde6c1b7484`) has r3 benchmark-adjusted −13.64 bps, N=16,220, and all five folds negative. Its raw overnight mean is only −0.30 bps, while the selected r5/r10 cells each have just 42 observations. That is relative underperformance, not established profitable short P&L.

## Interpretation

All figures are discovery-period descriptive target returns. The selected cells came from a large correlated search and their reported N includes overlapping horizons. The r3 patterns are leads for governed subgroup and execution tests, not validated strategies or profit forecasts. This selection risk is consistent with the multiple-testing problem documented by [Harvey, Liu, and Zhu](https://www.nber.org/papers/w20592).
