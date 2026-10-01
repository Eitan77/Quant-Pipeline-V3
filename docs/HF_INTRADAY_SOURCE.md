# Codex Spec — HF Intraday Run-All Edge Pack

## Rule

Everything in this file is intended to be run.

- Run **every feature** below as a single.
- Run **every exact dual pair** below.
- Build **every target** below.
- Do not add random/exploratory pairs.
- Do not skip a listed item because it looks like a conditioner.
- Do not add L1/L2/order-book features; this candidate is restricted to the available 1-minute OHLCV/VWAP/trade-count data.

These features are intentionally intraday-specific: short-lived residual shocks, liquidity/impact state, cross-sectional dislocation, PCA residuals, peer lead-lag, same-clock effects, compression/breakout state, and event response.

## Causality

Decision time is the close of completed minute `t`. All inputs must be known by then. Betas, PCA loadings, peer sets/coefficients, TOD distributions, and historical baselines must use prior data only. Daily-frozen prior-only models are allowed.

Notation:

```text
DV_t = W_t * V_t
r_h(t) = C_t / C_(t-h) - 1
e_h(t) = r_h(t) - beta_i,d * m_h(t)
u_h(t) = daily-frozen PCA common-factor residual
TOD_TAIL(x) = 2 * empirical_same_clock_percentile_prior60(x) - 1
TOD_ROBZ(x) = (x - same_clock_median_prior60) / (1.4826 * same_clock_MAD_prior60 + eps)
```

# 1. Features — RUN ALL 117 AS SINGLES

