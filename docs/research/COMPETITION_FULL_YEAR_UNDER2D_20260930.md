# Full-year discovery: selective activity/dislocation reversal

Discovery: 2025-05-01–2026-04-30. Replication and final holdout remain untouched. The earlier artificial training/later split is superseded. No prior researcher rankings informed this search.

## Frozen candidate

At the prior close, rank eligible PIT stocks cross-sectionally on:

- `positive_return_sum__20d__raw__daily_close`: sum of positive daily returns over 20 sessions.
- `price_minus_sma_volnorm__20d__raw__daily_close`: distance below the 20-session SMA scaled by return volatility.

Long when the first is in bin 9 and the second in bin 0 at r10: pair `a80d744f007ca5a9b3818172`, cell 90. Enter next session at 09:31 New York, exit at 15:59. Reference prices are those minute opens. Orders start one second later and expire before the next minute. Report at buy reference +5 bp and sell reference -5 bp; all seven requested offsets were evaluated. A failed exit limit crosses at the last valid bid. A failed entry leaves cash for that session.

One position, maximum 100% gross exposure, no leverage. Multiple signals use a fixed security/date hash independent of outcomes. The lower-concentration alternative uses three equal capital slots. Nominal hold is 388 minutes; all positions close the same session.

## Evidence and execution

- Full-year broad map: 588,864 canonical surfaces / 26,302,592 cells across intraday, overnight and one-day targets; inspect multiple lenses separately rather than a single quality score.
- Tail: 155 eligible observations/trade opportunities, 0.1395% state frequency, 36 symbols, gross mean 110.56 bp, interaction lift 99.79 bp. All five populated discovery folds positive.
- Parent marginals: 10.64 and 3.37 bp gross. The joint effect is substantially stronger.
- Surface coherence: r3 corresponding broad corner 19.8 bp; r5 corner 36.2 bp; r10 most selective corner 110.6 bp. Adjacent r10 cell 91 is 47.3 bp and cell 80 is 17.7 bp. This is a graded tail, with increasing selectivity, rather than a lone unsupported spike.
- Price path: tail mean 8.1 / 22.0 / 68.3 / 91.3 / 111.2 bp at 30 / 60 / 120 / 240 / 388 minutes; median full-session MFE 212.9 bp and MAE -134.5 bp. Short exits surrender much of the effect.
- Benchmark-adjusted tail mean: 99.45 bp. These are descriptive residual comparisons, not returns of an implemented hedge.
- Nearby definitions: high upside semivariance plus low SMA distance gives 63.54 bp on 242 observations; generic close-to-close volatility gives only 13.73 bp, and negative-return sum only 6.62 bp. Positive activity matters more than generic volatility. Nearby windows have not been recomputed.
- Every selected trade passed stored PIT membership, causal timestamp, corporate-action exclusions and the under-two-day limit.

| bp per side | Stage A trades | Assumed fixed-base return | Quote entries | Limit exits | Forced exits | Quote-supported return including forced exits |
|---:|---:|---:|---:|---:|---:|---:|
| -1 | 106 | 105.18% | 69 | 46 | 23 | 61.09% |
| 0 | 106 | 103.04% | 77 | 60 | 17 | 70.98% |
| 1 | 106 | 100.90% | 78 | 69 | 9 | 72.45% |
| 2 | 106 | 98.76% | 79 | 72 | 7 | 70.38% |
| 3 | 106 | 96.62% | 80 | 75 | 5 | 68.59% |
| 4 | 106 | 94.48% | 82 | 78 | 4 | 67.20% |
| 5 | 106 | 92.34% | 82 | 79 | 3 | 65.69% |

At +5 bp per side: 80.11 bp per filled trade, 10/12 positive months, 13.26% close-mark drawdown and 16.78% minute-mark drawdown. No missing exit quote windows. Returns use fixed initial capital, with cash on idle sessions; they are not compounded. Additional broker fees and a dollar notional/depth constraint are not included.

The three-slot version has 119 filled trades, 37.57% quote-supported fixed-base return and 11/12 positive months at +5 bp per side. Its close-mark drawdown is 3.58%; this is not its intraday drawdown.

Quote acquisition used only endpoint bars that reached or improved at least one requested limit: 356 one-minute windows, 1,613,968 quote rows, approximately 17.4 MB compressed. Both sides were checked at the same original reference prices; no new offset values were optimized. This establishes the requested historical price attainability, not size or queue capacity.

## Concentration and counterevidence

- Quote-supported one-position executions span 27 symbols; 70.4% have positive total results. Top five names supply 72.4% of profit. Excluding those names leaves +31.27 bp per trade.
- Excluding the best five days leaves +29.85% fixed-base return; excluding the best month leaves +47.72%.
- Ten outcome-independent tie orders produce quote-supported returns from +56.72% to +81.86%. The frozen rule retains the pre-existing seed-zero order, not the most profitable ordering.
- Whole-discovery weekly resampling is positive, but is not selection-adjusted significance or out-of-sample validation. The entire year was used to discover the rule.
- The broader r3 one-position variant is sensitive to which simultaneous names are chosen: assumed returns range from -22.7% to +106.2% across tie orders. Do not prefer its seed-zero result merely because it is larger.
- Rare overnight shock cells show enormous apparent spreads, but many are synchronized stocks on one or a few dates. Finite capital and the elapsed-time holding limit collapse their opportunity counts. Their populated-fold denominators must be checked; a positive fraction of 1.0 can describe only one populated fold.
- Broad intraday jump states and broad daily market-volatility states lose their edge at +5 bp per side. Several short-side tails persist only on a few dates. The 10-minute reclaim/pullback tail retained a small positive result but lacked the recurring capital contribution of the selected daily structure.

## Research collections and next test

Strong interactions/selective tails: positive-activity/negative-SMA-distance reversal; upside-variance neighbor. Broad persistence: r3/r5 direction agrees, with higher participation but diluted edge. Hidden specialists: retained symbol/month ledgers expose APP, SMCI, PLTR, ENPH and TSLA contribution without using a fitted ticker whitelist. Resolution disagreements and concentrated failures are retained in the evidence map and capacity sensitivity files. Short-side and overnight leads remain separate findings, not unsupported additions to the frozen portfolio.

Next: evaluate this exact frozen definition on authorized out-of-sample data, without changing thresholds, allocation, references or order timeouts. This is the strongest quote-supported discovery candidate found here, not a validated live strategy.

Artifacts: `D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/competition_full_year_under2d_20260930/`.

Core files: `FROZEN_STRATEGY.json`, `selected_strategy_summary.json`, `selected_strategy_trades.parquet`, `selected_strategy_minute_equity.parquet`, `selected_strategy_symbols.parquet`, `selected_strategy_symbol_month.parquet`, `quote_replay/summary.parquet`, `quote_replay/attainability_trades.parquet`, `evidence_map.parquet`, `capacity_sensitivity.parquet`, `daily_core_horizons.parquet`, `integrity_and_return_basis.parquet`. Scripts live under `tools/competition_*.py`.
