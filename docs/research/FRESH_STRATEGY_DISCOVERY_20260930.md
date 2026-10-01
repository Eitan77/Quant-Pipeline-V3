# Fresh strategy discovery, 2026-09-30

Frozen discovery candidate: prior-close low EMA-distance / high older-momentum state, enter next close and exit the following close. Two features, one rank, no extra alpha filters. Working offset +1 bp per side, zero fees, ten cash-funded positions. The entire May 2025–April 2026 year is discovery; later OOS remains sealed.

Working result: **64.35% return; 856 fills; 3.48% minute-close drawdown; 12/12 positive months; 40/53 positive weeks; maximum hold 24.015 hours.** 185 names, 175 filled entry sessions, 1038 attempts, 1974 eligible calendar/priced intentions. Win rate 57.59%. Correlated stock trades are not independent trials.

## Rules and execution

State is A bottom quintile AND B top quintile of contemporaneous cross-sectional ranks, using the original prior-session daily decision. A=close/EMA20-1; B=close[-5]/close[-63]-1. Prefer stronger B/lower A using B_decile-A_decile; outcome-independent stable hash ties. These bins are per decision, with no future distribution fitting.

Buy at session close minus one minute +5 seconds; sell next ordinary adjacent-day session at close minus one minute +1 second. Use the latest completed source close at each planned minute, no later than that time. BUY=reference*(1+bps/10000), SELL=reference*(1-bps/10000). Valid fresh ask<=BUY and bid>=SELL establish quote attainability. Select new entries at +4 seconds using only freed cash/slots. Buy expires at +59; sell cancels at +54, assumed acknowledged +55, force liquidation from +56 before close. Forced bid is capped at sell limit conservatively. Known early closes and calendar crossings are handled explicitly; no hold reaches 48 hours. No leverage, no same-security overlap, no fill-conditioned replacement of missed orders.

Stage A uses exactly the closing reference prices replayed in Stage B:

| bps | trades | mean_trade_bps | cash_funded_return_pct |
| --- | --- | --- | --- |
| -1 | 1169 | 50.552 | 78.404 |
| 0 | 1169 | 48.542 | 74.281 |
| 1 | 1169 | 46.532 | 70.253 |
| 2 | 1169 | 44.523 | 66.318 |
| 3 | 1169 | 42.514 | 62.475 |
| 4 | 1169 | 40.506 | 58.720 |
| 5 | 1169 | 38.498 | 55.052 |

Stage B retains missed attempts and forced exits; all closing liabilities are priced. Per-side offsets are limit levels, not fees:

| bps | attempts | fills | mean_fill_bps | cash_funded_return_pct | minute_mark_relative_drawdown_pct | green_months | forced_exits | entry_attainment_pct | sell_limit_attainment_pct | both_limits_attainment_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| -1 | 958 | 640 | 62.805 | 48.458 | 3.378 | 11 | 191 | 66.806 | 70.156 | 46.868 |
| 0 | 997 | 778 | 61.350 | 60.061 | 3.471 | 12 | 148 | 78.034 | 80.977 | 63.190 |
| 1 | 1038 | 856 | 58.934 | 64.346 | 3.483 | 12 | 112 | 82.466 | 86.916 | 71.676 |
| 2 | 1089 | 962 | 51.892 | 63.219 | 4.676 | 11 | 67 | 88.338 | 93.035 | 82.185 |
| 3 | 1122 | 1050 | 45.258 | 59.281 | 5.640 | 11 | 40 | 93.583 | 96.190 | 90.018 |
| 4 | 1138 | 1093 | 41.734 | 56.214 | 6.065 | 11 | 25 | 96.046 | 97.713 | 93.849 |
| 5 | 1152 | 1124 | 40.955 | 56.836 | 6.198 | 11 | 13 | 97.569 | 98.843 | 96.441 |

## Evidence and controls

Canonical unit: a2cfbdd1248d9ad6c2d1d20a, target_2d__raw__daily_close, r5 cell 4. Active mean 77.611 bp, N=2,269, frequency 2.075%, interaction lift 45.616 bp, weighted contribution 1.610 bp. Parent A 23.331 bp, parent B 18.628 bp. Lift is active-parentA-parentB+overall. Five chronological fold means positive, weakest component fold 40.517 bp. These descriptive targets precede the calendar/funding/quote policy and are not executed returns.

r3 broader corner N=6,192, mean 44.859 bp. Equivalent four r10 children all positive: cells 8/9/18/19 have approximately 94.9/100.9/48.0/58.9 bp; stronger lower-EMA gradient, not one isolated spike. Full surfaces and all distinct evidence lenses are saved alongside this record. Nearby EMA/return definitions were scanned in the full canonical map; not every definition received annual quote validation.