| # | Feature | Exact definition |
|---:|---|---|
| 1 | `ret_tod_tail_1m` | TOD_TAIL(r_1) |
| 2 | `resid_tod_tail_1m` | TOD_TAIL(e_1) |
| 3 | `resid_tod_tail_2m` | TOD_TAIL(e_2) |
| 4 | `resid_tod_tail_3m` | TOD_TAIL(e_3) |
| 5 | `resid_tod_tail_5m` | TOD_TAIL(e_5) |
| 6 | `ret_tod_robz_1m` | TOD_ROBZ(r_1) |
| 7 | `resid_tod_robz_1m` | TOD_ROBZ(e_1) |
| 8 | `resid_prevol_norm_1m` | e_1(t) / (std(e_1[t-30:t-1]) + eps) |
| 9 | `resid_prevol_norm_2m` | e_2(t) / (std(e_1[t-30:t-1]) * sqrt(2) + eps) |
| 10 | `shock_accel_1m` | e_1(t) - e_1(t-1) |
| 11 | `shock_excess_1pct` | sign(e_1)*max(abs(e_1)-q99_TOD(abs(e_1)),0)/(q99_TOD(abs(e_1))+eps) |
| 12 | `idio_share_1m` | abs(e_1)/(abs(e_1)+abs(beta_d*m_1)+eps) |
| 13 | `body_ret_1m` | C_t/O_t - 1 |
| 14 | `gap_ret_1m` | O_t/C_(t-1) - 1 |
| 15 | `body_share_1m` | abs(C_t-O_t)/(H_t-L_t+eps) |
| 16 | `clv_signed_1m` | 2*(C_t-L_t)/(H_t-L_t+eps)-1 |
| 17 | `dir_close_extreme_1m` | sign(e_1)*clv_signed_1m |
| 18 | `last1_abs_share_3m` | abs(e_1(t))/sum(abs(e_1(t-k)),k=0..2) |
| 19 | `last1_abs_share_5m` | abs(e_1(t))/sum(abs(e_1(t-k)),k=0..4) |
| 20 | `path_eff_3m` | abs(sum(e_1(t-k),k=0..2))/sum(abs(e_1(t-k)),k=0..2) |
| 21 | `path_eff_5m` | abs(sum(e_1(t-k),k=0..4))/sum(abs(e_1(t-k)),k=0..4) |
| 22 | `path_eff_10m` | abs(sum(e_1(t-k),k=0..9))/sum(abs(e_1(t-k)),k=0..9) |
| 23 | `same_sign_streak_1m` | sign(e_1(t))*consecutive_same_sign_run_length_ending_at_t |
| 24 | `sign_switch_rate_5m` | mean(sign(e_1(k)) != sign(e_1(k-1))) over recent 5m |
| 25 | `tail_event_count_5m` | count(abs(resid_tod_tail_1m)>=0.98) in last 5m |
| 26 | `tail_event_count_15m` | count(abs(resid_tod_tail_1m)>=0.98) in last 15m |
| 27 | `range_tod_tail_1m` | TOD_TAIL((H_t-L_t)/C_(t-1)) |
| 28 | `volume_tod_tail_1m` | TOD_TAIL(log(1+V_t)) |
| 29 | `dollar_volume_tod_tail_1m` | TOD_TAIL(log(1+W_t*V_t)) |
| 30 | `trade_count_tod_tail_1m` | TOD_TAIL(log(1+N_t)) |
| 31 | `avg_trade_size_tod_tail_1m` | TOD_TAIL(log(1+V_t/max(N_t,1))) |
| 32 | `dollar_per_trade_tod_tail_1m` | TOD_TAIL(log(1+(W_t*V_t)/max(N_t,1))) |
| 33 | `impact_per_dollar_1m` | abs(e_1)/(DV_t/1e6+eps) |
| 34 | `impact_tod_tail_1m` | TOD_TAIL(log(1+impact_per_dollar_1m)) |
| 35 | `range_per_dollar_1m` | ((H_t-L_t)/C_(t-1))/(DV_t/1e6+eps) |
| 36 | `effort_result_1m` | TOD_ROBZ(log(1+DV_t))-TOD_ROBZ(abs(e_1)) |
| 37 | `volume_return_mismatch_1m` | TOD_ROBZ(log(1+V_t))-TOD_ROBZ(abs(e_1)) |
| 38 | `trade_intensity_mismatch_1m` | TOD_ROBZ(log(1+N_t))-TOD_ROBZ(abs(e_1)) |
| 39 | `prevol_tod_tail_30m` | TOD_TAIL(sqrt(sum(e_1(t-k)^2,k=1..30))) |
| 40 | `liquidity_rank_20d` | cross-sectional percentile of prior-20-session median 1m dollar volume |
| 41 | `signed_dollar_pressure_1m` | clv_signed_1m*TOD_ROBZ(log(1+DV_t)) |
| 42 | `signed_volume_pressure_1m` | clv_signed_1m*TOD_ROBZ(log(1+V_t)) |
| 43 | `vwap_close_location_1m` | (C_t-W_t)/(H_t-L_t+eps) |
| 44 | `vwap_bar_location_1m` | (W_t-L_t)/(H_t-L_t+eps) |
| 45 | `vwap_pressure_1m` | vwap_close_location_1m*TOD_ROBZ(log(1+DV_t)) |
| 46 | `upper_rejection_pressure_1m` | ((H_t-max(O_t,C_t))/(H_t-L_t+eps))*max(TOD_ROBZ(log(1+DV_t)),0) |
| 47 | `lower_rejection_pressure_1m` | ((min(O_t,C_t)-L_t)/(H_t-L_t+eps))*max(TOD_ROBZ(log(1+DV_t)),0) |
| 48 | `wick_skew_pressure_1m` | ((min(O_t,C_t)-L_t)-(H_t-max(O_t,C_t)))/(H_t-L_t+eps)*max(TOD_ROBZ(log(1+DV_t)),0) |
| 49 | `pressure_return_divergence_1m` | signed_dollar_pressure_1m-resid_tod_robz_1m |
| 50 | `absorption_score_1m` | clv_signed_1m*max(TOD_ROBZ(log(1+DV_t))-abs(resid_tod_robz_1m),0) |
| 51 | `resid_cs_rank_1m` | cross-sectional percentile rank of e_1 at t |
| 52 | `resid_cs_rank_2m` | cross-sectional percentile rank of e_2 at t |
| 53 | `resid_cs_rank_5m` | cross-sectional percentile rank of e_5 at t |
| 54 | `resid_rank_velocity_1m` | resid_cs_rank_1m(t)-resid_cs_rank_1m(t-1) |
| 55 | `resid_rank_accel_1m` | resid_rank_velocity_1m(t)-resid_rank_velocity_1m(t-1) |
| 56 | `resid_dispersion_1m` | cross-sectional std_i(e_1(i,t)) |
| 57 | `resid_dispersion_tod_tail_1m` | TOD_TAIL(resid_dispersion_1m) |
| 58 | `tail_breadth_down_1m` | fraction of eligible stocks with resid_tod_tail_1m<=-0.98 |
| 59 | `tail_breadth_up_1m` | fraction of eligible stocks with resid_tod_tail_1m>=+0.98 |
| 60 | `tail_breadth_imbalance_1m` | tail_breadth_up_1m-tail_breadth_down_1m |
| 61 | `cs_resid_skew_1m` | cross-sectional skewness of e_1 |
| 62 | `cs_resid_kurt_1m` | cross-sectional excess kurtosis of e_1 |
| 63 | `median_stock_ret_1m` | cross-sectional median of r_1 |
| 64 | `benchmark_minus_median_1m` | m_1-median_stock_ret_1m |
| 65 | `market_tod_tail_1m` | TOD_TAIL(m_1) |
| 66 | `market_tod_tail_2m` | TOD_TAIL(m_2) |
| 67 | `market_vol_tod_tail_5m` | TOD_TAIL(sqrt(sum(m_1(t-k)^2,k=0..4))) |
| 68 | `lagged_market_response_gap_1m` | beta_d*m_1(t-1)-r_1(t) |
| 69 | `breadth_positive_1m` | fraction of eligible stocks with r_1>0 |
| 70 | `breadth_change_1m` | breadth_positive_1m(t)-breadth_positive_1m(t-1) |
| 71 | `factor_resid_1m` | u_1(t), residual from daily-frozen K=5 PCA common-factor model |
| 72 | `factor_resid_tod_tail_1m` | TOD_TAIL(u_1) |
| 73 | `factor_resid_2m` | u_2(t) using same daily-frozen factor model |
| 74 | `factor_resid_tod_tail_2m` | TOD_TAIL(u_2) |
| 75 | `factor_common_share_1m` | abs(r_1-u_1)/(abs(r_1)+eps), clipped at configured cap |
| 76 | `factor_resid_cs_rank_1m` | cross-sectional percentile rank of u_1 |
| 77 | `peer_basket_resid_1m` | sum_j w_ij*u_1(j,t) over daily-frozen peer set |
| 78 | `peer_gap_1m` | peer_basket_resid_1m-u_1(i,t) |
| 79 | `peer_gap_2m` | sum_j w_ij*u_2(j,t)-u_2(i,t) |
| 80 | `peer_gap_velocity_1m` | peer_gap_1m(t)-peer_gap_1m(t-1) |
| 81 | `peer_lead_pred_1m` | daily-frozen prior-only prediction of u_i(t+1) from peer residuals at t |
| 82 | `peer_lead_pred_2m` | daily-frozen prior-only prediction of u_i(t+2) from peer current/lagged residuals |
| 83 | `peer_breadth_sign_1m` | weighted fraction of peers whose residual sign agrees with peer_lead_pred_1m |
| 84 | `peer_shock_breadth_1m` | weighted fraction of peers in their own 2% residual tail in predicted direction |
| 85 | `peer_dispersion_1m` | weighted std of peer u_1 returns |
| 86 | `peer_move_concentration_1m` | HHI of abs(w_ij*u_1(j,t)) contributions |
| 87 | `peer_leader_count_1m` | count of peers contributing >=10% of abs(peer_lead_pred_1m) |
| 88 | `network_lead_strength` | daily-frozen aggregate outgoing lead strength of stock i |
| 89 | `network_follow_strength` | daily-frozen aggregate incoming follower sensitivity of stock i |
| 90 | `leader_liquidity_advantage` | weighted peer liquidity rank-stock liquidity_rank_20d |
| 91 | `dist_session_vwap` | C_t/cumulative_session_VWAP_t-1 |
| 92 | `dist_session_open` | C_t/session_open-1 |
| 93 | `dist_prior_close` | C_t/prior_session_close-1 |
| 94 | `dist_session_high` | C_t/session_high_to_t-1 |
| 95 | `dist_session_low` | C_t/session_low_to_t-1 |
| 96 | `session_range_expansion_tod` | current session-to-date range/prior-session median same-clock session range-1 |
| 97 | `same_minute_resid_lag1d` | e_1 at exact same clock minute on prior session |
| 98 | `same_minute_resid_mean5d` | mean e_1 at exact same clock minute over prior 5 sessions |
| 99 | `same_minute_resid_mean20d` | mean e_1 at exact same clock minute over prior 20 sessions |
| 100 | `same_minute_rank_mean20d` | mean residual cross-sectional rank at exact same clock minute over prior 20 sessions |
| 101 | `prevol_ratio_5_30` | sqrt(sum last-5 e_1^2)/(sqrt(sum prior-30 e_1^2)*sqrt(5/30)+eps) |
| 102 | `range_ratio_5_30` | sum last-5 one-minute ranges/scaled sum prior-30 ranges |
| 103 | `dollar_volume_ratio_5_30` | sum last-5 DV/scaled sum prior-30 DV |
| 104 | `squeeze_score_5_30` | -TOD_ROBZ(prevol_ratio_5_30) |
| 105 | `breakout_dist_high_5m` | C_t/max(C_(t-5:t-1))-1 |
| 106 | `breakout_dist_low_5m` | C_t/min(C_(t-5:t-1))-1 |
| 107 | `breakout_dist_high_15m` | C_t/max(C_(t-15:t-1))-1 |
| 108 | `breakout_dist_low_15m` | C_t/min(C_(t-15:t-1))-1 |
| 109 | `dist_orh_5m` | C_t/opening_range_high_first5m-1, valid after 09:35 |
| 110 | `dist_orl_5m` | C_t/opening_range_low_first5m-1, valid after 09:35 |
| 111 | `vwap_cross_age_signed` | sign(C_t-session_VWAP_t)*minutes since last session-VWAP side change |
| 112 | `breakout_age_signed_15m` | signed minutes since latest break of prior-15m high/low |
| 113 | `minutes_since_tail_event` | minutes since previous abs(resid_tod_tail_1m)>=0.98 event, capped at 30 |
| 114 | `post_shock_recovery_1m` | if prior minute was 2% tail shock: sign(-shock)*r_1(t), else NA |
| 115 | `post_shock_recovery_3m` | signed cumulative recovery since most recent <=3-minute-old 2% tail shock |
| 116 | `shock_cluster_score_15m` | sum I(tail shock)*exp(-age/5) over prior 15m |
| 117 | `vol_accel_1_5` | abs(e_1(t))/(sqrt(sum last-5 e_1^2)/sqrt(5)+eps) |

