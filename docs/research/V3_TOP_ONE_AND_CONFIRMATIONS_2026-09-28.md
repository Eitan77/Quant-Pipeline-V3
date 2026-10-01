# V3 selective-entry and top-one extension

**Best positive-cost candidate:** top-one opening short plus a selective reversal backup. About 59% discovery profit at 1 bp/side; inspect the exact recomputed table below. The high-frequency alternatives are attractive only under cheaper cost assumptions. No May 2026+ data was accessed.

All rows below use one position at a time, 100% current equity notional, compounded after every completed trade. Five-minute-before-close hard cutoff; no overnight positions. Returns are modeled raw-open returns under the specified per-side friction.

| Strategy | Trades/day | -1 bp | 0 bp | 1 bp | 2 bps | 3 bps | 4 bps | 5 bps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|Top-one 240m|0.94|72.58%|64.64%|57.06%|49.83%|42.94%|36.35%|30.07%|
|Top-one plus reversal|0.97|74.87%|66.55%|58.63%|51.09%|43.90%|37.06%|30.54%|
|10m acceleration-confirmed|11.98|172.06%|49.09%|-18.31%|-55.24%|-75.48%|-86.57%|-92.64%|
|5m high-frequency|45.10|1323.35%|47.98%|-84.62%|-98.40%|-99.83%|-99.98%|-100.00%|
|15m fresh-cross|0.92|30.60%|24.71%|19.08%|13.71%|8.58%|3.68%|-1.00%|
|Core + reversal + 10m|7.69|151.04%|70.68%|16.03%|-21.13%|-46.39%|-63.57%|-75.24%|

## Rules and selection

- Top-one 240m: R00530, opening-hour breakdown-distance bottom 5% and acceleration-halves top 10%. At the first eligible decision while flat, choose the highest acceleration-halves percentile; submit after the decision and enter the next-minute raw open. Hold 240 minutes. At most one full-equity short. No return-based ticker whitelist.
- Reversal backup: C0412, acceleration-halves r10 bin 8 and acceleration-thirds bin 1, 60-minute hold, with a positive preceding five-minute price move before shorting. At simultaneous timestamps the 240m engine has priority. The combined model consumes signals from two independent virtual engines; each engine advances its own hypothetical position schedule even when the shared portfolio rejects its trade. This explicit scheduling restriction is part of the candidate, not a sum of standalone P&Ls.
- 10m acceleration-confirmed: C0210 all-day state, market-beta rank in top decile and positive-jump-fraction rank in [70%,80%), plus acceleration-halves rank >=90%; short, 10-minute hold. Select the largest absolute preceding-five-minute move at competing timestamps. One full-equity position.
- 5m high-frequency: C0490 expanded all day, market-beta top decile and positive-jump-fraction rank in [30%,40%); short, 5-minute hold, same causal tie ranking. Reentry only after prior exit.
- 15m fresh-cross: C0410, p95-subreturn bottom decile and Parkinson-volatility rank in [80%,90%), fresh state entry versus the exact prior five-minute observation. Short for 15 minutes; same causal tie ranking.

Cross-sectional ranks use V3 average-tie rules and PIT eligible observations. Market-derived rank labels can have large tie masses, so these are exact bin predicates, not necessarily economic thresholds on SPY itself.

## Evidence and fragility

Completed 11,739 entry/holding/time/capital variants across 41 non-EMA states, 1,015 confirmation variants, and 180 top-one variants. Confirmation families included fresh state entry, persistence, recent price agreement/disagreement, turns, volatility, acceleration, and joint filters. The earlier broken EMA feature remains excluded.
The 45-trades/day five-minute rule earns only 0.399 gross bps/trade. Adding one minute of entry delay reduces that to 0.056 bps. Its spectacular rebate scenario is chiefly rebate arithmetic; it is not evidence those executions receive rebates. The ten-minute acceleration-confirmed rule averages 1.38 gross bps/trade, versus 1.78 with one extra minute of delay, and is positive in both discovery halves. It loses at 1 bp/side.
The 240m top-one rule averages 23.25 gross bps/trade, 12.36 in the first half and 33.96 in the second. Its best five trades account for about 70% of net additive profit; removing them still leaves positive aggregate profit. This is substantial tail concentration, not smooth daily income.
The 15m fresh-cross rule stays positive at 1 bp/side after one- and two-minute entry delays, but has fewer than one trade per session and stronger second-half returns.

## Risk and uncertainty at 1 bp/side

| Strategy | Daily Sharpe | Daily max DD | One-minute-open MTM DD | Positive months |
|---|---:|---:|---:|---:|
|Top-one 240m|1.59|16.15%|16.83%|8/12|
|Top-one plus reversal|1.63|16.28%|17.36%|7/12|
|10m acceleration-confirmed|-1.09|26.82%|27.70%|3/12|
|5m high-frequency|-5.56|85.60%|85.80%|0/12|
|15m fresh-cross|1.87|8.18%|8.83%|8/12|
|Core + reversal + 10m|0.61|20.35%|21.42%|6/12|

Five-day-block bootstrap intervals are saved in full_equity_diagnostics.json. They describe discovery uncertainty and do not correct for selecting winners from thousands of trials. One-minute-open marking cannot capture intraminute extremes.

## Limit-entry findings

Tested 2/5/10/20 bp favorable entry offsets with five-minute expiry. Orders anchor to an observed next-minute open, then may fill only at a subsequent sampled open crossing the limit; fills are priced at the limit. Pending and expired orders reserve both capital and the security. The proxy has no queue, quote spread, or partial-fill model. It is therefore hypothetical, not quote-executable P&L.
Passive offsets generally reduced throughput and did not beat the best immediate-entry top-one rule. A fresh/high-volatility filtered C0401 2-bp-offset variant improved versus its parent, but remains a proxy and did not displace the main candidate.

## Decision

Freeze the top-one 240m candidate and its reversal backup for later OOS testing; retain the 10m acceleration-confirmed rule for genuinely zero/rebated execution. Prefer the earlier 10-slot diversified portfolio if the top-one concentration is unacceptable. No strategy here is yet proven out of sample.

Artifacts: `D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923\research\intraday_strategy_20260928\entry_extension`. Scripts: tools/intraday_entry_search.py, tools/intraday_confirmation_search.py, tools/intraday_topone.py, tools/intraday_extension_report.py.
