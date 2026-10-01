# Scalping reassessment

Full discovery year: May 2025 through April 2026. Later out-of-sample data was not accessed. Hold times are minutes and strictly below two days. No new scalping strategy is promoted.

## Conclusion

The examined frequent momentum and reversal baselines do not yet supply a defensible executable edge. Stop the weak shock-reversal refinement branch. Do not rescue it with combinations of thresholds, time windows, trend gates, spread gates, or ticker selections.

## Evidence and useful failures

| Mechanism | Independent bar opportunities | Evidence | Decision |
|---|---:|---|---|
| Five-minute ETF shock reversal | 12,925 | Completed-close references give 0.256 bp gross per trade and 11 positive months. A preassigned 1,200-signal, twelve-month quote probe produces negative filled-entry returns even at the favorable -1 bp limit level. | Broad rule rejected after quote execution. |
| Ten-minute AMD shock reversal | 2,791 | 1.331 bp gross and ten positive months. The 480-signal quote probe is negative broadly; positive tight-spread slices contain too few fills. | No specialist promotion or filter stacking. |
| Range-breakout momentum, 5/15 minutes | 5,292–31,747 depending on scope | Negative gross returns for both ETF and liquid-stock scopes. Ranking by displacement does not repair the baseline. | No quote spending. |
| Moving-mean reversion, 15/30-minute maximum hold | 2,821–14,591 depending on scope | Two neighboring deviation thresholds, fixed entry-time mean target, and time-forced exits. Gross means remain below one basis point. All tested variants lose at +1 bp per side, before extra broker fees. Target touches are OHLC proxies, not executable fills. | No quote spending or additional gates. |
| Canonical reclaim plus momentum context, ten minutes | 768 | 4.087 bp gross across 340 names, ten positive months, and 2.087 bp after hypothetical +1 bp per side. However these trades occur on only 55 sessions and 113 entry timestamps; April has no trades. | Stronger conditional effect, but insufficient frequent independent opportunities for the requested profile. |

## Selection and capacity

Full-year canonical surfaces informed reclaim/continuation hypotheses. Parent singles, a coherent adjacent region, related 5/10/15/30-minute horizons, and coarse continuation states were replayed. Conditional observation averages were distinguished from first-episode, finite-slot trades. Reclaim's stronger conditional edge falls considerably when overlapping observations become actual opportunities.

For raw liquid-market baselines, predefined SPY/QQQ and thirteen liquid stocks used stored point-in-time stock membership. Selection tested nested shock tails and a small number of economically motivated conditions. Those experiments are diagnostic failures, not a proposed layered strategy. Strongest normalized shocks are not automatically the highest-expectancy trades.

Ranking used only information available at the signal, with outcome-independent hash ties as a comparison. One- and three-slot screens reserved positions through their maximum order/holding window and prevented overlapping positions in the same symbol. Canonical comparisons used ten fixed capital slots. Reported fixed-base returns across different slot counts should not be compared as equivalent utilization.

## Quote assumptions and limits

The shock probes used completed-bar order references, all seven prescribed per-side price offsets (-1, 0, 1, 2, 3, 4, 5 bp), 15/59-second order windows, positive-size noncrossed NBBO, and an extra second after observing the initial quote before entry activation. Entry failures return zero; a failed exit limit crosses at the final valid executable-side quote. Additional round-trip fee scenarios are explicit assumptions, not quoted broker pricing. The probes are sampled diagnostics and are not annualized full-strategy returns.

The full morning-ledger quote expansion was stopped at the user's direction. Its cached quotes are preserved; it is incomplete and has no full-year executable-performance claim. No pending downloads should continue this branch. Displayed-size capacity and live execution have not been validated.

## Artifacts

Canonical run research directory: `D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923/research/competition_scalp_full_year_20260930`.

- `bar_sensitivity.parquet`, `bar_trades.parquet`, and `reversal_structure.parquet`: broad shock, momentum, pullback and temporal evidence.
- `quote_probe/` and `quote_probe_reversion_2_10m__AMD/`: completed sampled execution probes.
- `selective/`: actual causal ranking comparisons, simple selection diagnostics, and their informative failures.
- `reset_reclaim/` and `reset_reclaim_fast/`: fresh canonical parent/context/neighbor and horizon comparisons.
- `new_baselines/`: distinct range-breakout and fixed-mean-target reversion research.
- `quote_morning_reversion_1.5_5m__etfs/STOPPED.json`: stopped expansion, not completed evidence.
