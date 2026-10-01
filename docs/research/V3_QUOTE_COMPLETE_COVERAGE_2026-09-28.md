# Complete scheduled-trade quote coverage

Supersedes the incomplete-coverage headline:447/447 scheduled trades now have entry and exit quote states (248 rule115;199 rule78). Each is replayed with market entry and seven limit offsets; no trades are dropped. No hypothetical costs or rebates are applied. Passive orders may still go unfilled.

## What changed

The old five-second freshness gate excluded last-reported quotes even where historical data were available. The revised as-of replay uses the last raw quote at or before the exact order time, never a future quote. It checks positive prices/sizes and noncrossed markets on that last state, rather than reviving an older valid quote after an invalid update. Twelve windows without a preceding quote in the original short lookback were fetched with five-minute lookbacks. Raw windows and quote ages are retained. Quote state reconstruction assumes the downloaded SIP event sequence is complete; data coverage is not proof of real execution.

Two remaining trades used the old PEAK alias. The local master links PEAK and DOC to the same security ID. The [SEC filing](https://www.sec.gov/Archives/edgar/data/765880/000110465924029661/tm247564d1_8k.htm) confirms the DOC ticker transition effective March4,2024. Their quotes were acquired under DOC; original symbol provenance is retained.

Maximum entry/exit quote ages: 62.88/90.62 seconds. 138 scheduled trades have at least one quote older than five seconds. This is an explicit as-of-state model, not a claim those older quotes are independently certified executable. The old five-second run remains available as a separate sensitivity, but excluded trades made its return comparison incomplete.

## Results

| Rule | Entry offset bps | Fills/orders | Compounded discovery return | Bps/fill | Bps/day | Positive months |
|---|---|---:|---:|---:|---:|---:|
| breadth115 | -1 | 172/248 | 82.40% | 38.84 | 26.62 | 9/12 |
| breadth115 | 0 | 170/248 | 89.48% | 41.51 | 28.12 | 9/12 |
| breadth115 | 1 | 159/248 | 91.07% | 44.82 | 28.39 | 8/12 |
| breadth115 | 2 | 150/248 | 89.53% | 46.83 | 27.99 | 7/12 |
| breadth115 | 3 | 146/248 | 88.13% | 47.57 | 27.67 | 6/12 |
| breadth115 | 4 | 144/248 | 86.82% | 47.73 | 27.38 | 6/12 |
| breadth115 | 5 | 141/248 | 83.81% | 47.57 | 26.72 | 8/12 |
| breadth115 | market | 248/248 | 87.72% | 28.79 | 28.45 | 8/12 |
| breadth78 | -1 | 145/199 | 66.17% | 38.83 | 22.43 | 9/12 |
| breadth78 | 0 | 141/199 | 67.28% | 40.40 | 22.69 | 9/12 |
| breadth78 | 1 | 130/199 | 73.23% | 46.18 | 23.92 | 9/12 |
| breadth78 | 2 | 119/199 | 70.95% | 49.19 | 23.32 | 9/12 |
| breadth78 | 3 | 111/199 | 81.24% | 57.83 | 25.57 | 9/12 |
| breadth78 | 4 | 103/199 | 64.04% | 52.42 | 21.51 | 9/12 |
| breadth78 | 5 | 99/199 | 61.94% | 53.20 | 20.98 | 10/12 |
| breadth78 | market | 199/199 | 82.57% | 33.84 | 26.83 | 9/12 |

## Current decision

Keep rule115 midpoint as the candidate, but replace the earlier +114.24% headline with +89.48%. Full coverage matters: recovered trades reduced the result materially. The midpoint model fills170/248 orders, averages41.51bps/fill and has nine positive months. All seven offsets remain positive (+82.40% to +91.07%); market entry returns+87.72%. Small differences among entry methods do not establish limit-order superiority.
- breadth115 0: daily-close drawdown 19.86%; excluding five best days leaves 7.82bps per original discovery day.
- breadth78 market: daily-close drawdown 18.49%; excluding five best days leaves 12.90bps per original discovery day.

Rules, ranking,60-second cancellations, cent rounding and scheduled four-hour exits are unchanged. One full-equity position is modeled at marginal quote prices; capital-sized depth is unverified. Passive fills still require subsequent executable-side strict move-through and remain estimates. This covers every scheduled candidate trade, not every signal suppressed by the frozen schedules. May2026+ remains untouched.

Artifacts:quote_leaders_coverage/manifest.parquet,design.json,replays.parquet,summary.parquet,daily.parquet,missing.json and raw quote windows. Reproduce:tools/intraday_quote_expanded.py --full-coverage.
