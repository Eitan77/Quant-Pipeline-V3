# Quote-fill sample: corrected execution comparison

Supersedes the prior quote report and its extra cost tables. No hypothetical cost or rebate is deducted or added to quote-fill returns. Original bar-cost screens remain separate discovery tools.

Twenty predetermined trades: four each from fast10, fast5, core240, fresh15 and reversal60. Limits are -1, 0, 1, 2, 3, 4, 5 bps relative to arrival midpoint; all trades are short, so positive means a higher sale price. Sell limits are rounded upward to cents. Marketable limits receive the arrival bid. Other limits require a later bid strictly above the limit within 60 seconds, with fills priced at the limit. Exits buy at the scheduled exit ask. No fill means zero profit for that attempted opportunity.

Use latest valid quote before arrival, or first within one second afterward. Primary results require entry and exit quotes no more than five seconds old. Two attempts fail the quote-arrival/freshness checks, leaving 18 usable attempts. Market entries/exits are small-order quote-price estimates; passive fills are move-through proxies, not queue-confirmed executions. Quote size positivity is checked, but capital-sized capacity, latency and order acknowledgements are not simulated. Actual broker fees/rebates are not included. Only the entry waiting path and scheduled exit window are replayed, not dynamic exits during the holding period.

| Strategy | Entry | Fills / attempts | Bps / fill | Bps / attempt | Mean wait seconds, including cancellations |
|---|---|---:|---:|---:|---:|
| core240 | limit_+0 | 3/3 | 24.40 | 24.40 | 24.5 |
| core240 | limit_+1 | 2/3 | 63.10 | 42.07 | 33.5 |
| core240 | limit_+2 | 2/3 | 63.98 | 42.65 | 33.5 |
| core240 | limit_+3 | 2/3 | 63.98 | 42.65 | 33.5 |
| core240 | limit_+4 | 2/3 | 66.40 | 44.27 | 36.7 |
| core240 | limit_+5 | 2/3 | 66.40 | 44.27 | 36.7 |
| core240 | limit_-1 | 3/3 | 24.22 | 24.22 | 24.5 |
| core240 | market | 3/3 | 12.26 | 12.26 | 0.0 |
| fast10 | limit_+0 | 3/4 | -25.06 | -18.80 | 24.7 |
| fast10 | limit_+1 | 3/4 | -23.74 | -17.81 | 25.7 |
| fast10 | limit_+2 | 3/4 | -23.15 | -17.36 | 25.7 |
| fast10 | limit_+3 | 2/4 | 1.99 | 0.99 | 43.6 |
| fast10 | limit_+4 | 2/4 | 2.84 | 1.42 | 44.3 |
| fast10 | limit_+5 | 2/4 | 4.29 | 2.14 | 50.7 |
| fast10 | limit_-1 | 3/4 | -25.71 | -19.28 | 24.7 |
| fast10 | market | 4/4 | -26.22 | -26.22 | 0.0 |
| fast5 | limit_+0 | 3/4 | -25.55 | -19.17 | 19.7 |
| fast5 | limit_+1 | 2/4 | -32.07 | -16.03 | 32.6 |
| fast5 | limit_+2 | 2/4 | -30.95 | -15.48 | 32.6 |
| fast5 | limit_+3 | 2/4 | -30.05 | -15.02 | 39.4 |
| fast5 | limit_+4 | 2/4 | -28.94 | -14.47 | 39.5 |
| fast5 | limit_+5 | 2/4 | -28.03 | -14.02 | 40.0 |
| fast5 | limit_-1 | 4/4 | -22.97 | -22.97 | 4.7 |
| fast5 | market | 4/4 | -25.32 | -25.32 | 0.0 |
| fresh15 | limit_+0 | 2/4 | 21.63 | 10.81 | 36.8 |
| fresh15 | limit_+1 | 2/4 | 23.15 | 11.58 | 37.3 |
| fresh15 | limit_+2 | 2/4 | 24.20 | 12.10 | 43.6 |
| fresh15 | limit_+3 | 2/4 | 25.26 | 12.63 | 44.4 |
| fresh15 | limit_+4 | 2/4 | 25.73 | 12.86 | 44.4 |
| fresh15 | limit_+5 | 1/4 | 12.75 | 3.19 | 56.8 |
| fresh15 | limit_-1 | 3/4 | -0.90 | -0.68 | 36.8 |
| fresh15 | market | 4/4 | -3.60 | -3.60 | 0.0 |
| reversal60 | limit_+0 | 1/3 | -73.97 | -24.66 | 40.1 |
| reversal60 | limit_+1 | 1/3 | -72.01 | -24.00 | 53.8 |
| reversal60 | limit_+2 | 0/3 | nan | 0.00 | 60.0 |
| reversal60 | limit_+3 | 0/3 | nan | 0.00 | 60.0 |
| reversal60 | limit_+4 | 0/3 | nan | 0.00 | 60.0 |
| reversal60 | limit_+5 | 0/3 | nan | 0.00 | 60.0 |
| reversal60 | limit_-1 | 1/3 | -73.97 | -24.66 | 40.1 |
| reversal60 | market | 3/3 | -14.05 | -14.05 | 0.0 |

The sample is too small to establish expected value, frequency, or a winning offset. Repeated identical results across offsets can reflect cent rounding and the same filled trades. Compare profit per attempt, not just the conditional average of fills. No annualization or promotion is justified.

Artifacts: quote_sample/manifest.parquet, results.parquet, summary.parquet and raw *_pre30.parquet quote windows. Reproduce with tools/intraday_quote_sample.py.
