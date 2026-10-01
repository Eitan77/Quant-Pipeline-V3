# Mechanism-first consistency research

Goal: find recurring per-trade expectancy, then adjust slots, frequency and capital. Lower exposure cannot repair negative expectancy. All-positive discovery months are descriptive, not proof of a stable edge.

Screened short-hold (1-30minute) non-EMA definitions with at least2500 observations and100 observations per month; ranked monthly downside and selected24 distinct feature-pair definitions with11-12 positive pooled months. This is explicitly discovery selection, not an independent consistency test. Replayed neutral deterministic and prior-move ranking,1/5/10slots,25/50/100%total capital, and all seven bar-cost assumptions. Neutral ranks use a deterministic security hash, not future returns. Capital is divided across slots using day-start equity. Missing scheduled exit bars execute at the first subsequent available minute open before the close buffer; complete ledgers are saved.

## Mechanism hypotheses

- Opening failed-breakout/price-path reversal: ten-minute long entries conditioned on a spread proxy and failed-breakout state (mechanism2); downside-run variant (9).
- Afternoon reversal: ten-minute longs conditioned on path convexity and negative acceleration (11).
- Morning burst exhaustion: two-minute shorts conditioned on fast-minus-slow returns and positive-jump fraction (19).
- Late-session short drift: thirty-minute shorts conditioned on a spread proxy and information discreteness (10), or permutation entropy (12).

These descriptions are hypotheses from signal definitions, not causal explanations established by the backtest. Neighbor analysis is saved: mechanism11 has positive adjacent-cell means but only10 positive months; mechanism19 has one similarly positive neighbor and one sharply negative neighbor; mechanism2 is locally fragile.

## Bar-reference examples, zero assumed cost

| Mechanism | Slots | Trades/day | Return | Daily-close DD | Positive months |
|---|---:|---:|---:|---:|---:|
| 2 | 10 | 28.62 | 15.95% | 1.98% | 12/12 |
| 11 | 10 | 58.80 | 14.13% | 1.86% | 12/12 |
| 19 | 5 | 8.25 | 8.65% | 0.51% | 12/12 |
| 9 | 1 | 1.81 | 28.94% | 6.04% | 11/12 |
| 10 | 5 | 4.98 | 14.51% | 2.68% | 10/12 |
| 12 | 10 | 9.99 | 10.63% | 2.31% | 10/12 |

The first three have12 positive months in the bar replay but very thin margins; at+1bp/side, mechanism2 is+0.43%,11 is-15.05%,19 is+0.02%. Reducing capital changes profit/drawdown scale, not the underlying execution problem. Daily-close drawdowns exclude intraday excursions.

## Quote diagnostic

Four predetermined ledger indices per month per candidate,288scheduled sample trades. No profit-based sample selection. Market plus seven midpoint-relative limit offsets.60second wait; no hypothetical fee/rebate overlay. Passive fills require strict move-through; missing quote states are explicitly listed in missing.json. This is a marginal-order fill proxy, not a portfolio or queue simulation. Frozen timestamps allow comparable execution testing but do not regenerate signals after unfilled orders.

