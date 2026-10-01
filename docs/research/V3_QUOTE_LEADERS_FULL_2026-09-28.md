> Superseded by [complete coverage](V3_QUOTE_COMPLETE_COVERAGE_2026-09-28.md). The +114.24% figure below excludes trades; updated midpoint result is +89.48%.

# Expanded quote comparison

251 discovery sessions; 447 scheduled trades across 2 candidates. 387 have usable quote windows; 60 are excluded. No May 2026+ data. No hypothetical cost overlay. All exits remain intraday.

## Method and limits

Market entry and seven midpoint-relative limit offsets (-1,0,1,2,3,4,5 bps); positive offset demands a better entry in the trade direction. Whole-cent rounding. Latest valid quote within five seconds before arrival, otherwise first valid quote within one second after. Marketable limits execute at quoted ask for buys or bid for sells. Passive orders require strict executable-side move-through within 60 seconds, filled at the limit. Scheduled exits use opposite-side quote. No-fill attempts earn zero.

One position uses full current equity sequentially; pending orders reserve capital for 60 seconds. Combined strategies prioritize the named engine at simultaneous arrivals. These are frozen standalone signal schedules: signals previously blocked by standalone positions are not regenerated after missed fills or portfolio conflicts. Consequently this is a schedule-based comparison, not a complete live signal-union backtest. Missing quote trades are excluded, making P&L incomplete; coverage is shown below. Quote fills are marginal small-order proxies, not proof of full-equity capacity. Queue, latency, borrow, and actual fees/rebates are not modeled.

## Coverage

- breadth115: 214/248 usable scheduled trades.
- breadth78: 173/199 usable scheduled trades.

## All results

Bps/day averages over all selected days, including idle days. The 24-session diagnostic uses two sessions per month; the full-year run uses every session. Sample return compounds those sessions only, never annualized. Missing trades are not evidence of zero return.

| Candidate | Offset | Fills/attempts | Bps/fill | Bps/attempt | Bps/day | Positive sampled months | First/second half bps/day |
|---|---|---:|---:|---:|---:|---:|---:|
| breadth115 | -1 | 152/214 | 51.80 | 36.79 | 31.37 | 9/12 | 18.91 / 43.92 |
| breadth115 | 0 | 150/214 | 54.89 | 38.47 | 32.80 | 9/12 | 18.91 / 46.81 |
| breadth115 | 1 | 139/214 | 59.59 | 38.70 | 33.00 | 8/12 | 20.21 / 45.88 |
| breadth115 | 2 | 131/214 | 60.41 | 36.98 | 31.53 | 8/12 | 21.06 / 42.08 |
| breadth115 | 3 | 127/214 | 61.50 | 36.49 | 31.12 | 8/12 | 21.56 / 40.75 |
| breadth115 | 4 | 125/214 | 61.75 | 36.07 | 30.75 | 8/12 | 20.81 / 40.78 |
| breadth115 | 5 | 122/214 | 61.79 | 35.23 | 30.03 | 8/12 | 18.89 / 41.27 |
| breadth115 | market | 214/214 | 34.24 | 34.24 | 29.19 | 8/12 | 11.96 / 46.56 |
| breadth78 | -1 | 125/173 | 36.48 | 26.36 | 18.17 | 8/12 | 24.03 / 12.26 |
| breadth78 | 0 | 121/173 | 38.14 | 26.67 | 18.38 | 8/12 | 25.14 / 11.57 |
| breadth78 | 1 | 110/173 | 44.50 | 28.29 | 19.50 | 9/12 | 26.70 / 12.24 |
| breadth78 | 2 | 100/173 | 48.14 | 27.83 | 19.18 | 9/12 | 24.47 / 13.85 |
| breadth78 | 3 | 94/173 | 58.38 | 31.72 | 21.86 | 9/12 | 26.58 / 17.11 |
| breadth78 | 4 | 86/173 | 51.74 | 25.72 | 17.73 | 8/12 | 26.70 / 8.69 |
| breadth78 | 5 | 82/173 | 52.47 | 24.87 | 17.14 | 9/12 | 24.41 / 9.82 |
| breadth78 | market | 173/173 | 31.92 | 31.92 | 22.00 | 8/12 | 34.63 / 9.28 |

## Concentration and uncertainty

Descriptive 95% bootstrap intervals resample the daily returns (5,000 draws, seed 20260928); they do not correct candidate selection or establish out-of-sample evidence.
- breadth115, observed best offset 1: mean 33.00 bps/day; descriptive interval [6.01, 61.37]; removing two best days leaves 22.00 bps per original sampled day.
- breadth78, observed best offset market: mean 22.00 bps/day; descriptive interval [-5.70, 51.50]; removing two best days leaves 15.66 bps per original sampled day.

## Broader discovery completed

187 non-EMA features, 8,269 replay configurations. Bar-based single-position leaders at +1 bp/side: up_down_return_ratio rule115 +193.98%, market_return rule78 +146.61%, positive_jump_fraction rule338 +133.52%. These are selected discovery returns, not quote-confirmed annual performance. Their best five trades account for roughly 42%,36%,36% of additive gross profit; positive months 10,10,9. Each trades roughly once per day with a 240-minute hold. The top two are included in this full-year quote comparison.

Artifacts: quote_leaders_full/design.json, manifest.parquet, replays.parquet, summary.parquet, daily.parquet, missing.json and raw quote windows. Reproduce with tools/intraday_quote_expanded.py and tools/intraday_quote_expanded_report.py.

## Current candidate decision

Prefer rule115 at midpoint (offset0), rather than optimizing the tiny difference to offset+1. Midpoint returned +114.24% over the covered-trade discovery replay; 150/214 usable orders filled, nine positive months, 12.71% daily-close drawdown, 52.67% winning fills, median +14.49bps/fill. Intraday drawdown is not measured here. Excluding the five best days still leaves +12.50bps per original discovery day. All seven offsets remain positive, around +100.7% to +115.6%; market entries return +92.93%. Missing34 of248 scheduled trades are excluded, not demonstrated unfilled. Their bar-reference average is +18.68bps, but cannot substitute for quote returns.

Rule: go long the highest-ranked eligible stock in the top decile of 30-minute up/down-return ratio at the first eligible opening timestamp, ranked by absolute prior-five-minute price movement. All observed signals occurred at09:35ET, order arrival09:36. The lookback uses available session history, so the opening signal reflects approximately five minutes of data despite the 30-minute feature label. Submit midpoint buy limit, cancel after60seconds, no second attempt that day. Sell at the original scheduled four-hour exit; always flat before close. Exact discovery freeze is in candidate_freeze.json. Stored decile boundaries need a causal live translation before deployment; this is a research candidate, not a completed trading system.

Both new leaders passed six prefix-only feature reconstructions, three each. The holdout remains untouched. Next decisive work is closing quote coverage, validating capital-sized execution and fixed-rule OOS testing when authorized. Do not interpret discovery bootstrap intervals as protection against selecting among thousands of candidates.
