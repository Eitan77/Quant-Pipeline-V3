# Momentum micro-scalp: bidirectional entry/exit research

Date: 2026-09-29  
Status: discovery only; replication and final holdout untouched

## Verdict

The stronger candidate is not a one-basis-point scalp. It is a selective long-continuation trade with a 5-7 bp resting profit target and a 60-second timeout. Directional order-flow imbalance (OFI), aligned final-minute return, and above-median relative volume were the useful entry gates. The literal short inversion is not stable enough to combine with it yet.

All returns below include the observed entry spread through quote-side execution, but are before residual regulatory fees, broker-specific routing effects, latency slippage, and market impact.

## Scope

- Discovery: eight sampled sessions, 12:00-12:59 ET, SPY and QQQ, one-minute decision cadence.
- Later check: 2026-04-21 and 2026-04-28, QQQ only.
- Entry path: current SIP quotes; market entry means ask for longs and bid for shorts. Hybrid entries rested for one or five seconds, then crossed.
- Exit path: executable quote side, strict target-through logic, 60-second timeout.
- Exit sweep: 2/3/4/5/7 bp targets; 2/3/5 bp hard stops; breakeven and trailing variants.

## Best long specification

Entry:

1. Positive five-minute momentum.
2. Final one-minute return also positive.
3. Current one-minute volume at least the trailing-20-minute median.
4. Directional two-second OFI positive.
5. Enter with a tightly capped marketable limit; when simultaneous signals compete, rank by OFI.

Exit candidates:

| Exit | Raw opportunities | Mean bp/trade | Positive days | Ex-best-day bp/trade | Later QQQ check |
|---|---:|---:|---:|---:|---:|
| 2 bp target / 60 sec | 77 | 0.494 | 6/8 | 0.223 | 0.383, 2/2 days |
| 5 bp target / 60 sec | 77 | 0.911 | 6/8 | 0.216 | 0.841, 2/2 days |
| 7 bp target / 60 sec | 77 | 1.170 | 6/8 | 0.243 | 0.650, 2/2 days |
| 5 bp target, breakeven after +1 bp | 77 | 0.477 | 7/8 | 0.266 | 0.267, 1/2 days |

The 7 bp target wins pooled return, but much of its advantage is winner convexity: excluding the best day, 2, 5, and 7 bp targets are close. The 5 bp target is the more conservative working candidate. A 2 bp hard stop reduced discovery performance sharply (5 bp target: 0.911 to 0.206 bp/trade), so tight symmetric stops are not supported.

## Frequency and finite slots

There were 77 qualifying long opportunities in eight monitored hours, or 9.6 per hour across SPY and QQQ.

With one concurrent slot and OFI priority:

| Exit | Selected trades | Trades/hour | Mean bp/trade | Positive days | Worst day |
|---|---:|---:|---:|---:|---:|
| 5 bp target | 59 | 7.4 | 0.843 | 7/8 | -0.887 bp |
| 7 bp target | 59 | 7.4 | 1.046 | 7/8 | -0.887 bp |
| 5 bp + breakeven after +1 | 59 | 7.4 | 0.467 | 8/8 | +0.187 bp |

Two slots retained 76 of 77 opportunities. This means the current signal supply is high enough for roughly 7-10 trades/hour in the tested window, but not 50 independent trades/day without extending hours or the liquid universe.

## Short side

Short continuation produced more signals but weaker stability:

- Market entry, 3 bp target: 210 opportunities, +0.270 bp/trade, only 4/8 positive days, -12.94 bp worst day.
- Market entry, 2 bp target: +0.078 bp/trade, 3/8 positive days, and -0.069 bp/trade excluding the best day. It happened to earn +0.572 bp/trade on 18 later QQQ signals, which is not enough to overturn the weak discovery stability.
- The earlier passive-ask short candidate filled only 64 of 187 opportunities and failed its later check: three fills, no targets, -0.466 bp total.

Conclusion: keep short signals as a separate research branch. Do not assume symmetry or use them to inflate trade count.

## Execution implications

- A marketable limit entry is preferable to an uncapped market order, but it still crosses the spread. The profit-taking order can rest passively.
- Displayed orders at the same price are queue-prioritized by receipt time. Post-only entries avoid crossing but add fill uncertainty and adverse-selection risk.
- OFI and queue imbalance are standard microstructure predictors, but they should gate entries rather than be treated as guaranteed fills.
- Use native target orders where possible; monitor timeout/stop logic with cancel-replace safeguards, partial-fill handling, stale-quote checks, and locked/crossed-market guards.
- Short deployment additionally needs borrow availability and Rule 201 handling.

Primary references:

- Nasdaq equities order types and price-time priority: https://nasdaqtrader.com/Trader.aspx?id=TradingUSEquities
- Nasdaq post-only order behavior: https://www.nasdaqtrader.com/content/productsservices/trading/MPPO_factsheet.pdf
- Order-flow imbalance evidence: https://arxiv.org/abs/1011.6402
- Queue-imbalance evidence: https://arxiv.org/abs/1512.03492
- Alpaca order behavior and price increments: https://docs.alpaca.markets/us/docs/orders-at-alpaca
- SEC Rule 201 FAQ: https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions-7

## Next research step

Freeze the long 5 bp / 60-second rule as the conservative baseline and the 7 bp target as its higher-take challenger. Extend the same causal quote replay to more intraday windows and a small, predeclared set of very liquid names. Rank simultaneous candidates by OFI and validate with one- and two-slot replays. Keep targets, entry rules, and the short branch frozen while adding dates so the result is not tuned to ten sampled sessions.