# 2. Targets — BUILD ALL 31

| # | Target | Basis | Definition |
|---:|---|---|---|
| 1 | `fwd_raw_1m` | raw | C_(t+1)/C_t - 1 |
| 2 | `fwd_raw_2m` | raw | C_(t+2)/C_t - 1 |
| 3 | `fwd_raw_3m` | raw | C_(t+3)/C_t - 1 |
| 4 | `fwd_raw_5m` | raw | C_(t+5)/C_t - 1 |
| 5 | `fwd_raw_10m` | raw | C_(t+10)/C_t - 1 |
| 6 | `fwd_raw_15m` | raw | C_(t+15)/C_t - 1 |
| 7 | `fwd_raw_30m` | raw | C_(t+30)/C_t - 1 |
| 8 | `fwd_beta_resid_1m` | beta-residual | fwd_raw_1 - beta_d*fwd_market_1 |
| 9 | `fwd_beta_resid_2m` | beta-residual | fwd_raw_2 - beta_d*fwd_market_2 |
| 10 | `fwd_beta_resid_3m` | beta-residual | fwd_raw_3 - beta_d*fwd_market_3 |
| 11 | `fwd_beta_resid_5m` | beta-residual | fwd_raw_5 - beta_d*fwd_market_5 |
| 12 | `fwd_beta_resid_10m` | beta-residual | fwd_raw_10 - beta_d*fwd_market_10 |
| 13 | `fwd_beta_resid_15m` | beta-residual | fwd_raw_15 - beta_d*fwd_market_15 |
| 14 | `fwd_beta_resid_30m` | beta-residual | fwd_raw_30 - beta_d*fwd_market_30 |
| 15 | `fwd_factor_resid_1m` | PCA-factor-residual | future 1-minute return residualized wit1 same daily-frozen PCA loadings |
| 16 | `fwd_factor_resid_2m` | PCA-factor-residual | future 2-minute return residualized wit2 same daily-frozen PCA loadings |
| 17 | `fwd_factor_resid_3m` | PCA-factor-residual | future 3-minute return residualized wit3 same daily-frozen PCA loadings |
| 18 | `fwd_factor_resid_5m` | PCA-factor-residual | future 5-minute return residualized wit5 same daily-frozen PCA loadings |
| 19 | `fwd_factor_resid_10m` | PCA-factor-residual | future 10-minute return residualized wit10 same daily-frozen PCA loadings |
| 20 | `fwd_factor_resid_15m` | PCA-factor-residual | future 15-minute return residualized wit15 same daily-frozen PCA loadings |
| 21 | `fwd_factor_resid_30m` | PCA-factor-residual | future 30-minute return residualized wit30 same daily-frozen PCA loadings |
| 22 | `step_raw_p1` | raw incremental | C_(t+1)/C_(t+0) - 1 |
| 23 | `step_raw_p2` | raw incremental | C_(t+2)/C_(t+1) - 1 |
| 24 | `step_raw_p3` | raw incremental | C_(t+3)/C_(t+2) - 1 |
| 25 | `step_raw_p4` | raw incremental | C_(t+4)/C_(t+3) - 1 |
| 26 | `step_raw_p5` | raw incremental | C_(t+5)/C_(t+4) - 1 |
| 27 | `step_factor_resid_p1` | factor-residual incremental | incremental minute +1 residual using frozen PCA model |
| 28 | `step_factor_resid_p2` | factor-residual incremental | incremental minute +2 residual using frozen PCA model |
| 29 | `step_factor_resid_p3` | factor-residual incremental | incremental minute +3 residual using frozen PCA model |
| 30 | `step_factor_resid_p4` | factor-residual incremental | incremental minute +4 residual using frozen PCA model |
| 31 | `step_factor_resid_p5` | factor-residual incremental | incremental minute +5 residual using frozen PCA model |

