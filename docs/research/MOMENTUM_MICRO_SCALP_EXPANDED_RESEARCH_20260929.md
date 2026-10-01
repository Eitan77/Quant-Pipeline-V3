# Momentum micro-scalp expanded research — 2026-09-29

## Verdict

Continuous unfiltered five-minute momentum does not work. A selective QQQ rule using contemporaneous volume and two-second order-flow imbalance is promising, and a tiny later confirmation remained positive, but it is not yet validated.

All tests use zero commissions. Market entries buy the SIP ask and forced exits sell the SIP bid, so the spread is already included.

## Eight-day discovery probe

Scope: SPY/QQQ, 12:00–12:59 ET, evaluated every minute on eight prespecified discovery dates spanning May 2025 through April 2026. There were 477 positive-five-minute-momentum signals with complete SIP paths and no download errors. One active position per symbol was enforced.

Unfiltered rule, market entry, 3 bp target and 60-second timeout:

- 477 attempts, -0.325 bp per attempt
- 80 targets and 397 forced exits
- 2/8 positive days

Requiring current one-minute volume to exceed its trailing-20-minute median improved the pooled result, but the apparent profit was concentrated in one strong trend hour. Static displayed bid/ask imbalance did not make it stable.

## Applied microstructure rule

Research on short-horizon execution identifies order-flow imbalance and queue imbalance as more useful than trade volume alone. A causal two-second top-of-book OFI was therefore computed from SIP bid/ask price and size changes immediately before order arrival.

Frozen discovery candidate:

- QQQ only
- Positive five-minute momentum
- Current minute volume >= trailing-20-minute median
- Two-second OFI > 0
- Buy immediately at the SIP ask
- Rest a sell limit 2 bp above the actual entry
- Force-sell at the SIP bid after 60 seconds

Eight-day result:

- 53 attempts, 27 target exits and 26 forced exits
- +0.771 bp per attempted trade
- 6/8 positive days
- +0.480 bp per trade after removing the best day
- Worst trade: -4.735 bp
- 6.6 qualifying trades per observed hour

The corresponding passive-bid entries were weaker: waiting five seconds produced +0.331 bp per attempted signal with only 27/53 entries; waiting 15 seconds produced +0.354 bp with 34/53 entries. Marketable entry captured continuation more reliably and avoided the passive-entry adverse-selection/missed-trade problem.

## Later frozen check

The unchanged QQQ rule was applied to two later untouched discovery dates, 2026-04-21 and 2026-04-28:

- 8 qualifying trades
- 5 targets and 3 forced exits
- +0.324 bp per trade pooled
- Day results: -0.154 and +0.802 bp per trade

This is directionally supportive but far too sparse to validate the candidate. A broader volume-only QQQ variant failed this later check, confirming that raw momentum plus volume is insufficient.

## Industry-standard execution implications

1. Use a marketable limit for entry, not an uncapped market order: price at the current ask with a small protection band and cancel immediately if it does not execute. IOC is ideal when the broker/account supports it.
2. Submit the take-profit limit immediately after the confirmed entry fill. Calculate it from the actual weighted-average fill and round up to a valid cent.
3. At 60 seconds, cancel the take-profit, reconcile partial fills, and submit a protected marketable sell limit. Never leave the failed position open indefinitely.
4. Allow only one live QQQ entry/order/position. Use unique client order IDs, fill-event state transitions and explicit cancel/replace reconciliation.
5. Do not count touches as fills. Displayed orders follow price/time priority, so historical validation should continue to require strict move-through and should eventually incorporate actual order acknowledgements and partial fills.
6. Do not assume exchange maker rebates reach a retail account. The current lead does not require a rebate.

Useful references:

- Nasdaq price/time priority and Post-Only/Midpoint order types: https://nasdaqtrader.com/Trader.aspx?id=TradingUSEquities
- Alpaca limit-order, IOC, bracket/OCO and lifecycle documentation: https://docs.alpaca.markets/us/docs/orders-at-alpaca
- Gould and Bonart, *Queue Imbalance as a One-Tick-Ahead Price Predictor*: https://arxiv.org/abs/1512.03492
- Cont, Kukanov and Stoikov, *The Price Impact of Order Book Events*: https://arxiv.org/abs/1011.6402
- SEC maker-taker and routing discussion: https://www.sec.gov/newsroom/speeches-statements/us-equity-market-structure

## Remaining limitations

- SIP top-of-book is not venue-level depth or direct-feed queue position.
- Full-size capacity, partial fills, broker routing and live acknowledgment latency are not modeled.
- Only midday hours were tested; opening, lunch and closing regimes must remain separate.
- The OFI/QQQ combination was selected on the eight-day sample; the two-day check has only eight trades.
- This is discovery evidence, not authorization for replication, sealed holdout or live trading.

## Artifacts

- `research/momentum_micro_scalp_hf_expanded_20260929/`
- `research/momentum_micro_scalp_hf_confirmation_20260929/`
- `arrival_microstructure.parquet`, `replay.parquet`, `selective_summary.parquet`
- `daily_consistency_grid.csv`
- Runner: `tools/momentum_micro_scalp_hf_probe.py`
