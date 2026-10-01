# Expanded quote comparison

Predetermined 24 discovery sessions, two per month; 390 scheduled trades across six candidates. 340 have usable quote windows; 50 are excluded. No May 2026+ data. No hypothetical cost overlay. All exits remain intraday.

## Method and limits

Market entry and seven midpoint-relative limit offsets (-1,0,1,2,3,4,5 bps); positive offset demands a better entry in the trade direction. Whole-cent rounding. Latest valid quote within five seconds before arrival, otherwise first valid quote within one second after. Marketable limits execute at quoted ask for buys or bid for sells. Passive orders require strict executable-side move-through within 60 seconds, filled at the limit. Scheduled exits use opposite-side quote. No-fill attempts earn zero.

One position uses full current equity sequentially; pending orders reserve capital for 60 seconds. Combined strategies prioritize the named engine at simultaneous arrivals. These are frozen standalone signal schedules: signals previously blocked by standalone positions are not regenerated after missed fills or portfolio conflicts. Consequently this is a schedule-based comparison, not a complete live signal-union backtest. Missing quote trades are excluded, making P&L incomplete; coverage is shown below. Quote fills are marginal small-order proxies, not proof of full-equity capacity. Queue, latency, borrow, and actual fees/rebates are not modeled.

## Coverage

- breadth115: 20/24 usable scheduled trades.
- breadth338: 23/24 usable scheduled trades.
- breadth78: 16/16 usable scheduled trades.
- core240: 21/23 usable scheduled trades.
- fast10: 238/279 usable scheduled trades.
- fresh15: 22/24 usable scheduled trades.

## All results

Bps/day averages over all 24 selected days, including idle days. Months contain only two sampled sessions. Sample return compounds those sessions only, never annualized. Missing trades are not evidence of zero return.