Primary research horizons: **1m, 2m, 3m, 5m, 10m**.

15m and 30m are still run; treat them as persistence/decay information rather than a reason to exclude a short-lived edge.

# 3. Exact dual pairs — RUN ALL 305

## Shock × path

1. `resid_tod_tail_1m` × `body_share_1m`
2. `resid_tod_tail_1m` × `dir_close_extreme_1m`
3. `resid_tod_tail_1m` × `last1_abs_share_3m`
4. `resid_tod_tail_1m` × `last1_abs_share_5m`
5. `resid_tod_tail_1m` × `path_eff_3m`
6. `resid_tod_tail_1m` × `path_eff_5m`
7. `resid_tod_tail_1m` × `same_sign_streak_1m`
8. `resid_tod_tail_1m` × `sign_switch_rate_5m`
9. `resid_tod_tail_1m` × `tail_event_count_5m`
10. `resid_tod_tail_1m` × `tail_event_count_15m`
## Shock × liquidity/impact

11. `resid_tod_tail_1m` × `range_tod_tail_1m`
12. `resid_tod_tail_1m` × `volume_tod_tail_1m`
13. `resid_tod_tail_1m` × `dollar_volume_tod_tail_1m`
14. `resid_tod_tail_1m` × `trade_count_tod_tail_1m`
15. `resid_tod_tail_1m` × `avg_trade_size_tod_tail_1m`
16. `resid_tod_tail_1m` × `dollar_per_trade_tod_tail_1m`
17. `resid_tod_tail_1m` × `impact_tod_tail_1m`
18. `resid_tod_tail_1m` × `range_per_dollar_1m`
19. `resid_tod_tail_1m` × `effort_result_1m`
20. `resid_tod_tail_1m` × `volume_return_mismatch_1m`
21. `resid_tod_tail_1m` × `trade_intensity_mismatch_1m`
22. `resid_tod_tail_1m` × `prevol_tod_tail_30m`
23. `resid_tod_tail_1m` × `liquidity_rank_20d`
24. `resid_tod_tail_1m` × `idio_share_1m`
## Shock × market/cross-section

25. `resid_tod_tail_1m` × `resid_dispersion_tod_tail_1m`
26. `resid_tod_tail_1m` × `tail_breadth_down_1m`
27. `resid_tod_tail_1m` × `tail_breadth_up_1m`
28. `resid_tod_tail_1m` × `tail_breadth_imbalance_1m`
29. `resid_tod_tail_1m` × `market_tod_tail_1m`
30. `resid_tod_tail_1m` × `market_vol_tod_tail_5m`
31. `resid_tod_tail_1m` × `breadth_positive_1m`
32. `resid_tod_tail_1m` × `breadth_change_1m`
33. `resid_tod_tail_1m` × `factor_common_share_1m`
34. `resid_tod_tail_1m` × `resid_cs_rank_1m`
35. `resid_tod_tail_1m` × `resid_rank_velocity_1m`
36. `resid_tod_tail_1m` × `factor_resid_cs_rank_1m`
## Shock × peer state

37. `resid_tod_tail_1m` × `peer_gap_1m`
38. `resid_tod_tail_1m` × `peer_gap_2m`
39. `resid_tod_tail_1m` × `peer_lead_pred_1m`
40. `resid_tod_tail_1m` × `peer_lead_pred_2m`
41. `resid_tod_tail_1m` × `peer_breadth_sign_1m`
42. `resid_tod_tail_1m` × `peer_shock_breadth_1m`
43. `resid_tod_tail_1m` × `peer_dispersion_1m`
44. `resid_tod_tail_1m` × `peer_move_concentration_1m`
45. `resid_tod_tail_1m` × `leader_liquidity_advantage`
46. `resid_tod_tail_1m` × `network_follow_strength`
## Shock × path

