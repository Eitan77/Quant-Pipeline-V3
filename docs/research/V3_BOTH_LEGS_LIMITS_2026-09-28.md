# Buy and sell limit execution probe — 2026-09-28

## Verdict
Both-leg limits modestly improve this sample, but do not establish a consistent strategy. Best grid cell: buy at midpoint +1 bp (entry offset -1), sell at scheduled-exit midpoint +4 bps. Gross quote-price return: **4.501 bps per attempted entry; 9.656 bps per filled entry**. Only **8/12 sampled months positive**. Removing the three best trades leaves **-0.366 bps per attempt**. Do not promote the peak or annualize it.

## Fixed design and coverage
Candidate 68: long continuation near recent highs, 30-minute scheduled hold; frozen neutral-ranked five-slot ledger. 120 prespecified sample trades (10 evenly spaced ledger indices per month), 118 usable quote paths. This is not full-year trade coverage. All 64 combinations of market or -1,0,1,2,3,4,5 bp entry/exit offsets tested on the same 118 attempts. No additional hypothetical costs or rebates applied.

Buy limit = entry midpoint minus offset; sell limit = exit midpoint plus offset, rounded conservatively to cents. Thus -1 buy offset is midpoint +1 bp. Entry waits up to 60 seconds then cancels; exit waits up to 60 seconds then markets, capped five minutes before exchange close. Missed entries earn zero per attempt. Passive fills require executable-side quote move-through, not mere touches; these remain fill proxies without queue or size validation. Frozen entry schedule does not refill capital from canceled entries or resolve new conflicts caused by extended exits.

## Comparisons
| Entry | Exit | bps/attempt | Entry fills | Limit exits | Market fallback exits |
|---|---|---:|---:|---:|---:|
| market | market | -5.955 | 118/118 | 0 | 0 |
| -1 | market | 3.958 | 55/118 | 0 | 0 |
| -1 | 0 | 4.055 | 55/118 | 32 | 23 |
| -1 | 4 | 4.501 | 55/118 | 26 | 29 |
| -1 | 5 | 4.416 | 55/118 | 24 | 31 |
| 0 | 4 | 0.665 | 50/118 | 25 | 25 |

The best sell offset adds only 0.543 bps/attempt over the same buy limit with market exit. The larger benefit is selective entry, but gains are concentrated in a few trades. Neighboring sell offsets remain positive; this does not remove entry-selection or sample uncertainty.

## Artifacts

`D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923\research\intraday_strategy_20260928\passive_exit_probe` contains `both_legs_replays.parquet`, `both_legs_summary.parquet` (complete 64-cell grid), and `both_legs_monthly.parquet`. Runner: `tools/intraday_passive_exit_probe.py`. All baseline market exits matched the original cached quotes; exactly 118 × 64 replay rows retained. May 2026 onward untouched.
