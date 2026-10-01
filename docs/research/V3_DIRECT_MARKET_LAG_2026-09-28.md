# Direct market lag and overshoot - 2026-09-28

**Verdict: reject promotion of all three execution diagnostics.** Quote coverage is 216/216 sampled trades. Rules 9 and 24 lose under every tested entry/exit combination. Rule 23 peaks at +0.225 bp/attempt with only 13 entries and two positive sampled months; excluding its three best trades gives -1.206 bp/attempt. No quote/bar entry identity flags above 2%. Three independent CPU trailing-beta spot checks matched GPU estimates within 1e-8. No full-coverage download or additional fitted filters justified for these definitions.

24 fixed rules: lag versus overshoot, 5/15-minute lookbacks, SPY moves exceeding 5/10 bp, beta-adjusted stock deviations beyond 5 bp, 2/5/15-minute holds. Lag trades with market direction; overshoot trades against it. Beta uses the preceding 20 sessions only, nonoverlapping 5-minute open returns, minimum 100 valid observations, clipped to [0,3]. First 20 discovery sessions warm up; full-calendar denominator retained. SPY/QQQ excluded as trading stocks. Signals observe raw opens, enter one minute later and exit at least five minutes before close. Missing scheduled bar exits advance to the next available open before cutoff.

Tested 1/5/10 slots and 25/50/100% capital at -1,0,1,2,3,4,5 bp per side; 72 rule/slot schedules. No ticker/time filters. GPU beta and signal calculations. Rules 9/23 selected as frequent overshoot diagnostics despite failing half-period bar stability; rule 24 is the strongest best-five-days-trimmed top-one configuration with both bar halves positive.

## Quote execution

Six seeded random trades/month (seed 20260928), all 64 entry/exit combinations. Quotes use historical-date symbol mapping. Passive executable-side move-through is a fill proxy without queue/size validation. Entry cancels after 60 seconds; exit markets after 60 seconds if unfilled, capped five minutes before close. Positive entry offsets improve entry price, positive exit offsets improve exit price relative to scheduled midpoint, with conservative cent rounding. Long and short sides included. No extra cost or rebate overlay. No annualization. These frozen sampled schedules do not recycle canceled capital or resolve conflicts from extended exits.

| Rule | Coverage | Market bps/attempt | Best entry/exit offsets | Best bps/attempt | Fills | Positive sampled months | Excluding best 3 trades |
|---|---:|---:|---|---:|---:|---:|---:|
| 23 | 72/72 | -11.692 | 5/5 | 0.225 | 13 | 2/12 | -1.206 |
| 24 | 72/72 | -13.702 | 5/-1 | -3.975 | 9 | 2/12 | -4.839 |
| 9 | 72/72 | -16.332 | 5/market | -2.576 | 18 | 3/12 | -4.690 |

Grid maxima are selected discovery results, not proven execution policies.

## Bar diagnostics

- Rule 9: overshoot, 5m lookback, SPY move 5 bp, 15m hold, 5 slots. Zero-cost bar return 14.05%, daily DD 14.75%, 60.66 trades/day, 8/12 positive months.
- Rule 23: overshoot, 15m lookback, SPY move 10 bp, 5m hold, 5 slots. Zero-cost bar return 11.38%, daily DD 8.67%, 90.82 trades/day, 8/12 positive months.
- Rule 24: overshoot, 15m lookback, SPY move 10 bp, 15m hold, 1 slots. Zero-cost bar return 27.65%, daily DD 8.29%, 8.98 trades/day, 8/12 positive months.

Rule 23 reaches 12 positive months under hypothetical -1 bp/side costs; that is not an observed rebate. All bar diagnostics remain distinct from quote execution.

Artifacts: D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923\research\intraday_strategy_20260928 under direct_market_lag, direct_lag_quote_sample and direct_lag_both_legs. Full grids and trade ledgers saved. May 2026 onward untouched.