47. `factor_resid_tod_tail_1m` × `body_share_1m`
48. `factor_resid_tod_tail_1m` × `dir_close_extreme_1m`
49. `factor_resid_tod_tail_1m` × `last1_abs_share_3m`
50. `factor_resid_tod_tail_1m` × `last1_abs_share_5m`
51. `factor_resid_tod_tail_1m` × `path_eff_3m`
52. `factor_resid_tod_tail_1m` × `path_eff_5m`
53. `factor_resid_tod_tail_1m` × `same_sign_streak_1m`
54. `factor_resid_tod_tail_1m` × `sign_switch_rate_5m`
55. `factor_resid_tod_tail_1m` × `tail_event_count_5m`
56. `factor_resid_tod_tail_1m` × `tail_event_count_15m`
## Shock × liquidity/impact

57. `factor_resid_tod_tail_1m` × `range_tod_tail_1m`
58. `factor_resid_tod_tail_1m` × `volume_tod_tail_1m`
59. `factor_resid_tod_tail_1m` × `dollar_volume_tod_tail_1m`
60. `factor_resid_tod_tail_1m` × `trade_count_tod_tail_1m`
61. `factor_resid_tod_tail_1m` × `avg_trade_size_tod_tail_1m`
62. `factor_resid_tod_tail_1m` × `dollar_per_trade_tod_tail_1m`
63. `factor_resid_tod_tail_1m` × `impact_tod_tail_1m`
64. `factor_resid_tod_tail_1m` × `range_per_dollar_1m`
65. `factor_resid_tod_tail_1m` × `effort_result_1m`
66. `factor_resid_tod_tail_1m` × `volume_return_mismatch_1m`
67. `factor_resid_tod_tail_1m` × `trade_intensity_mismatch_1m`
68. `factor_resid_tod_tail_1m` × `prevol_tod_tail_30m`
69. `factor_resid_tod_tail_1m` × `liquidity_rank_20d`
70. `factor_resid_tod_tail_1m` × `idio_share_1m`
## Shock × market/cross-section

71. `factor_resid_tod_tail_1m` × `resid_dispersion_tod_tail_1m`
72. `factor_resid_tod_tail_1m` × `tail_breadth_down_1m`
73. `factor_resid_tod_tail_1m` × `tail_breadth_up_1m`
74. `factor_resid_tod_tail_1m` × `tail_breadth_imbalance_1m`
75. `factor_resid_tod_tail_1m` × `market_tod_tail_1m`
76. `factor_resid_tod_tail_1m` × `market_vol_tod_tail_5m`
77. `factor_resid_tod_tail_1m` × `breadth_positive_1m`
78. `factor_resid_tod_tail_1m` × `breadth_change_1m`
79. `factor_resid_tod_tail_1m` × `factor_common_share_1m`
80. `factor_resid_tod_tail_1m` × `resid_cs_rank_1m`
81. `factor_resid_tod_tail_1m` × `resid_rank_velocity_1m`
82. `factor_resid_tod_tail_1m` × `factor_resid_cs_rank_1m`
## Shock × peer state

83. `factor_resid_tod_tail_1m` × `peer_gap_1m`
84. `factor_resid_tod_tail_1m` × `peer_gap_2m`
85. `factor_resid_tod_tail_1m` × `peer_lead_pred_1m`
86. `factor_resid_tod_tail_1m` × `peer_lead_pred_2m`
87. `factor_resid_tod_tail_1m` × `peer_breadth_sign_1m`
88. `factor_resid_tod_tail_1m` × `peer_shock_breadth_1m`
89. `factor_resid_tod_tail_1m` × `peer_dispersion_1m`
90. `factor_resid_tod_tail_1m` × `peer_move_concentration_1m`
91. `factor_resid_tod_tail_1m` × `leader_liquidity_advantage`
92. `factor_resid_tod_tail_1m` × `network_follow_strength`
## Shock × path

93. `resid_prevol_norm_1m` × `body_share_1m`
94. `resid_prevol_norm_1m` × `dir_close_extreme_1m`
95. `resid_prevol_norm_1m` × `last1_abs_share_3m`
96. `resid_prevol_norm_1m` × `last1_abs_share_5m`
97. `resid_prevol_norm_1m` × `path_eff_3m`
98. `resid_prevol_norm_1m` × `path_eff_5m`
99. `resid_prevol_norm_1m` × `same_sign_streak_1m`
100. `resid_prevol_norm_1m` × `sign_switch_rate_5m`
101. `resid_prevol_norm_1m` × `tail_event_count_5m`
102. `resid_prevol_norm_1m` × `tail_event_count_15m`
## Shock × liquidity/impact

103. `resid_prevol_norm_1m` × `range_tod_tail_1m`
104. `resid_prevol_norm_1m` × `volume_tod_tail_1m`
105. `resid_prevol_norm_1m` × `dollar_volume_tod_tail_1m`
106. `resid_prevol_norm_1m` × `trade_count_tod_tail_1m`
107. `resid_prevol_norm_1m` × `avg_trade_size_tod_tail_1m`
108. `resid_prevol_norm_1m` × `dollar_per_trade_tod_tail_1m`
109. `resid_prevol_norm_1m` × `impact_tod_tail_1m`
110. `resid_prevol_norm_1m` × `range_per_dollar_1m`
111. `resid_prevol_norm_1m` × `effort_result_1m`
112. `resid_prevol_norm_1m` × `volume_return_mismatch_1m`
113. `resid_prevol_norm_1m` × `trade_intensity_mismatch_1m`
114. `resid_prevol_norm_1m` × `prevol_tod_tail_30m`
115. `resid_prevol_norm_1m` × `liquidity_rank_20d`
116. `resid_prevol_norm_1m` × `idio_share_1m`
## Shock × market/cross-section

