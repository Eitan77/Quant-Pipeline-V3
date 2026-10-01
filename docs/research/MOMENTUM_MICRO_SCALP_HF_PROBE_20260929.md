# High-frequency 5-minute momentum micro-scalp probe — 2026-09-29

## Verdict

The unfiltered strategy failed, but a simple volume-confirmed SPY/QQQ version was positive in both test hours. This is a promising mechanism-level smoke test, not enough observations for promotion.

## Fixed quick scope

- Two discovery sessions: 2025-06-17 and 2026-03-17; sealed periods untouched.
- SPY and QQQ from 12:00–12:59 ET, evaluated every minute.
- Signal: positive return over the last five completed one-minute bars.
- 104 signal attempts with complete SIP quote paths and zero download failures.
- Order arrival: 250 ms after the signal minute completed.
- Zero commissions. Market entries pay the ask; forced exits sell at the bid.
- Passive buys rest at the bid and require the later ask to move strictly below the order. Sell limits require the later bid to move strictly above the target. A touch is not a fill.
- Every filled entry missing its target is forcibly sold at the bid after the declared timeout.

## Result

Trading every positive five-minute signal was negative at zero commission. Merely requiring a larger five-minute gain did not improve the earlier sparse screen.

The useful selective rule was: require the current minute's volume to be at least its trailing-20-minute median.

| Entry | Target | Timeout | Attempts | Entry fills | Target fills | Forced exits | Net bps / attempt |
|---|---:|---:|---:|---:|---:|---:|---:|
| Passive bid, wait 15 s | 1 bp | 60 s | 42 | 34 | 21 | 13 | +0.089 |
| Passive bid, wait 15 s | 2 bp | 60 s | 42 | 34 | 15 | 19 | +0.314 |
| Passive bid, wait 15 s | 3 bp | 60 s | 42 | 34 | 10 | 24 | **+0.518** |
| Market at ask | 2 bp | 60 s | 42 | 42 | 18 | 24 | +0.277 |
| Market at ask | 3 bp | 60 s | 42 | 42 | 7 | 35 | **+0.412** |

The passive 3 bp rule returned +0.862 bp per attempt on the first date and +0.011 bp on the second date. The market-entry 3 bp rule returned +0.511 and +0.268 bp per attempt respectively. Thus both dates were positive when SPY and QQQ were pooled, although the later passive result was essentially flat.

There were 42 eligible attempts in two observed hours: 21 attempted signals/hour and 17 passive fills/hour. Do not extrapolate that mechanically to a full session because only midday conditions were tested.

## Interpretation

The early evidence supports frequent, selective five-minute momentum more than a 120-minute-only strategy. The selection variable that helped was contemporaneous relative volume, not raw momentum magnitude. The 3 bp target dominated 1 bp because the target winners paid for many forced exits, while the underlying positive drift also made some forced exits profitable.

Queue position, partial fills and capital-sized depth remain unmodeled. Strict quote move-through is conservative about whether an order filled, but it does not prove that a real order at the back of the queue would receive the full requested size.

## Artifacts

- `research/momentum_micro_scalp_hf_20260929/scope.json`
- `signal_sample.parquet`, `replay.parquet`, `summary.parquet`
- `selective_summary.parquet`, `selective_top.csv`
- Cached SIP paths under `quote_windows/`
- Runner: `tools/momentum_micro_scalp_hf_probe.py`
