# V3 intraday strategy discovery — 2026-09-28

**Result:** Freeze the combined opening-hour short strategy as the main diversified candidate; retain the 240-minute component for higher-cost execution. All results are discovery-only raw-bar execution models, not proven OOS performance.

## Cost comparison

Modeled compounded return over 251 discovery sessions, averaged over five deterministic entry tie orders. Costs are exactly the requested bps per side; net trade bps = gross minus twice the stated cost. No extra spread/slippage is silently imposed.

| Strategy | -1 | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---:|---:|---:|---:|---:|---:|---:|
|Opening short, 5 slots|42.12%|37.44%|32.91%|28.53%|24.29%|20.20%|16.23%|
|Combined short, 10 slots|40.33%|34.67%|29.24%|24.03%|19.02%|14.22%|9.61%|
|30-minute short, 10 slots|18.71%|15.63%|12.62%|9.70%|6.84%|4.06%|1.36%|
|Ticker-selected short, 5 slots|56.05%|53.31%|50.61%|47.96%|45.35%|42.79%|40.28%|

## Exact main rules

- Universe: the run's point-in-time eligible securities. Evaluate at its five-minute decision timestamps from 09:35 through 10:25 ET. Cross-sectional percentile ranks use average ties among valid observations at that timestamp.
- Component A (`R00530`): short when 30-minute breakdown-distance rank is below 5% and return-acceleration-halves rank is at least 90%. Enter at the exact next-minute raw open. Hold 240 clock minutes; skip any entry whose exit would be later than five minutes before that session's exchange close.
- Component B (`R00965`): short when return-acceleration-halves rank is at least 80% and return-acceleration-thirds rank is below 20%. Same entry timing; hold 30 minutes. Same close restriction.
- Combined portfolio: 10 equal-notional slots, maximum 100% aggregate short notional, one position per security. First signal wins; A wins an identical-timestamp same-security conflict. Recycle a slot only after exit. No pyramiding. Deterministic date/security hash breaks simultaneous competing entries (five seed sensitivities retained).
- Capital arithmetic: each slot uses 1/K of starting-day equity; idle cash returns zero. Daily slot returns compound between sessions. Drawdowns and Sharpe use daily realized account returns, not intraday marked-to-market equity. No overnight positions, including early closes.
- Interpretation: A selects strong negative price displacement with a rebound in recent return acceleration, then fades it. B selects disagreement between two acceleration windows and fades the short-lived rebound. These are candidate mechanisms, not established causal explanations. Exact formulas remain the versioned V3 feature definitions.

## Frequency and risk at 1 bp per side

| Strategy | Trades/day | Gross bps/trade | Daily Sharpe | Daily max drawdown |
|---|---:|---:|---:|---:|
|Opening short, 5 slots|3.34|19.60|2.01|6.55%|
|Combined short, 10 slots|8.21|14.68|2.71|3.58%|
|30-minute short, 10 slots|5.25|11.11|2.42|2.77%|
|Ticker-selected short, 5 slots|1.78|48.79|3.33|5.38%|

The faster rule does not create continuous all-day turnover: its entries concentrate in the opening hour. After 60.5 million surface cells, all 188 intraday singles, 125 diverse pair follow-ups, 561 capital-screened rules, 70 one-minute replays, ticker overlays, and 1,702 percentile/time/horizon refinements, no robust every-five-minutes money printer was established.

## Consistency and fragility

For the combined 10-slot portfolio (seed 0): 8/12 positive months at 1 bp/side; about 51% winning trades; mean gross trade return 11.12 bps in the first half versus 17.22 in the second. Removing its five best days still leaves +5.21 account bps/day. The top five securities contribute 14.9% of positive security-level profit. March and April 2026 are negative. These diagnostics use the same discovery year and are not OOS validation.
The 240-minute component has similar first/second-half gross means (21.78/21.39 bps), with neighboring 10%/20% displacement thresholds also positive. This provides stronger shape evidence than an isolated winning cell. The 30-minute component is weaker in the first half (4.18 versus 16.29 bps).
The higher-profit ticker strategy uses AKAM, SMCI, TTD, SWKS, TEL, LUV, EFX, MRNA, CZR, NXPI, selected from the entire discovery year. It shorts the C0033 market-momentum/volatility state in the opening hour and exits five minutes before close. It trades only 90 sessions. Selecting tickers using the first 126 sessions and applying them later produced only about +0.54% on average at 1 bp/side, versus +50.61% for the full-year-selected list. Keep the full-year list as an aggressive discovery candidate; do not call its high return proven.

## Timing sensitivity

| Candidate (10 slots, seed 0) | Extra entry delay | Return at 1 bp/side | Trades |
|---|---:|---:|---:|
|R00530|0 min|20.78%|983|
|R00530|1 min|18.43%|972|
|R00530|2 min|18.94%|966|
|R00965|0 min|12.55%|1318|
|R00965|1 min|11.06%|1285|
|R00965|2 min|11.62%|1285|
|combined_refined|0 min|28.45%|2061|
|combined_refined|1 min|24.95%|2020|
|combined_refined|2 min|26.16%|2016|

Delay sensitivity keeps selected signals and exits fixed; it is a bounded fill-timing check, not a fresh portfolio selection.

## Critical excluded result

The earlier EMA-based headline strategy is invalid as evidence of an EMA edge. A 19,461-observation security audit found zero matches to a correctly aligned causal EMA reconstruction; one stored -42.70% value should be +0.82%. The implementation resets an already flat grouped-apply index, breaking alignment. Reconstructed ranks disagree with 8,170,747 stored r10 labels. Corrected EMA features produce no qualifying extreme-corner candidates in the tested tail family. Original caches and pipeline source were preserved; only research-local corrected arrays were created.
Twenty-four prefix-only feature reconstructions across four unaffected finalist rules matched their stored feature values. Final trades were checked for same-security overlap and exits at least five minutes before close.

## Scope and limitations

Discovery: 2025-05-01 through 2026-04-30. May 2026 onward was not accessed. Completed evidence: 469,311/469,311 tasks. Global screen includes all 30 intraday target bases and r3/r5/r10; strategy P&L uses explicit raw price legs, not residual returns. Daily/overnight targets are excluded by the user's intraday directive. Subgroup deep replay is a selected search, not exhaustive enumeration of every possible ticker/time/threshold combination.
Short availability and fills are assumed; the cost ladder is the requested hypothetical total friction model. No limit-order queue/fill probability or size-dependent capacity is established. These are scalable-notional simulations, not a dollar-capacity claim. No stop-loss was fitted; open-price tail losses and daily drawdowns must remain visible. Freeze rules and position selection before the later OOS test.

## Artifacts

All result tables, rule definitions, trade ledgers, diagnostics and audit evidence: `D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923\research\intraday_strategy_20260928`.
Reproduction: `tools/intraday_strategy_search.py`. Canonical run artifacts were read-only; research outputs are isolated.