117. `resid_prevol_norm_1m` × `resid_dispersion_tod_tail_1m`
118. `resid_prevol_norm_1m` × `tail_breadth_down_1m`
119. `resid_prevol_norm_1m` × `tail_breadth_up_1m`
120. `resid_prevol_norm_1m` × `tail_breadth_imbalance_1m`
121. `resid_prevol_norm_1m` × `market_tod_tail_1m`
122. `resid_prevol_norm_1m` × `market_vol_tod_tail_5m`
123. `resid_prevol_norm_1m` × `breadth_positive_1m`
124. `resid_prevol_norm_1m` × `breadth_change_1m`
125. `resid_prevol_norm_1m` × `factor_common_share_1m`
126. `resid_prevol_norm_1m` × `resid_cs_rank_1m`
127. `resid_prevol_norm_1m` × `resid_rank_velocity_1m`
128. `resid_prevol_norm_1m` × `factor_resid_cs_rank_1m`
## Shock × peer state

129. `resid_prevol_norm_1m` × `peer_gap_1m`
130. `resid_prevol_norm_1m` × `peer_gap_2m`
131. `resid_prevol_norm_1m` × `peer_lead_pred_1m`
132. `resid_prevol_norm_1m` × `peer_lead_pred_2m`
133. `resid_prevol_norm_1m` × `peer_breadth_sign_1m`
134. `resid_prevol_norm_1m` × `peer_shock_breadth_1m`
135. `resid_prevol_norm_1m` × `peer_dispersion_1m`
136. `resid_prevol_norm_1m` × `peer_move_concentration_1m`
137. `resid_prevol_norm_1m` × `leader_liquidity_advantage`
138. `resid_prevol_norm_1m` × `network_follow_strength`
## Shock × path

139. `shock_excess_1pct` × `body_share_1m`
140. `shock_excess_1pct` × `dir_close_extreme_1m`
141. `shock_excess_1pct` × `last1_abs_share_3m`
142. `shock_excess_1pct` × `last1_abs_share_5m`
143. `shock_excess_1pct` × `path_eff_3m`
144. `shock_excess_1pct` × `path_eff_5m`
145. `shock_excess_1pct` × `same_sign_streak_1m`
146. `shock_excess_1pct` × `sign_switch_rate_5m`
147. `shock_excess_1pct` × `tail_event_count_5m`
148. `shock_excess_1pct` × `tail_event_count_15m`
## Shock × liquidity/impact

149. `shock_excess_1pct` × `range_tod_tail_1m`
150. `shock_excess_1pct` × `volume_tod_tail_1m`
151. `shock_excess_1pct` × `dollar_volume_tod_tail_1m`
152. `shock_excess_1pct` × `trade_count_tod_tail_1m`
153. `shock_excess_1pct` × `avg_trade_size_tod_tail_1m`
154. `shock_excess_1pct` × `dollar_per_trade_tod_tail_1m`
155. `shock_excess_1pct` × `impact_tod_tail_1m`
156. `shock_excess_1pct` × `range_per_dollar_1m`
157. `shock_excess_1pct` × `effort_result_1m`
158. `shock_excess_1pct` × `volume_return_mismatch_1m`
159. `shock_excess_1pct` × `trade_intensity_mismatch_1m`
160. `shock_excess_1pct` × `prevol_tod_tail_30m`
161. `shock_excess_1pct` × `liquidity_rank_20d`
162. `shock_excess_1pct` × `idio_share_1m`
## Shock × market/cross-section

163. `shock_excess_1pct` × `resid_dispersion_tod_tail_1m`
164. `shock_excess_1pct` × `tail_breadth_down_1m`
165. `shock_excess_1pct` × `tail_breadth_up_1m`
166. `shock_excess_1pct` × `tail_breadth_imbalance_1m`
167. `shock_excess_1pct` × `market_tod_tail_1m`
168. `shock_excess_1pct` × `market_vol_tod_tail_5m`
169. `shock_excess_1pct` × `breadth_positive_1m`
170. `shock_excess_1pct` × `breadth_change_1m`
171. `shock_excess_1pct` × `factor_common_share_1m`
172. `shock_excess_1pct` × `resid_cs_rank_1m`
173. `shock_excess_1pct` × `resid_rank_velocity_1m`
174. `shock_excess_1pct` × `factor_resid_cs_rank_1m`
## Shock × peer state

175. `shock_excess_1pct` × `peer_gap_1m`
176. `shock_excess_1pct` × `peer_gap_2m`
177. `shock_excess_1pct` × `peer_lead_pred_1m`
178. `shock_excess_1pct` × `peer_lead_pred_2m`
179. `shock_excess_1pct` × `peer_breadth_sign_1m`
180. `shock_excess_1pct` × `peer_shock_breadth_1m`
181. `shock_excess_1pct` × `peer_dispersion_1m`
182. `shock_excess_1pct` × `peer_move_concentration_1m`
183. `shock_excess_1pct` × `leader_liquidity_advantage`
184. `shock_excess_1pct` × `network_follow_strength`
## Pressure / absorption

