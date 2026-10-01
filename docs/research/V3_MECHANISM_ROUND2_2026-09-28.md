# Mechanism round 2 — 2026-09-28

**Verdict: none promoted.** All three market-entry/market-exit samples lost money. Best limit combinations produced only 4, 6, and 5 positive sampled months; each turns negative excluding its best three trades. Do not spend on full quote coverage or add fitted filters to these candidates. 214/216 sample trades had usable quotes; no quote/bar entry-price identity discrepancy exceeded 2%. These samples reject promotion, not establish population expected returns. Next distinct experiment should construct a direct stock-versus-market lag/dislocation signal rather than select another return-feature corner.

Screened 18 previously unreplayed pairs across market response/relative strength, price-volume dislocations, and volume confirmation, with r10 and broader r5 cells (36 rules). Used existing global neighbor, residual-return, and benchmark-adjusted sign screens. No new time/ticker filters. Replayed 1/5/10 positions, 25/50/100% capital, and -1,0,1,2,3,4,5 bps per side. All results are discovery only.

## Quote results

Three candidates passed initial two-half, concentration and monthly screens. Six seeded random eligible trades/month/candidate, seed 20260928; fixed neutral five-slot schedules. Each tested with the complete 64 buy/sell market-or-limit combinations. Entry cancellation after 60 seconds; exit market fallback after 60 seconds, capped five minutes before close. Positive buy offset bids below midpoint; positive sell offset offers above midpoint. Returns use quote prices without hypothetical fee/rebate overlays. Strict executable-side move-through is a passive fill proxy, not established queue/size fillability. Sample results are not annualized.

| Rule | Quote coverage | Market bps/attempt | Best buy/sell offsets | Best bps/attempt | Fills | Positive sampled months | Remove best 3 trades |
|---|---:|---:|---|---:|---:|---:|---:|
| 11 | 71/72 | -5.092 | 1/1 | 2.145 | 20 | 6/12 | -0.143 |
| 31 | 72/72 | -2.843 | -1/5 | 0.026 | 31 | 5/12 | -2.379 |
| 5 | 71/72 | -0.821 | 5/-1 | 4.387 | 13 | 4/12 | -1.557 |

Best grid cells are selected discovery maxima, not proven execution policies. Reject concentrated or negative outcomes rather than tune around them. Frozen sampled schedules do not model opportunities freed by canceled orders or conflicts introduced by extended exits; full event-driven replay is required before portfolio claims.

## Definitions and bar diagnostics

- Rule 5: benchmark_excess_return__30m__raw__intraday_5m × prior_high_reclaim_strength__30m__raw__intraday_5m, r10 cell 97, direction 1, hold 30m. Bar zero-cost 16.87%, daily drawdown 2.57%, 8.38 trades/day, 9/12 months. These are bar diagnostics, not quote returns.
- Rule 11: breakout_distance__30m__raw__intraday_5m × price_shock_minus_volume_shock__30m__raw__intraday_5m, r10 cell 70, direction 1, hold 30m. Bar zero-cost 8.31%, daily drawdown 1.37%, 4.16 trades/day, 10/12 months. These are bar diagnostics, not quote returns.
- Rule 31: prior_high_reclaim_strength__30m__raw__intraday_5m × return_x_rvol__30m__raw__intraday_5m, r5 cell 19, direction 1, hold 30m. Bar zero-cost 10.16%, daily drawdown 2.42%, 9.85 trades/day, 10/12 months. These are bar diagnostics, not quote returns.

All three remain bar-profitable excluding the best three tickers and five days. Both halves are positive for these definitions; rule 31 narrower r10 neighbor fails the second half, so its stability is weaker. No sector-specific feature was introduced and these tests do not establish a causal market lead mechanism. Feature definitions inspected use trailing/current inputs; this is not a fresh full prefix-recomputation audit.

Artifacts: `D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923\research\intraday_strategy_20260928` under `mechanism_round2`, `round2_quote_sample`, and `round2_both_legs`. Complete cost grids, trade ledgers, 64-cell quote grids, monthly quote summaries, and identity flags saved. May 2026 onward untouched.
