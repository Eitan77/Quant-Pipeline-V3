# Edge-spread and long-only research - 2026-09-28

Screened all canonical r5 raw-return surfaces, excluding known misaligned EMA distance. Required at least 10,000 observations on each leg, long mean >=3 bp and short mean <=-3 bp. 631 pair/horizon combinations qualified. Ranked spread divided by sqrt(hold), tempered by smaller-leg frequency n/(n+10000). Selected 16 distinct pairs with a two-use feature cap. Separately selected eight high-margin long-only time subsets (>=5 bp, >=5,000 observations, >=10 pooled positive months). Correlated breakout/reclaim definitions are not independent confirmations.

Replayed exact eligible signals with a one-minute entry delay and highest contemporaneous trailing dollar volume priority. Long-only: 1/5 positions. Matched spread: 1/5 pairs, simultaneous opposite cells of the same edge, same holding horizon, no shared active ticker. Paired capital is 50/50 long/short per pair, total gross notional 100%, not two full-equity legs. Dollar neutral is not necessarily beta neutral. Actual simultaneous availability reduces pooled frequency substantially. Positions exit before close, including early closes. Cost ladder -1,0,1,2,3,4,5 bp/side saved.

## Quote samples

Four seeded random opportunities per month per strategy. Paired samples select whole pairs. 64 entry/exit offset combinations, market plus -1 through5 bp. Unfilled entries cancel after60 seconds. If exactly one pair leg fills, that leg is unwound at the entry expiry quote; no invented matching fill and no free one-leg exposure. Both-filled pair returns average the two leg returns. Exit limits have a60-second market fallback, capped five minutes before close. Quote-price returns have no hypothetical cost/rebate overlay. Strict move-through remains a queue/size-unverified fill proxy. No sample annualization.

| Strategy | Attempts | Market bps/attempt | Best entry/exit | Best bps/attempt | Filled trades/pairs | Unmatched unwinds | Positive sampled months | Excluding best3 |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| mechanism12_long1 | 48 | 52.986 | market/2 | 53.332 | 48 | 0 | 10/12 | 25.080 |
| mechanism12_paired5 | 47 | -6.775 | 1/4 | -0.065 | 4 | 27 | 3/12 | -2.966 |
| mechanism19_long5 | 48 | 16.910 | -1/5 | 19.092 | 43 | 0 | 9/12 | 12.093 |

Best-grid values are selected discovery maxima. Capital conflicts from extended limit exits require full event replay before portfolio claims.

## Bar diagnostics (not quote performance)

- 12/long/1: amihud_illiquidity__30m__raw__intraday_5m x jump_variance_share__30m__raw__intraday_5m; 240m hold. At1 bp/side: 58.23%, daily DD 15.20%, 0.99 trades or pairs/day, 8/12 positive months.
- 12/paired/5: amihud_illiquidity__30m__raw__intraday_5m x jump_variance_share__30m__raw__intraday_5m; 240m hold. At1 bp/side: 4.95%, daily DD 3.95%, 3.91 trades or pairs/day, 5/12 positive months.
- 19/long/5: market_volatility__30m__raw__intraday_5m x prior_high_reclaim_strength__30m__raw__intraday_5m; 15m hold. At1 bp/side: 3.37%, daily DD 0.42%, 0.73 trades or pairs/day, 8/12 positive months.

Artifacts: D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923\research\intraday_strategy_20260928 under spread_replay, spread_quote_sample and spread_both_legs. Detailed rules, coverage, cost ladder, legs, paired execution and quote grids saved. May2026 onward untouched.

## Broader-bin frequency check

Eight long-only definitions were also replayed using their enclosing r5 bins. Frequency increased (for rule19, from0.73 to26.41 trades/day at five slots), but its mean gross return fell from11.03 to0.055 bp/leg, with only6 positive months and negative profit excluding the best five days. Broader signals are not promoted.

## Sample decision

The paired strategy is rejected: 47/48 complete sampled pairs; even its best execution policy is negative after unmatched-leg unwinds. Both long-only samples remain positive excluding their best three trades; full quote coverage is underway. Full-year performance must replace these sample headlines before promotion.