185. `signed_dollar_pressure_1m` × `resid_tod_tail_1m`
186. `signed_volume_pressure_1m` × `resid_tod_tail_1m`
187. `vwap_pressure_1m` × `resid_tod_tail_1m`
188. `wick_skew_pressure_1m` × `resid_tod_tail_1m`
189. `pressure_return_divergence_1m` × `impact_tod_tail_1m`
190. `pressure_return_divergence_1m` × `liquidity_rank_20d`
191. `absorption_score_1m` × `resid_tod_tail_1m`
192. `absorption_score_1m` × `impact_tod_tail_1m`
193. `absorption_score_1m` × `peer_gap_1m`
194. `effort_result_1m` × `clv_signed_1m`
195. `effort_result_1m` × `vwap_close_location_1m`
196. `volume_return_mismatch_1m` × `dir_close_extreme_1m`
197. `trade_intensity_mismatch_1m` × `dir_close_extreme_1m`
198. `upper_rejection_pressure_1m` × `resid_tod_tail_1m`
199. `lower_rejection_pressure_1m` × `resid_tod_tail_1m`
200. `vwap_close_location_1m` × `dollar_volume_tod_tail_1m`
201. `vwap_bar_location_1m` × `clv_signed_1m`
202. `impact_per_dollar_1m` × `prevol_tod_tail_30m`
## Cross-sectional dislocation

203. `resid_cs_rank_1m` × `resid_rank_velocity_1m`
204. `resid_cs_rank_1m` × `resid_rank_accel_1m`
205. `resid_cs_rank_1m` × `resid_dispersion_tod_tail_1m`
206. `resid_cs_rank_1m` × `tail_breadth_imbalance_1m`
207. `resid_cs_rank_1m` × `liquidity_rank_20d`
208. `resid_rank_velocity_1m` × `volume_tod_tail_1m`
209. `resid_rank_velocity_1m` × `peer_lead_pred_1m`
210. `resid_rank_accel_1m` × `path_eff_3m`
211. `resid_cs_rank_2m` × `resid_cs_rank_1m`
212. `resid_cs_rank_5m` × `resid_cs_rank_1m`
213. `factor_resid_cs_rank_1m` × `resid_cs_rank_1m`
214. `factor_resid_cs_rank_1m` × `resid_dispersion_tod_tail_1m`
215. `tail_breadth_imbalance_1m` × `market_tod_tail_1m`
216. `benchmark_minus_median_1m` × `breadth_positive_1m`
217. `cs_resid_skew_1m` × `resid_dispersion_tod_tail_1m`
218. `cs_resid_kurt_1m` × `resid_dispersion_tod_tail_1m`
## Market / factor

219. `market_tod_tail_1m` × `resid_cs_rank_1m`
220. `market_tod_tail_1m` × `resid_rank_velocity_1m`
221. `market_tod_tail_1m` × `lagged_market_response_gap_1m`
222. `market_tod_tail_1m` × `market_vol_tod_tail_5m`
223. `market_tod_tail_1m` × `breadth_positive_1m`
224. `market_tod_tail_2m` × `factor_resid_tod_tail_1m`
225. `lagged_market_response_gap_1m` × `liquidity_rank_20d`
226. `lagged_market_response_gap_1m` × `peer_lead_pred_1m`
227. `factor_resid_tod_tail_2m` × `path_eff_3m`
228. `breadth_change_1m` × `market_tod_tail_1m`
229. `benchmark_minus_median_1m` × `resid_dispersion_tod_tail_1m`
## Peer / lead-lag

230. `peer_lead_pred_1m` × `peer_breadth_sign_1m`
231. `peer_lead_pred_1m` × `peer_shock_breadth_1m`
232. `peer_lead_pred_1m` × `peer_dispersion_1m`
233. `peer_lead_pred_1m` × `peer_move_concentration_1m`
234. `peer_lead_pred_1m` × `peer_leader_count_1m`
235. `peer_lead_pred_1m` × `leader_liquidity_advantage`
236. `peer_lead_pred_1m` × `network_follow_strength`
237. `peer_lead_pred_1m` × `factor_resid_1m`
238. `peer_lead_pred_1m` × `factor_resid_cs_rank_1m`
239. `peer_lead_pred_2m` × `peer_breadth_sign_1m`
240. `peer_gap_1m` × `peer_breadth_sign_1m`
241. `peer_gap_1m` × `peer_shock_breadth_1m`
242. `peer_gap_1m` × `peer_dispersion_1m`
243. `peer_gap_1m` × `peer_move_concentration_1m`
244. `peer_gap_1m` × `leader_liquidity_advantage`
245. `peer_gap_1m` × `resid_rank_velocity_1m`
246. `peer_gap_2m` × `peer_lead_pred_1m`
247. `peer_gap_velocity_1m` × `peer_breadth_sign_1m`
248. `peer_gap_velocity_1m` × `resid_cs_rank_1m`
249. `network_follow_strength` × `liquidity_rank_20d`
250. `network_lead_strength` × `liquidity_rank_20d`
## Session / same-clock

