# Concentration comparison, 2026-09-30

Same frozen stock state, rank, closing clocks, limits and May 2025-April 2026 discovery. Only position capacity changes: one, two, three or ten slots. All seven prescribed per-side offsets were replayed from existing complete quote outcomes, with zero new downloads and zero fees. Existing three/ten-slot selections and funded returns reproduce exactly. Later OOS remains untouched; the ten-slot frozen primary policy is unchanged.

At +1bp per side:

| Execution profile | Slots | Cash-funded return | Minute-close drawdown | Positive months | Fills | Names | Top-five profit share |
| --- | --- | --- | --- | --- | --- | --- | --- |
| main | 1 | +87.89% | 15.74% | 9/12 | 121 | 58 | 84.9% |
| main | 2 | +114.83% | 11.99% | 10/12 | 246 | 89 | 72.5% |
| main | 3 | +108.75% | 7.37% | 10/12 | 351 | 112 | 56.9% |
| main | 10 | +64.35% | 3.48% | 12/12 | 856 | 185 | 41.6% |
| conservative | 1 | +129.23% | 10.11% | 10/12 | 89 | 50 | 63.7% |
| conservative | 2 | +122.05% | 10.69% | 11/12 | 179 | 76 | 68.0% |
| conservative | 3 | +86.08% | 8.14% | 10/12 | 262 | 97 | 62.6% |
| conservative | 10 | +50.30% | 5.46% | 10/12 | 690 | 175 | 46.1% |

Main execution profile selects at close minute +4sec, activates buys at +5sec and sells at +1sec. Only completed exits free cash/slots. Conservative profile selects before same-minute exits, uses +5sec activation on both legs, and reuses no same-minute sale cash. Both cancel sells at +54sec and force from +56sec, before the official close, using the existing priced outcomes.

Capital is divided by free slots. A one-slot filled attempt invests all available cash in the highest eligible ranked name. Two/three slots allow overlapping carry positions and allocate cash to free slots; a failed limit stays cash and consumes the window. Selection is causal, before attainability; a pending holding can prevent a new entry. This is not hindsight choosing the best return, nor always refilling an existing holding on every day.

Ranking is the existing decile difference B-A. Inside the frozen bottom-EMA/top-older-momentum corner, many names tie; stable security/date hashes break those ties. Concentration does not supply a newly fitted predictor of the single best stock. Smaller trade samples and greater name concentration weaken confidence even when in-sample return is larger.

comparison.parquet contains all 56 combinations; each profile has exact attempts, funded trades, minute equity, monthly returns and name contributions. No unpriced reported liabilities, borrowing, capacity overflow or holds of 48h or longer occurred. Quote attainability is not live fill proof: putting all capital into one name increases order size, and account notional/displayed-depth consumption/impact have not been validated. Drawdowns use minute-close marks.

Reproduce: competition_slot_comparison.py main; conservative; report.
