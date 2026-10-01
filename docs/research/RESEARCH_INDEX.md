# V3 strategy research — working index

Updated: 2026-09-28. This is the compact entry point; detailed evidence stays in linked reports and Parquet files.

**Active research:** mechanism-first short-hold consistency and quote execution. Broad replay completed (187features,8269configurations). The earlier four-hour leader is retained as a benchmark, not the target design. Latest coverage-complete benchmark is documented below; old pauses and incomplete headlines are historical.

## Mandate

- Maximize executable account profit, not pooled edge size. Test ticker/time subsets, signal tails, confirmations, crossings, selective entries, and capital recycling.
- Intraday only: exit at least five minutes before the actual exchange close, including early closes.
- Costs: **−1, 0, 1, 2, 3, 4, 5 bps per side**, with no additional hidden friction assumption.
- Entire **2025-05-01–2026-04-30** is discovery. May 2026 onward remains untouched for later validation.
- User permits one position at a time with **100% equity notional**, selecting the best simultaneous opportunity causally.

## Earlier findings (superseded where noted)

| Candidate | Discovery result | Interpretation |
|---|---|---|
| Top-one opening short + reversal backup | **58.63% at 1 bp/side; 30.54% at 5 bps/side**; 0.97 trades/day; daily Sharpe 1.63; one-minute-open marked drawdown 17.36% | Strongest current positive-cost full-equity candidate; about 69% of net additive profit comes from five trades. |
| Diversified opening short combination, 10 slots | **29.24% at 1 bp/side**, 9.61% at 5; 8.21 trades/day; daily Sharpe 2.71; daily drawdown 3.58% | Lower concentration; figures average five deterministic tie orders. |
| 10-minute acceleration-confirmed short | **49.09% at zero cost; 172.06% at −1 bp/side**; 11.98 trades/day; loses at +1 bp/side | Genuine frequent-trading lead under cheap execution assumptions; one-minute extra-delay diagnostic remains positive at zero cost. |
| 5-minute high-frequency short | **47.98% at zero cost; 1,323.35% at −1 bp/side**; 45.10 trades/day | Mostly rebate-sensitive arithmetic. Gross edge is only 0.399 bp/trade and falls to 0.056 with one extra minute of delay. |
| 15-minute fresh-cross short | **19.08% at 1 bp/side**; 0.92 trades/day | Timing check survives, but frequency is limited and second-half performance is much stronger. |
| Full-year-selected ticker list | 50.61% at 1 bp/side, five slots | Earlier-selected tickers applied later produced only about 0.54%; aggressive discovery lead, weak selection stability. |

**None is proven OOS.** The full-equity candidates' five-day-block bootstrap intervals at 1 bp/side include zero. Search selection is not corrected by those intervals. Rebate and passive-fill scenarios are assumptions, not verified obtainable executions. Short availability and size-dependent capacity remain unverified.

## Research ledger

1. **Broad evidence screen:** 60,505,020 cells, all 30 intraday targets and r3/r5/r10; all 188 singles plus 125 diverse pair follow-ups; 561 capital-screened rules and 70 raw-open replays.
2. **Subset development:** ticker selection, rolling ticker selection, time windows, exact percentile tails, 1,702 threshold/time/hold refinements, shared-capital combinations and timing checks.
3. **Selective-entry extension:** 11,739 variants across 41 unaffected states; 2/5/10/20 bp favorable entry offsets, 5-minute expiry, eight holds, time buckets and capital limits. Pending/expired orders reserve capital. Sampled-open limit fills remain proxies; they did not beat the best immediate-entry top-one rule.
4. **Confirmations:** 1,015 variants covering fresh crosses, persistence, recent-price agreement/disagreement, turns, volatility, acceleration and joint filters. Added 180 top-one/ranking/entry variants. Rankings use information available before entry.
5. **Portfolio accounting:** shared slots, same-security conflict resolution, no overlapping full-equity trades, actual close cutoffs; final top-one tables compound current equity after each trade. Earlier multi-slot reports compound daily fixed-slot returns. Do not mix these conventions silently.

## Critical exclusions and lessons

- **Cached EMA feature is misaligned.** One 19,461-row security audit had zero causal-reconstruction matches; corrected ranks disagreed with 8,170,747 stored r10 labels. Rebuilt separately; the apparent extreme-corner EMA winner disappears. Do not reuse earlier EMA headline profits. Canonical caches/source were preserved.
- Twenty-four prefix-only feature checks across four unaffected finalists matched. This is targeted validation, not proof every V3 feature is correct.
- An older report mistakenly treated the requested costs as round-trip. Current reports use **per-side** costs.
- Short holds do not automatically imply frequent opportunities. Conversely, high-frequency net profit can depend almost entirely on the cost assumption.
- Adding the fast engine to the slower core improved zero-cost return but hurt the +1 bp/side result. Never sum standalone returns without shared-capital replay.

