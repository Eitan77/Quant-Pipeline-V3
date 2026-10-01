# Frozen momentum micro-scalp expansion

Date: 2026-09-29  
Verdict: rejected as a broadly deployable strategy  
Data boundary: discovery only; replication and final holdout untouched

## Frozen test

- Twelve new dates: eight development and four later-validation dates.
- Full session from 09:45 through 15:44 ET.
- SPY, QQQ, NVDA, AAPL, MSFT, AMZN, META, and TSLA.
- Long entry required positive five-minute momentum, positive final-minute return, volume at least its trailing-20-minute median, and positive two-second OFI.
- Marketable entry at the observed ask after 250/500/1000 ms; resting 5 or 7 bp target; executable bid exit after 60 seconds.
- 0/1/2 bp additional cost stress and one/two-slot conflict replay.
- 5,566 bar-qualified quote windows; all were downloaded successfully after retry.

## Result

At 250 ms and zero added cost:

| Segment | Trades | 5 bp exit | 7 bp exit | Positive days |
|---|---:|---:|---:|---:|
| Development | 1,781 | -1.231 bp/trade | -1.206 bp/trade | 0/8 |
| Later validation | 957 | -1.619 bp/trade | -1.537 bp/trade | 0/4 |
| Combined | 2,738 | -1.367 bp/trade | -1.322 bp/trade | 0/12 |

The one-slot OFI-priority replay also failed on every day: -1.470 bp/trade for the 5 bp target and -1.453 bp/trade for the 7 bp target. Adding 1 or 2 bp of execution stress worsened results mechanically. Latency changes between 250 and 1000 ms did not rescue the rule.

## Diagnosis

- Stocks were especially poor: -1.61 bp/trade in development and -1.95 in validation. Their average entry spreads were about 1.39 and 1.51 bp.
- SPY/QQQ reduced the damage but did not produce an edge: -0.223 bp/trade in development and -0.545 in validation.
- SPY/QQQ midday, the closest match to the earlier small probe, was -0.443 in development and -1.135 in validation.
- Filters for sub-1-bp spreads, stronger OFI, stronger momentum, and different fixed time buckets all remained negative in later validation.
- Every fixed time bucket was negative in development except no credible exception; the 14:00 hour was least bad but still negative and did not constitute a positive rule.

## Conclusion

The earlier positive SPY/QQQ noon result was a small-sample discovery artifact. Crossing the spread to capture a 5-7 bp continuation did not have positive expectancy when expanded across new dates and the full session. Raising the target increased occasional winner capture but did not fix the negative entry expectancy.

Do not advance this candidate to sealed replication or live trading. A viable next microstructure strategy needs a different entry mechanism, not another target/stop tweak on five-minute momentum.

Artifacts:

- `research/momentum_micro_scalp_frozen_expansion_20260929/scope.json`
- `research/momentum_micro_scalp_frozen_expansion_20260929/signal_sample.parquet`
- `research/momentum_micro_scalp_frozen_expansion_20260929/frozen_replay.parquet`
- `research/momentum_micro_scalp_frozen_expansion_20260929/summary.csv`
- `research/momentum_micro_scalp_frozen_expansion_20260929/finite_slot_summary.csv`