The source feature-only state has 2,455 observations, 2,448 discovery entry dates, six unavailable causal opening references, and 2,442 initially priceable intentions. Closing-calendar selection retains 1974. Corporate actions were audited without conditioning selection on them. PIT membership passed. Source dividends are ignored, no split accounting exception occurred.

Slower control: both legs activate after five seconds and select new entries before any same-minute sale can free cash/slots. +1bp gives **50.30%**, 690 fills, 5.46% drawdown, 10/12 green months. All seven levels remain positive in this control. Uniform hash selection at +1bp also retains approximately 62.5% return and 12 green months; the economic state does not depend on finely optimized ranking. Three slots increases concentration and return, but reduces annual sample and monthly consistency; ten slots is the high-sample primary candidate.

Top five names contribute 41.62% of funded profit. Remaining names average 38.54 bp/trade; 63.24% of traded names are profitable. Removing the best month leaves 48.58% of initial capital in marked profit; removing five best marked days leaves 39.82%. These are contributions of the existing wallet, not independent reallocated backtests.

Matched SPY same-window reference comparison gives about 7.07 bp/trade versus 58.93 bp for the strategy, 51.86 bp excess. Its actual-budget weighted SPY price profit is about 7.70% versus 64.35% for stocks. This is timing attribution using unexecuted SPY reference prices, not a quote-executed hedge or independent SPY portfolio.

Complete-bar path median MFE 157.59 bp, median MAE -116.72 bp, median terminal 25.69 bp. Intrabar extremes are path diagnostics, not attainable stops. The executed same-day opening-to-close variant loses at every level; moving entry to close is an exposure/limit-attainment hypothesis supported by its full-year replay, not a claim that all raw intraday state means are negative.

## Informative failures and search coverage

Fresh full canonical map: 666,498 surfaces, 29,770,244 cells; raw short intraday horizons, overnight, daily one/two-day across r3/r5/r10, with full surfaces, coherent regions, parents, symbol/fold lenses. Daily two-day descriptors were converted to actual calendar holds below 48h before strategy claims. Existing strategy rankings were discarded; code/data/cache were reused.

Opening carry is weaker and sensitive to activation delay. Same-day dislocation loses after quote fills. Activity/drawdown tails lose breadth when top names are removed; scarce overnight and market-regime states have too few independent sessions. Balanced five-mechanism intraday diagnostics use only 240 intentions per mechanism and are not annual strategy evidence.

Full causal two-hour rebound: 437,092 state observations -> 193,921 eligible episodes -> 7,470 reserved annual intentions per hash/ranked head, union 9,612. Exact zero/-1bp annual execution loses despite thousands of fills. No extra filters added to salvage it. +1..+5 ranked heads retain one unresolved ERIE exit each and are explicitly not complete annual performance claims. Hash policies and ranked zero/-1 have complete liquidation coverage:

| ranked | bps | fills | cash_funded_return_pct | minute_mark_relative_drawdown_pct | green_months |
| --- | --- | --- | --- | --- | --- |
| False | -1 | 3158 | -19.278 | 21.056 | 2 |
| False | 0 | 3832 | -20.699 | 22.459 | 1 |
| False | 1 | 4080 | -25.936 | 27.800 | 1 |
| False | 2 | 4469 | -31.616 | 33.319 | 1 |
| False | 3 | 4879 | -35.031 | 37.011 | 0 |
| False | 4 | 5202 | -38.098 | 39.902 | 0 |
| False | 5 | 5511 | -44.228 | 45.677 | 0 |
| True | -1 | 3340 | -21.280 | 23.064 | 2 |
| True | 0 | 3990 | -20.401 | 22.813 | 2 |

## Limits and next test

All reported results are discovery simulations after a broad search. Weekly bootstrap conditional interval 41.26% to 90.95% does not adjust for selection or establish out-of-sample confidence. Quote attainability has positive displayed size, but account notional, depth consumption, queue/impact, and actual cancellation acknowledgements remain unvalidated. Minute-close drawdown may omit brief intraminute losses. Test the frozen policy unchanged on the later sealed data, with a stated account notional, before promotion. No further parameter fitting on that test.

Machine rules: FROZEN_STRATEGY.json. Actual funded fills: working_trades.parquet. All offsets, attempts/misses, equity/months, concentration and matched benchmark are adjacent Parquet files. Reproduce with competition_fresh_close_entry.py, competition_fresh_close_stress.py, competition_fresh_benchmark.py, then competition_fresh_finalize.py. Earlier legacy/full diagnostic folders are not promoted or substituted for the causal replay.