| Candidate | Offset | Fills/attempts | Bps/fill | Bps/attempt | Bps/day | Positive sampled months | First/second half bps/day |
|---|---|---:|---:|---:|---:|---:|---:|
| breadth115 | -1 | 15/20 | 143.76 | 107.82 | 89.85 | 6/12 | 153.13 / 26.58 |
| breadth115 | 0 | 14/20 | 151.56 | 106.09 | 88.41 | 6/12 | 149.79 / 27.03 |
| breadth115 | 1 | 14/20 | 153.50 | 107.45 | 89.54 | 6/12 | 151.35 / 27.73 |
| breadth115 | 2 | 14/20 | 154.27 | 107.99 | 89.99 | 6/12 | 151.95 / 28.03 |
| breadth115 | 3 | 14/20 | 155.18 | 108.63 | 90.52 | 6/12 | 152.32 / 28.72 |
| breadth115 | 4 | 13/20 | 155.42 | 101.02 | 84.19 | 6/12 | 139.23 / 29.14 |
| breadth115 | 5 | 13/20 | 156.22 | 101.54 | 84.62 | 6/12 | 139.63 / 29.61 |
| breadth115 | market | 20/20 | 76.20 | 76.20 | 63.50 | 5/12 | 123.44 / 3.56 |
| breadth338 | -1 | 15/23 | 0.57 | 0.37 | 0.36 | 5/12 | -25.22 / 25.93 |
| breadth338 | 0 | 15/23 | 1.11 | 0.72 | 0.69 | 5/12 | -24.90 / 26.28 |
| breadth338 | 1 | 15/23 | 2.45 | 1.60 | 1.53 | 5/12 | -23.89 / 26.95 |
| breadth338 | 2 | 15/23 | 3.51 | 2.29 | 2.19 | 5/12 | -23.26 / 27.65 |
| breadth338 | 3 | 15/23 | 4.43 | 2.89 | 2.77 | 5/12 | -22.55 / 28.09 |
| breadth338 | 4 | 14/23 | 20.46 | 12.46 | 11.94 | 5/12 | -21.91 / 45.79 |
| breadth338 | 5 | 13/23 | 1.50 | 0.85 | 0.81 | 5/12 | -44.48 / 46.10 |
| breadth338 | market | 23/23 | -29.21 | -29.21 | -27.99 | 6/12 | -41.37 / -14.62 |
| breadth78 | -1 | 12/16 | 120.19 | 90.14 | 60.09 | 6/12 | 44.60 / 75.58 |
| breadth78 | 0 | 12/16 | 120.97 | 90.73 | 60.48 | 6/12 | 44.95 / 76.02 |
| breadth78 | 1 | 11/16 | 151.66 | 104.26 | 69.51 | 6/12 | 62.45 / 76.57 |
| breadth78 | 2 | 11/16 | 152.48 | 104.83 | 69.89 | 6/12 | 62.68 / 77.09 |
| breadth78 | 3 | 10/16 | 148.24 | 92.65 | 61.76 | 6/12 | 63.04 / 60.49 |
| breadth78 | 4 | 9/16 | 158.48 | 89.15 | 59.43 | 5/12 | 57.96 / 60.91 |
| breadth78 | 5 | 9/16 | 159.35 | 89.64 | 59.76 | 5/12 | 58.20 / 61.32 |
| breadth78 | market | 16/16 | 98.72 | 98.72 | 65.81 | 7/12 | 38.30 / 93.32 |
| core240 | -1 | 13/21 | 8.14 | 5.04 | 4.41 | 5/12 | 3.38 / 5.44 |
| core240 | 0 | 13/21 | 8.53 | 5.28 | 4.62 | 5/12 | 3.68 / 5.56 |
| core240 | 1 | 13/21 | 9.92 | 6.14 | 5.38 | 5/12 | 4.62 / 6.13 |
| core240 | 2 | 11/21 | 10.15 | 5.32 | 4.65 | 5/12 | 5.21 / 4.10 |
| core240 | 3 | 10/21 | -18.91 | -9.01 | -7.88 | 4/12 | 5.60 / -21.36 |
| core240 | 4 | 9/21 | -22.02 | -9.44 | -8.26 | 3/12 | 4.59 / -21.11 |
| core240 | 5 | 9/21 | -21.15 | -9.06 | -7.93 | 3/12 | 5.04 / -20.90 |
| core240 | market | 21/21 | -8.55 | -8.55 | -7.48 | 6/12 | -24.57 / 9.61 |
| fast10 | -1 | 142/238 | -6.56 | -3.92 | -38.77 | 3/12 | -33.67 / -43.87 |
| fast10 | 0 | 129/238 | -7.93 | -4.30 | -42.52 | 2/12 | -37.73 / -47.31 |
| fast10 | 1 | 116/238 | -7.78 | -3.79 | -37.53 | 3/12 | -30.89 / -44.16 |
| fast10 | 2 | 98/238 | -7.29 | -3.00 | -29.71 | 4/12 | -27.33 / -32.10 |
| fast10 | 3 | 82/238 | -6.10 | -2.10 | -20.80 | 5/12 | -19.42 / -22.18 |
| fast10 | 4 | 68/238 | -9.27 | -2.65 | -26.22 | 4/12 | -27.21 / -25.22 |
| fast10 | 5 | 56/238 | -6.82 | -1.60 | -15.93 | 3/12 | -18.71 / -13.15 |
| fast10 | market | 238/238 | -6.81 | -6.81 | -67.24 | 2/12 | -32.88 / -101.60 |
| fresh15 | -1 | 13/22 | -22.06 | -13.04 | -11.95 | 2/12 | -20.24 / -3.67 |
| fresh15 | 0 | 11/22 | -29.96 | -14.98 | -13.74 | 0/12 | -24.03 / -3.44 |
| fresh15 | 1 | 11/22 | -28.84 | -14.42 | -13.23 | 0/12 | -23.29 / -3.16 |
| fresh15 | 2 | 11/22 | -27.41 | -13.71 | -12.57 | 0/12 | -22.47 / -2.67 |
| fresh15 | 3 | 10/22 | -26.52 | -12.05 | -11.05 | 1/12 | -22.16 / 0.05 |
| fresh15 | 4 | 9/22 | -27.42 | -11.22 | -10.29 | 1/12 | -20.80 / 0.23 |
| fresh15 | 5 | 8/22 | -29.45 | -10.71 | -9.82 | 1/12 | -20.35 / 0.71 |
| fresh15 | market | 22/22 | 6.38 | 6.38 | 5.79 | 6/12 | 0.59 / 10.99 |
| combined_core240 | -1 | 121/203 | -5.73 | -3.42 | -28.63 | 5/12 | -15.04 / -42.22 |
| combined_fresh15 | -1 | 136/226 | -6.73 | -4.05 | -37.98 | 4/12 | -44.50 / -31.47 |
| combined_core240 | 0 | 111/204 | -6.90 | -3.76 | -31.63 | 5/12 | -22.98 / -40.28 |
| combined_fresh15 | 0 | 126/227 | -7.74 | -4.30 | -40.48 | 4/12 | -52.09 / -28.87 |
| combined_core240 | 1 | 103/204 | -6.78 | -3.42 | -28.81 | 5/12 | -18.42 / -39.19 |
| combined_fresh15 | 1 | 116/227 | -7.75 | -3.96 | -37.32 | 4/12 | -47.07 / -27.57 |
| combined_core240 | 2 | 91/216 | -7.43 | -3.13 | -27.99 | 5/12 | -21.06 / -34.92 |
| combined_fresh15 | 2 | 99/230 | -7.34 | -3.16 | -30.23 | 5/12 | -43.12 / -17.33 |
| combined_core240 | 3 | 82/227 | -8.33 | -3.01 | -28.23 | 5/12 | -12.32 / -44.14 |
| combined_fresh15 | 3 | 89/241 | -8.76 | -3.23 | -32.29 | 5/12 | -38.26 / -26.32 |
| combined_core240 | 4 | 69/227 | -11.15 | -3.39 | -31.90 | 5/12 | -19.08 / -44.71 |
| combined_fresh15 | 4 | 75/241 | -11.95 | -3.72 | -37.25 | 4/12 | -44.91 / -29.58 |
| combined_core240 | 5 | 61/227 | -9.63 | -2.59 | -24.39 | 3/12 | -18.35 / -30.43 |
| combined_fresh15 | 5 | 64/241 | -11.22 | -2.98 | -29.91 | 3/12 | -42.85 / -16.97 |
| combined_core240 | market | 167/167 | -8.87 | -8.87 | -61.18 | 5/12 | -73.79 / -48.57 |
| combined_fresh15 | market | 195/195 | -8.22 | -8.22 | -66.47 | 5/12 | -81.07 / -51.86 |