| Mechanism | Entry | Fills/covered attempts | Bps/fill | Bps/attempt |
|---|---|---:|---:|---:|
| mechanism10 | -1 | 30/48 | 7.49 | 4.68 |
| mechanism10 | 0 | 27/48 | 11.17 | 6.28 |
| mechanism10 | 1 | 24/48 | 11.89 | 5.94 |
| mechanism10 | 2 | 17/48 | 13.18 | 4.67 |
| mechanism10 | 3 | 13/48 | 22.63 | 6.13 |
| mechanism10 | 4 | 12/48 | 22.50 | 5.63 |
| mechanism10 | 5 | 8/48 | 13.19 | 2.20 |
| mechanism10 | market | 48/48 | -1.16 | -1.16 |
| mechanism11 | -1 | 26/48 | -11.17 | -6.05 |
| mechanism11 | 0 | 23/48 | -10.58 | -5.07 |
| mechanism11 | 1 | 20/48 | -11.10 | -4.63 |
| mechanism11 | 2 | 17/48 | -11.56 | -4.09 |
| mechanism11 | 3 | 16/48 | -13.30 | -4.43 |
| mechanism11 | 4 | 15/48 | -14.86 | -4.64 |
| mechanism11 | 5 | 14/48 | -14.34 | -4.18 |
| mechanism11 | market | 48/48 | -7.69 | -7.69 |
| mechanism12 | -1 | 23/48 | -18.35 | -8.79 |
| mechanism12 | 0 | 20/48 | -19.79 | -8.25 |
| mechanism12 | 1 | 19/48 | -18.64 | -7.38 |
| mechanism12 | 2 | 18/48 | -25.84 | -9.69 |
| mechanism12 | 3 | 13/48 | -20.26 | -5.49 |
| mechanism12 | 4 | 10/48 | -21.23 | -4.42 |
| mechanism12 | 5 | 7/48 | -30.00 | -4.38 |
| mechanism12 | market | 48/48 | -15.82 | -15.82 |
| mechanism19 | -1 | 20/48 | -9.77 | -4.07 |
| mechanism19 | 0 | 19/48 | -9.95 | -3.94 |
| mechanism19 | 1 | 16/48 | -12.06 | -4.02 |
| mechanism19 | 2 | 12/48 | -13.62 | -3.40 |
| mechanism19 | 3 | 11/48 | -11.68 | -2.68 |
| mechanism19 | 4 | 10/48 | -9.95 | -2.07 |
| mechanism19 | 5 | 10/48 | -9.09 | -1.89 |
| mechanism19 | market | 48/48 | -9.33 | -9.33 |
| mechanism2 | -1 | 20/47 | -18.16 | -7.73 |
| mechanism2 | 0 | 17/47 | -17.05 | -6.17 |
| mechanism2 | 1 | 15/47 | -20.21 | -6.45 |
| mechanism2 | 2 | 15/47 | -19.24 | -6.14 |
| mechanism2 | 3 | 10/47 | -23.85 | -5.08 |
| mechanism2 | 4 | 8/47 | -21.34 | -3.63 |
| mechanism2 | 5 | 7/47 | -26.62 | -3.96 |
| mechanism2 | market | 47/47 | -15.51 | -15.51 |
| mechanism9 | -1 | 21/48 | -10.40 | -4.55 |
| mechanism9 | 0 | 20/48 | -8.38 | -3.49 |
| mechanism9 | 1 | 19/48 | -5.85 | -2.32 |
| mechanism9 | 2 | 17/48 | -4.13 | -1.46 |
| mechanism9 | 3 | 15/48 | -5.22 | -1.63 |
| mechanism9 | 4 | 15/48 | -4.48 | -1.40 |
| mechanism9 | 5 | 15/48 | -3.01 | -0.94 |
| mechanism9 | market | 48/48 | -2.98 | -2.98 |

## Preset spread screens

Arrival spreads at most1,2,5bps, applied before entry; skipped signals earn zero per original attempt. The entire table is saved in spread_filters.parquet. These are exploratory sample diagnostics; choosing a profitable tiny subset is not validation.

- mechanism12,offset1,spread<=5bps:12/22fills,+1.34bps per original attempt (5.35bps/fill).
- mechanism12,offset0,spread<=5bps:13/22fills,+0.62bps per original attempt (2.30bps/fill).
- mechanism12,offset-1,spread<=5bps:14/22fills,+-0.13bps per original attempt (-0.45bps/fill).
- mechanism10,offset1,spread<=5bps:14/30fills,+-0.39bps per original attempt (-1.35bps/fill).
- mechanism10,offset0,spread<=5bps:15/30fills,+-0.44bps per original attempt (-1.40bps/fill).
- mechanism12,offsetmarket,spread<=5bps:22/22fills,+-0.66bps per original attempt (-1.44bps/fill).
- mechanism11,offsetmarket,spread<=5bps:21/21fills,+-0.91bps per original attempt (-2.08bps/fill).
- mechanism19,offsetmarket,spread<=5bps:15/15fills,+-1.63bps per original attempt (-5.20bps/fill).

## Artifacts

mechanism_consistency/:rules.parquet,results.parquet,trades.parquet,neighbors.parquet. mechanism_quote_sample/:manifest.parquet,replays.parquet,summary.parquet,spread_filters.parquet,missing.json,raw quotes. Scripts:intraday_mechanism_consistency.py,intraday_mechanism_quotes.py,intraday_mechanism_report.py. May2026+ untouched.
