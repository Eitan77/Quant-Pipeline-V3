# Late-session mechanism: full quote schedule

1249 scheduled orders;1249 with quote states. No added hypothetical costs/rebates. Entry/exit quotes are historical as-of states; passive fill requires strict move-through within60seconds. This is not queue-confirmed execution or capital-sized depth validation.

Signal: spread-proxy top decile and information-discreteness bottom decile, short during the final-hour bucket,30minute scheduled hold, mandatory close-minus-five-minute exit. These are price-path conditions; the estimated spread feature is not the actual NBBO spread. Neutral deterministic ranking; at most five original slots. One and three slots restrict that same fixed candidate schedule by the same causal hash ranking. Missed fills reserve a slot for60seconds; newly freed capital does not regenerate suppressed signals.25/50/100%total capital is divided equally across slots using day-start equity.

| Entry offset | Slots | Capital | Fills/day | Return | Daily-close DD | Positive months | Worst month |
|---|---:|---:|---:|---:|---:|---:|---:|
| -1 | 1 | 25% | 0.80 | -0.81% | 1.84% | 5/12 | -0.82% |
| -1 | 1 | 50% | 0.80 | -1.65% | 3.66% | 5/12 | -1.64% |
| -1 | 1 | 100% | 0.80 | -3.39% | 7.25% | 5/12 | -3.28% |
| -1 | 3 | 25% | 2.21 | 0.64% | 0.89% | 7/12 | -0.66% |
| -1 | 3 | 50% | 2.21 | 1.27% | 1.78% | 7/12 | -1.32% |
| -1 | 3 | 100% | 2.21 | 2.51% | 3.54% | 7/12 | -2.64% |
| -1 | 5 | 25% | 3.07 | 0.63% | 0.72% | 8/12 | -0.49% |
| -1 | 5 | 50% | 3.07 | 1.26% | 1.44% | 8/12 | -0.98% |
| -1 | 5 | 100% | 3.07 | 2.52% | 2.86% | 8/12 | -1.95% |
| 0 | 1 | 25% | 0.74 | -0.78% | 1.78% | 6/12 | -0.88% |
| 0 | 1 | 50% | 0.74 | -1.59% | 3.54% | 6/12 | -1.76% |
| 0 | 1 | 100% | 0.74 | -3.26% | 7.00% | 6/12 | -3.53% |
| 0 | 3 | 25% | 2.00 | 0.92% | 0.95% | 8/12 | -0.64% |
| 0 | 3 | 50% | 2.00 | 1.84% | 1.90% | 8/12 | -1.29% |
| 0 | 3 | 100% | 2.00 | 3.68% | 3.77% | 8/12 | -2.56% |
| 0 | 5 | 25% | 2.69 | 0.64% | 0.74% | 8/12 | -0.49% |
| 0 | 5 | 50% | 2.69 | 1.29% | 1.47% | 8/12 | -0.97% |
| 0 | 5 | 100% | 2.69 | 2.57% | 2.93% | 8/12 | -1.94% |
| 1 | 1 | 25% | 0.66 | -0.80% | 1.82% | 6/12 | -0.89% |
| 1 | 1 | 50% | 0.66 | -1.63% | 3.61% | 6/12 | -1.78% |
| 1 | 1 | 100% | 0.66 | -3.33% | 7.13% | 6/12 | -3.56% |
| 1 | 3 | 25% | 1.73 | 0.85% | 0.84% | 8/12 | -0.41% |
| 1 | 3 | 50% | 1.73 | 1.71% | 1.67% | 7/12 | -0.83% |
| 1 | 3 | 100% | 1.73 | 3.40% | 3.32% | 7/12 | -1.66% |
| 1 | 5 | 25% | 2.29 | 0.47% | 0.65% | 8/12 | -0.36% |
| 1 | 5 | 50% | 2.29 | 0.94% | 1.30% | 8/12 | -0.71% |
| 1 | 5 | 100% | 2.29 | 1.88% | 2.58% | 8/12 | -1.42% |
| 2 | 1 | 25% | 0.59 | -0.50% | 1.87% | 5/12 | -0.76% |
| 2 | 1 | 50% | 0.59 | -1.02% | 3.72% | 5/12 | -1.52% |
| 2 | 1 | 100% | 0.59 | -2.13% | 7.38% | 5/12 | -3.05% |
| 2 | 3 | 25% | 1.44 | 0.67% | 0.79% | 7/12 | -0.44% |
| 2 | 3 | 50% | 1.44 | 1.33% | 1.57% | 7/12 | -0.87% |
| 2 | 3 | 100% | 1.44 | 2.65% | 3.12% | 7/12 | -1.74% |
| 2 | 5 | 25% | 1.89 | 0.32% | 0.62% | 8/12 | -0.37% |
| 2 | 5 | 50% | 1.89 | 0.64% | 1.24% | 8/12 | -0.73% |
| 2 | 5 | 100% | 1.89 | 1.27% | 2.48% | 8/12 | -1.46% |
| 3 | 1 | 25% | 0.47 | 0.32% | 1.62% | 6/12 | -0.98% |
| 3 | 1 | 50% | 0.47 | 0.62% | 3.23% | 6/12 | -1.96% |
| 3 | 1 | 100% | 0.47 | 1.14% | 6.36% | 6/12 | -3.92% |
| 3 | 3 | 25% | 1.19 | 0.69% | 0.76% | 7/12 | -0.47% |
| 3 | 3 | 50% | 1.19 | 1.37% | 1.52% | 7/12 | -0.94% |
| 3 | 3 | 100% | 1.19 | 2.73% | 3.02% | 7/12 | -1.88% |
| 3 | 5 | 25% | 1.53 | 0.26% | 0.64% | 6/12 | -0.39% |
| 3 | 5 | 50% | 1.53 | 0.52% | 1.28% | 6/12 | -0.79% |
| 3 | 5 | 100% | 1.53 | 1.03% | 2.56% | 6/12 | -1.58% |
| 4 | 1 | 25% | 0.42 | 0.74% | 1.29% | 6/12 | -0.97% |
| 4 | 1 | 50% | 0.42 | 1.47% | 2.57% | 6/12 | -1.94% |
| 4 | 1 | 100% | 0.42 | 2.85% | 5.11% | 6/12 | -3.87% |
| 4 | 3 | 25% | 1.00 | 0.76% | 0.72% | 7/12 | -0.49% |
| 4 | 3 | 50% | 1.00 | 1.52% | 1.45% | 7/12 | -0.98% |
| 4 | 3 | 100% | 1.00 | 3.03% | 2.88% | 7/12 | -1.97% |
| 4 | 5 | 25% | 1.29 | 0.36% | 0.64% | 7/12 | -0.42% |
| 4 | 5 | 50% | 1.29 | 0.72% | 1.29% | 7/12 | -0.84% |
| 4 | 5 | 100% | 1.29 | 1.42% | 2.56% | 7/12 | -1.68% |
| 5 | 1 | 25% | 0.35 | 0.98% | 1.23% | 7/12 | -0.79% |
| 5 | 1 | 50% | 0.35 | 1.95% | 2.46% | 7/12 | -1.57% |
| 5 | 1 | 100% | 0.35 | 3.83% | 4.88% | 7/12 | -3.15% |
| 5 | 3 | 25% | 0.82 | 0.88% | 0.62% | 8/12 | -0.31% |
| 5 | 3 | 50% | 0.82 | 1.77% | 1.24% | 8/12 | -0.63% |
| 5 | 3 | 100% | 0.82 | 3.54% | 2.46% | 8/12 | -1.25% |
| 5 | 5 | 25% | 1.07 | 0.47% | 0.53% | 7/12 | -0.29% |
| 5 | 5 | 50% | 1.07 | 0.94% | 1.06% | 7/12 | -0.57% |
| 5 | 5 | 100% | 1.07 | 1.87% | 2.11% | 7/12 | -1.14% |
| market | 1 | 25% | 1.00 | -1.45% | 2.28% | 5/12 | -1.02% |
| market | 1 | 50% | 1.00 | -2.91% | 4.52% | 5/12 | -2.04% |
| market | 1 | 100% | 1.00 | -5.88% | 8.90% | 5/12 | -4.04% |
| market | 3 | 25% | 3.00 | -0.03% | 1.09% | 4/12 | -0.58% |
| market | 3 | 50% | 3.00 | -0.07% | 2.18% | 4/12 | -1.16% |
| market | 3 | 100% | 3.00 | -0.19% | 4.33% | 4/12 | -2.32% |
| market | 5 | 25% | 4.98 | 0.17% | 0.96% | 7/12 | -0.61% |
| market | 5 | 50% | 4.98 | 0.33% | 1.91% | 7/12 | -1.22% |
| market | 5 | 100% | 4.98 | 0.62% | 3.80% | 7/12 | -2.43% |

The discovery sample selected this mechanism. Full-year discovery confirms or rejects that lead but is not OOS evidence. Daily-close DD does not bound intraday drawdown. Lower capital reduces both gain and loss; it cannot turn a negative month positive. Adjacent-offset stability matters more than one best cell. Features passed six prefix-only checks. May2026+ untouched.

Artifacts:mechanism_quote_full/{manifest,replays,portfolio_results,portfolio_daily}.parquet;missing.json. Reproduce with intraday_mechanism_quotes.py --mechanism-full and intraday_mechanism_full_report.py.