## Where everything lives

- [First strategy report](V3_INTRADAY_STRATEGIES_2026-09-28.md): diversified rules, cost ladder, consistency, EMA audit and scope.
- [Top-one and confirmations report](V3_TOP_ONE_AND_CONFIRMATIONS_2026-09-28.md): exact latest rules, seven-cost table, timing sensitivity, marked drawdown and limit-entry findings.
- Evidence root: `D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923\research\intraday_strategy_20260928`.
- Main artifacts: `scope.json`, `candidate_definitions.parquet`, `final_rules.json`, `final_results.parquet`, `final_trades.parquet`, `final_diagnostics.json`, `candidate_freeze.json`.
- Latest extension: `entry_extension\` contains `results.parquet`, `confirmation_results.parquet`, `topone_results.parquet`, corresponding trade ledgers, `sequential_results.parquet`, `full_equity_results.parquet`, `full_equity_diagnostics.json`, `timing_checks.parquet`, and `REPORT.md`.
- Reproduction scripts: `tools/intraday_strategy_search.py`, `tools/intraday_entry_search.py`, `tools/intraday_confirmation_search.py`, `tools/intraday_topone.py`, `tools/intraday_extension_report.py`. Sequential-engine combination construction is documented in the report and saved ledgers; its orchestration currently resides in the research session, not a standalone script.

## Next decision

Keep the top-one core and diversified version separate. Before accessing OOS, freeze the exact selected variant, engine scheduling, tie ranking, sizing and execution assumptions. Validate unchanged on the later period; do not present discovery improvements as independent confirmation.

## Quote sample and resumed breadth

[Corrected quote-path sample](V3_QUOTE_SAMPLE_2026-09-28.md): 20 predetermined discovery trades across five candidates, 18 usable. Market entries and all seven midpoint-relative limit offsets (-1,0,1,2,3,4,5 bps). Returns use quote entry/exit prices with no additional hypothetical costs or rebates. Supersedes the earlier ask-offset sample and cost tables. Fresh15 and core showed promising limit-entry outcomes; fast10 mixed; fast5 and reversal60 weak on this tiny sample. No promotion or annual extrapolation. Broad non-EMA replay remains running, not complete.

## Expanded quote evidence and new leader

[Expanded 24-day comparison](V3_QUOTE_EXPANDED_2026-09-28.md):390 scheduled trades across six candidates. Fast10 loses at every tested offset; mixing it into the earlier core hurts. Broad screen completed:187 features,8269 replays.

[Full discovery-year quote leaders](V3_QUOTE_LEADERS_FULL_2026-09-28.md):447 scheduled trades across two new long candidates. Current leader is rule115, up/down-return-ratio opening long, midpoint entry, four-hour scheduled exit. Covered-trade replay +114.24%,150/214 usable fills,nine positive months,12.71% daily-close drawdown.34 scheduled trades missing usable quotes. All offsets profitable; no hypothetical cost overlay. Six feature-prefix checks passed. Passive fills remain proxies, capacity unresolved, May2026+ untouched. Frozen definition:quote_leaders_full/candidate_freeze.json.

## Complete scheduled-trade coverage

[Coverage-complete replay](V3_QUOTE_COMPLETE_COVERAGE_2026-09-28.md):447/447 trades accounted for across both leaders. Longer as-of quote history and PEAK-to-DOC alias repair; all quote ages retained. Rule115 midpoint now+89.48%,170/248 fills,nine positive months. Replaces incomplete +114.24% headline. Actual limit fills/capital capacity remain unverified.

## Latest buy/sell limit probe

[Full 64-combination probe](V3_BOTH_LEGS_LIMITS_2026-09-28.md): 118/120 sample coverage. Best +4.501 bps/attempt, 55 entries, 26 limit exits, 29 market fallback exits. Only 8/12 sampled months positive; removing best three trades turns negative. Not promoted. No extra cost/rebate overlays.

## Mechanism round 2

[36 new rules and complete buy/sell quote grids](V3_MECHANISM_ROUND2_2026-09-28.md). Covers market response, price-volume dislocation and volume confirmation; raw ledgers and concentration checks saved.

## Direct market lag/overshoot

[24 fixed rules and execution diagnostics](V3_DIRECT_MARKET_LAG_2026-09-28.md). Prior-day beta only; complete cost grids and sampled buy/sell quote tests saved.

## Edge spreads and long-only

[Matched spread and high-margin long-only tests](V3_SPREAD_LONG_ONLY_2026-09-28.md). Pair-aware unmatched-leg unwind included.