## Concentration and uncertainty

Descriptive 95% bootstrap intervals resample the 24 daily returns (5,000 draws, seed 20260928); they do not correct candidate selection or establish out-of-sample evidence.
- breadth115, observed best offset 3: mean 90.52 bps/day; descriptive interval [-23.84, 248.91]; removing two best days leaves -2.66 bps per original sampled day.
- breadth338, observed best offset 4: mean 11.94 bps/day; descriptive interval [-39.86, 65.85]; removing two best days leaves -12.05 bps per original sampled day.
- breadth78, observed best offset 2: mean 69.89 bps/day; descriptive interval [-5.76, 172.35]; removing two best days leaves 11.00 bps per original sampled day.
- combined_core240, observed best offset 5: mean -24.39 bps/day; descriptive interval [-85.17, 33.74]; removing two best days leaves -48.73 bps per original sampled day.
- combined_fresh15, observed best offset 5: mean -29.91 bps/day; descriptive interval [-85.99, 22.39]; removing two best days leaves -47.33 bps per original sampled day.
- core240, observed best offset 1: mean 5.38 bps/day; descriptive interval [-54.53, 64.24]; removing two best days leaves -23.37 bps per original sampled day.
- fast10, observed best offset 5: mean -15.93 bps/day; descriptive interval [-32.24, 0.68]; removing two best days leaves -21.34 bps per original sampled day.
- fresh15, observed best offset market: mean 5.79 bps/day; descriptive interval [-19.80, 32.45]; removing two best days leaves -7.64 bps per original sampled day.

## Broader discovery completed

187 non-EMA features, 8,269 replay configurations. Bar-based single-position leaders at +1 bp/side: up_down_return_ratio rule115 +193.98%, market_return rule78 +146.61%, positive_jump_fraction rule338 +133.52%. These are selected discovery returns, not quote-confirmed annual performance. Their best five trades account for roughly 42%,36%,36% of additive gross profit; positive months 10,10,9. Each trades roughly once per day with a 240-minute hold. All three included in this quote comparison.

Artifacts: quote_expanded/design.json, manifest.parquet, replays.parquet, summary.parquet, daily.parquet, missing.json and raw quote windows. Reproduce with tools/intraday_quote_expanded.py and tools/intraday_quote_expanded_report.py.