251. `dist_session_vwap` × `volume_tod_tail_1m`
252. `dist_session_vwap` × `resid_tod_tail_1m`
253. `dist_session_vwap` × `vwap_cross_age_signed`
254. `dist_session_open` × `market_tod_tail_1m`
255. `dist_prior_close` × `resid_tod_tail_1m`
256. `dist_session_high` × `volume_tod_tail_1m`
257. `dist_session_low` × `volume_tod_tail_1m`
258. `session_range_expansion_tod` × `resid_tod_tail_1m`
259. `same_minute_resid_lag1d` × `same_minute_resid_mean20d`
260. `same_minute_resid_mean5d` × `resid_cs_rank_1m`
261. `same_minute_resid_mean20d` × `resid_cs_rank_1m`
262. `same_minute_rank_mean20d` × `resid_rank_velocity_1m`
263. `same_minute_resid_mean20d` × `market_tod_tail_1m`
264. `same_minute_resid_mean20d` × `prevol_tod_tail_30m`
## Compression / breakout

265. `squeeze_score_5_30` × `breakout_dist_high_5m`
266. `squeeze_score_5_30` × `breakout_dist_low_5m`
267. `squeeze_score_5_30` × `breakout_dist_high_15m`
268. `squeeze_score_5_30` × `breakout_dist_low_15m`
269. `squeeze_score_5_30` × `volume_tod_tail_1m`
270. `prevol_ratio_5_30` × `path_eff_5m`
271. `range_ratio_5_30` × `volume_tod_tail_1m`
272. `dollar_volume_ratio_5_30` × `breakout_dist_high_15m`
273. `dollar_volume_ratio_5_30` × `breakout_dist_low_15m`
274. `breakout_dist_high_5m` × `dir_close_extreme_1m`
275. `breakout_dist_low_5m` × `dir_close_extreme_1m`
276. `breakout_dist_high_15m` × `peer_lead_pred_1m`
277. `breakout_dist_low_15m` × `peer_lead_pred_1m`
278. `dist_orh_5m` × `volume_tod_tail_1m`
279. `dist_orl_5m` × `volume_tod_tail_1m`
280. `breakout_age_signed_15m` × `path_eff_5m`
## Event memory

281. `vol_accel_1_5` × `resid_tod_tail_1m`
282. `vol_accel_1_5` × `impact_tod_tail_1m`
283. `minutes_since_tail_event` × `resid_tod_tail_1m`
284. `shock_cluster_score_15m` × `resid_tod_tail_1m`
285. `shock_cluster_score_15m` × `peer_shock_breadth_1m`
286. `tail_event_count_15m` × `resid_dispersion_tod_tail_1m`
287. `sign_switch_rate_5m` × `absorption_score_1m`
288. `post_shock_recovery_1m` × `liquidity_rank_20d`
289. `post_shock_recovery_1m` × `impact_tod_tail_1m`
290. `post_shock_recovery_3m` × `peer_gap_1m`
## Fast vs slow residual state

291. `resid_tod_tail_1m` × `resid_tod_tail_5m`
292. `resid_tod_tail_2m` × `resid_tod_tail_5m`
293. `resid_tod_tail_1m` × `resid_tod_tail_2m`
## Fast vs slow factor residual

294. `factor_resid_tod_tail_1m` × `factor_resid_tod_tail_2m`
## Shock acceleration

295. `shock_accel_1m` × `resid_tod_tail_5m`
## Peer propagation

296. `peer_lead_pred_1m` × `peer_gap_velocity_1m`
297. `peer_lead_pred_2m` × `peer_gap_1m`
## Periodic × peer

298. `same_minute_resid_mean20d` × `peer_lead_pred_1m`
## Periodic × factor residual

299. `same_minute_resid_mean20d` × `factor_resid_tod_tail_1m`
## Compression × peer impulse

300. `squeeze_score_5_30` × `peer_lead_pred_1m`
## Compression × shock

301. `squeeze_score_5_30` × `resid_tod_tail_1m`
## VWAP state × shock

302. `vwap_cross_age_signed` × `resid_tod_tail_1m`
## VWAP state × peer gap

303. `dist_session_vwap` × `peer_gap_1m`
## Structural liquidity × transient impact

304. `liquidity_rank_20d` × `impact_tod_tail_1m`
## Structural liquidity × trade size

305. `liquidity_rank_20d` × `dollar_per_trade_tod_tail_1m`

# 4. Tail surfaces — RUN ALL

For each of the following first-leg variables:

```text
resid_tod_tail_1m
factor_resid_tod_tail_1m
resid_prevol_norm_1m
shock_excess_1pct
peer_gap_1m
peer_lead_pred_1m
```

run both lower and upper empirical tails:

```text
0.10%
0.25%
0.50%
1.00%
2.00%
5.00%
```

For dual surfaces, second-leg binning:

```text
5 bins
10 bins
```

Run both. Do not promote or reject solely from one resolution.

# 5. Output

Persist the full results; do not hard-gate away strange but potentially valuable subsets.

At minimum output:

```text
feature_registry.parquet
target_registry.parquet
single_results.parquet
dual_results.parquet
tail_results.parquet
candidate_summary.parquet
candidate_event_paths.parquet
```

Each result must preserve:

```text
feature / pair
target
bin or tail definition
direction
observations
unique episodes
unique symbols
mean bps
median bps
win rate
dispersion / standard error / t-stat equivalent
month breakdown
symbol breakdown
1m / 2m / 3m / 5m / 10m path
raw vs beta-residual vs PCA-factor-residual result
```

# 6. Run sequence

```text
1. Enable 1-minute decision grid.
2. Build all 117 listed features.
3. Build all 31 listed targets.
4. Run all 117 singles.
5. Run all 305 exact dual pairs.
6. Run all specified tail surfaces.
7. Preserve all results for research.
```

Do not add an execution model to this run.

After discovery, separately test any candidate at:

```text
-1, 0, 1, 2, 3, 4, 5 bps
```

and only then use quote replay to test whether the assumed entries/exits are achievable.