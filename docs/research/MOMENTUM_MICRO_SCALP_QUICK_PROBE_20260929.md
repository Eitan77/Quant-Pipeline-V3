# Momentum micro-scalp quick probe — 2026-09-29

## Verdict

Promising specifically in SPY/QQQ, not across the liquid-stock basket. This is a two-session/two-hour discovery probe, so it is evidence to continue—not a validated strategy.

## Scope and execution

- Discovery dates only: 2025-06-17 and 2026-03-17; replication/final holdout untouched.
- 12:00–12:59 ET sampled every five minutes.
- SPY, QQQ, NVDA, TSLA, AAPL, MSFT and AMD.
- Momentum lookbacks: 5, 15, 30, 60 and 120 completed minutes.
- Order arrives 250 ms after the signal minute closes.
- Market entry pays the SIP ask. Passive entry rests at the SIP bid and requires the later ask to move strictly below it within 1/5/15 seconds; a touch is not a fill.
- Sell target is 1/2/3 bps above the actual entry, rounded up to a cent. A fill requires the later SIP bid to move strictly above the target.
- Every filled position missing its target is forcibly sold at the SIP bid after 5/15/30/60 seconds. Missed entries remain zero-return attempts.
- Primary results below use zero commissions. Entry/forced-exit spread is already present in SIP prices.

142 unique SIP windows were downloaded with zero download errors. There were 402 lookback observations; 386 had a valid quote within one second of order arrival.

## Original 120-minute idea on SPY/QQQ

Thirty-second timeout, 15 positive-momentum attempts:

| Entry | Target | Entry fills | Target fills | Forced exits | Net bps / attempted signal |
|---|---:|---:|---:|---:|---:|
| Market at ask | 1 bp | 15 | 10 | 5 | +0.565 |
| Market at ask | 2 bp | 15 | 4 | 11 | +0.680 |
| Market at ask | 3 bp | 15 | 3 | 12 | +0.759 |
| Passive bid, wait 15 s | 1 bp | 10 | 5 | 5 | +0.298 |
| Passive bid, wait 15 s | 2 bp | 10 | 5 | 5 | +0.614 |
| Passive bid, wait 15 s | 3 bp | 10 | 2 | 8 | +0.727 |

This directly supports the mechanism in the tiny sample: after positive 120-minute momentum, even ask-paid entries had positive full-accounting expectancy over the next 30 seconds. The best result came from 3 bps rather than exactly 1 bp.

## Breadth warning

The best all-universe zero-commission passive configuration was 30-minute momentum, bid entry waiting up to 15 seconds, a 3 bp target and 30-second timeout: +0.209 bp per attempt across 99 observations. Its ETF subset returned +0.701 bp per attempt, while the five-stock subset returned -0.016 bp. The two dates also disagreed: +0.606 bp per attempt on 2025-06-17 versus -0.150 on 2026-03-17.

Therefore the early lead is SPY/QQQ, not “all liquid stocks.” Configuration selection and tiny N make these results highly uncertain. Queue position and partial fills are not modeled; strict quote move-through is used as the conservative fill proxy.

## Artifacts

- `research/momentum_micro_scalp_20260929/scope.json`
- `signal_sample.parquet`, `signal_frequency.parquet`
- `replay.parquet`, `summary.parquet`, `top_configs.csv`
- Cached quote windows under `quote_windows/`
- Runner: `tools/momentum_micro_scalp_discovery.py`
