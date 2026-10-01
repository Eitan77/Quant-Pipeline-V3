# Next intraday run: new features and targeted pairs

**Run objective:** produce new intraday discovery analysis data: causal features, targeted single/dual surfaces, forward-return and path labels, sample support, chronology and specialist breakdowns. These are additions for a pipeline run, not an executable strategy or claims of demonstrated alpha. Use the entire May 2025–April 2026 discovery year; later data stays sealed. This document does not launch a run.

**Scope:** bar/PIT-derived analysis only. Quote acquisition, limit-order replay, portfolio simulation and strategy selection are separate later work and are not included in this run.

This list prioritizes new event/state formulas over another sweep of ordinary momentum and mean reversion. “New” means a formula/state absent from the current canonical concept registry, checked against `src/quant_pipeline/alpha_discovery/registry.py`. Related old concepts and timing extensions are identified below; this is not a claim that no related idea has ever appeared in a research script.

## 1. What to prioritize

1. **Shock acceptance versus exhaustion:** was the move retained, did participation persist, and did subsequent volatility compress?
2. **Absorption and price impact:** substantial activity with little progress, asymmetric upside/downside impact, and divergence between price progress and volume direction.
3. **Breakout acceptance versus traps:** preserve the crossed level and measure subsequent dwell, retests, and participation rather than recomputing a moving boundary.
4. **Peer catch-up versus isolated moves:** explicit sector residuals and a prior-only lag model, rather than an unfitted “peer” proxy.
5. **Event-anchored VWAP and bar-based volume profiles:** where the recent volume was priced relative to the current price and the initiating event.
6. **Opening participation and trapped gap volume:** distinguish an opening burst that gains acceptance from one whose participants are subsequently underwater.

Start with the 28 formulas and 30 pairs below. Do not pair every feature with every other feature or enable arbitrary formula generation. Bidirectional discovery is allowed; the mechanism descriptions are hypotheses, not forced trade directions.

## 2. Common definitions — exact and causal

- `t` is a **completed one-minute RTH bar**, used only after its recorded availability timestamp. Every event, baseline, group member and feature input must already be available when the signal is evaluated.
- `O,H,L,C,V,Q` are open, high, low, close, shares and actual provider bar VWAP. Prices used together must have the same verified adjustment basis. Execution references use raw historical prices. Missing actual VWAP disables VWAP-dependent features; do not silently substitute typical price.
- `r_j = ln(C_j/C_(j-1))`; `u_j = C_j/C_(j-1)-1`. Returns do not bridge sessions or missing minutes. `W_n(t) = {t-n+1,...,t}` denotes exactly `n` consecutive completed minutes; return windows require the preceding close too.
- `R_n(t) = sum_(j in W_n(t)) r_j`. All listed window lengths are minutes. Overnight gaps are separate inputs.
- `D_j = Q_j*V_j` on the **raw price/share basis**, for actual dollar turnover. Adjusted-price dollar volume is prohibited.
- `TR_j = max(H_j-L_j, abs(H_j-C_(j-1)), abs(L_j-C_(j-1)))`; for the first session bar use `H_j-L_j`. `A_t^- = mean_(W_30(t-1)) TR_j` is the prior intraday ATR, excluding the current bar. It needs 30 complete same-session bars.
- `A_day^-` is mean daily true range across the preceding 20 completed sessions, on the current comparable feature-price basis. It is the scale for opening features; no current full-day range is used.
- `mu_j = median(r_(j-30),...,r_(j-1))`; `s_j = 1.4826*median(abs(r_k-mu_j))` over those same 30 prior minutes. `shock_j = 1{abs(r_j-mu_j)>3*s_j AND s_j>0 AND r_j!=0}`. Require complete history. This threshold is fixed, not optimized over the year.
- `B_V(j)` is median volume at the **same session minute** across the preceding 20 completed sessions; minimum 15 valid sessions. `v_j = V_j/B_V(j)`. Historical 25th/90th quantiles below use the same prior sessions and minute, with linear interpolation at index `(N-1)*p` in the sorted sample.
- `Slope(y,w) = sum[w_j*(j-jbar_w)*(y_j-ybar_w)] / sum[w_j*(j-jbar_w)^2]`, with weighted means and chronologically increasing integer `j`. `Slope(y,1)` is ordinary OLS slope.
- A zero/invalid denominator produces unavailable, not an arbitrary epsilon-generated extreme. Missing features do not invalidate unrelated feature families. Explicitly store event-present flags and eligible counts.

**Shock event:** for maximum age `a`, `e` is the latest shock in `[t-a,t-1]`, same session; `d=sign(r_e)` and `J={e+1,...,t}`. Excluding the current bar ensures there is an observed aftermath. No shock means unavailable, not zero. Events may not cross missing history.

**Breakout event:** choose `k=20` or `60`. At candidate event `e`, freeze `B_e=max(H_(e-k),...,H_(e-1))` if `C_e>B_e`, or `B_e=min(L_(e-k),...,L_(e-1))` if `C_e<B_e`; direction `d=+1` or `-1` respectively. Use the latest such close-crossing in `[t-30,t-1]`, with `A_e^-` and the level frozen at that event. Do not move the boundary after the breakout. `J={e+1,...,t}`. Preserve `e`, direction and age in the ledger.

**Sector inputs:** use verified PIT sector membership, excluding the subject stock. `g_(i,j)` is the equal-weight mean peer one-minute log return; require at least 10 eligible peers and at least 80% of that day's eligible peer set with available observations. Freeze daily eligible membership using prior-known data; record changing bar coverage. Do not silently replace sectors with the whole universe. If PIT sector history is unavailable, defer N15–N19 rather than invent it.

`m_j` is SPY's same-clock log return. `beta_i^- = Cov(r_i,m)/Var(m)` from paired RTH minutes in the preceding 20 completed sessions, with at least 3,000 observations across 15 sessions; freeze each day. `epsilon_(i,j)=r_(i,j)-beta_i^-*m_j`. This is a descriptive residual, not a free executable hedge.

## 3. New formulas to add

### A. Shock aftermath — do not repeat unconditional one-minute reversal

These features condition on the observed aftermath of an earlier shock. They are a new state description; they do not reopen the rejected rule “immediately fade every large one-minute move.”

| ID | Feature | Exact formula at t | Versions | Mechanism |
|---|---|---|---|---|
| N01 | Shock retention | `d*ln(C_t/C_(e-1))/abs(r_e)` | `a=10,30` | Below 1 means part of the initiating shock was retraced; above 1 means extension. Negative means reversal through its origin. |
| N02 | Post-shock volume direction | `d*sum_J[V_j*sign(r_j)]/sum_J V_j` | `a=10,30` | Whether subsequent bar volume supports or opposes the original direction. This is a bar proxy, not observed aggressor flow. |
| N03 | Post-shock volatility contraction | `sqrt(mean_J r_j^2)/s_e` | `a=10,30` | Quiet acceptance versus a continuing unstable price path. |
| N04 | Shock age | `t-e` | `a=10,30` | Separates immediate reaction from a settled state; context only, not an independent alpha claim. |

### B. Absorption, impact and participation

| ID | Feature | Exact formula at t | Versions | Mechanism |
|---|---|---|---|---|
| N05 | Directional price-impact asymmetry | Let `U=sum max(r_j,0)`, `D=sum max(-r_j,0)`, `DU=sum D_j*1{r_j>0}`, `DD=sum D_j*1{r_j<0}` over `W_n`; `ln((U/DU)/(D/DD))`. Require all four quantities positive. | `n=5,15,30` | Which direction moves price farther per traded dollar. Signed-volume classification is a proxy. |
| N06 | High-volume, low-progress share | `sum_W[V_j*1{V_j>q90_V(j) AND abs(r_j)<q25_absr(j)}]/sum_W V_j` | `n=5,15` | Activity being absorbed without much close-to-close progress. Quantiles are prior-only same-minute baselines. |
| N07 | Price/volume direction divergence | `sum_W r_j/sum_W abs(r_j) - sum_W[V_j*sign(r_j)]/sum_W V_j` | `n=5,15` | Price progress disagrees with volume-weighted bar direction. New composite of familiar parents, not independent new information by itself. |
| N08 | Participation leads price | `Corr({r_j},{ln(v_(j-1))})` for paired `j in W_n` | `n=15,30` | Prior-minute participation is associated with subsequent direction; differs from contemporaneous return/volume correlation. |
| N09 | Consecutive range overlap | Mean over `W_n` of `max(0,min(H_j,H_(j-1))-max(L_j,L_(j-1))) / (max(H_j,H_(j-1))-min(L_j,L_(j-1)))` | `n=5,15` | Repeated trading in the same range: churn/absorption rather than directional progress. |
| N10 | One-minute VWAP dislocation | `(C_t-Q_t)/A_t^-` | Single minute | Where a minute closes relative to where its actual volume traded. Timing extension of broad VWAP-distance ideas. |

### C. Persistent levels and breakout traps

| ID | Feature | Exact formula at t | Versions | Mechanism |
|---|---|---|---|---|
| N11 | Frozen breakout-level acceptance | `d*(C_t-B_e)/A_e^-` | `k=20,60` | Positive is acceptance outside the crossed level; negative is failure back through it. |
| N12 | Post-breakout dwell | `mean_J 1{d*(C_j-B_e)>0}` | `k=20,60` | Fraction of the observed aftermath that stayed on the breakout side. |
| N13 | Retest distance | `min_J dist(B_e,[L_j,H_j])/A_e^-`, where `dist=0` if the level lies in the interval, otherwise the smaller endpoint distance | `k=20,60` | A retest has actually occurred versus a runaway move. Excludes the breakout bar itself. |
| N14 | Post-breakout participation | `mean_J v_j` | `k=20,60` | Acceptance supported by abnormal participation versus a thin break. |

These are related to old breakout/reclaim concepts, but preserve the original event and boundary. Static distance from a continually rolling high is not an acceptable substitute.

### D. Genuine peers and lagged response

| ID | Feature | Exact formula at t | Versions | Mechanism |
|---|---|---|---|---|
| N15 | Sector-relative move | `sum_(W_n) (r_(i,j)-g_(i,j))` | `n=5,15` | Isolated stock movement versus sector-wide movement. Sector baskets are new; inactive statistical-peer/PCA concepts are not evidence that this was tested. |
| N16 | Sector-residual acceleration | `N15_5(t)-N15_5(t-5)` | Adjacent 5-minute blocks | Whether the isolated move is accelerating or already fading. |
| N17 | Prior-only peer catch-up forecast | Daily OLS on prior 20 sessions: `epsilon_(i,j)=a+gamma*g_(i,j-1)+phi*epsilon_(i,j-1)+delta*m_(j-1)+error_j`. Feature is `a+gamma*g_(i,t)+phi*epsilon_(i,t)+delta*m_t`. | One-minute lag; one frozen daily model | Predictable next-minute residual response to a peer impulse. No full-year coefficient fitting. Same 3,000-observation/15-session minimum; singular models unavailable. |
| N18 | Peer agreement with isolated move | `sign(N15_n(t)) * (2*mean_peers 1{R_n(peer,t)>0}-1)` | `n=5,15` | Peer participation confirms or contradicts the stock's relative move. |
| N19 | Sector breadth impulse versus market | `[B_sector(t)-B_sector(t-5)]-[B_universe(t)-B_universe(t-5)]`; each `B` is fraction with positive trailing 5-minute return | 5-minute difference | Rotation into/out of a sector beyond general market breadth. Sector-wide context, not hundreds of independent observations. |

### E. Event anchors and where volume was priced

Define `AV_t(e)=sum_(j=e..t) Q_j*V_j / sum_(j=e..t) V_j` using the shock event from N01, maximum age 30. Use consistently adjusted `Q` and `V` so this is a comparable feature price; raw basis is retained separately for execution.

| ID | Feature | Exact formula at t | Versions | Mechanism |
|---|---|---|---|---|
| N20 | Shock-anchored VWAP acceptance | `d*(C_t-AV_t(e))/A_e^-` | `a=30` | Price relative to the volume cost proxy since the initiating shock. |
| N21 | Event-VWAP versus price slope | `d*[Slope(ln(C_j),1)-Slope(ln(AV_j(e)),1)]` over the last five completed anchored observations | `a=30`; require `t-e>=4` | Price runs ahead of or falls behind the event's volume-weighted path. |
| N22 | Bar-priced volume balance | `[sum_W V_j*1{Q_j<C_t}-sum_W V_j*1{Q_j>C_t}]/sum_W V_j` | `n=15,30` | Recent bar volume priced below versus above current price. This is not actual investor inventory. |
| N23 | Bar-profile high-volume-node distance | In `W_n`, set `qlo=min Q`, `qhi=max Q`, `w=(qhi-qlo)/5`; assign bar `j` to `b_j=min(4,floor((Q_j-qlo)/w))`; `S_b=sum V_j*1{b_j=b}`; choose smallest `b*` attaining max `S_b`. Feature `(C_t-[qlo+(b*+0.5)*w])/A_t^-`. | `n=15,30` | Distance from the most heavily represented recent price region. |
| N24 | Bar-profile price concentration | With the same five bins: `sum_(b=0..4) (S_b/sum_W V_j)^2` | `n=15,30` | Concentrated trading at one price region versus dispersed price discovery. |
| N28 | Volume-weighted trend disagreement | `[Slope(ln(C_j),V_j)-Slope(ln(C_j),1)] / Std({r_j:j in W_30(t-1)},ddof=1)` over price bars `W_n` | `n=15,30` | Large-volume bars imply a different price trend from the ordinary time-weighted trend. |

N23/N24 assign each bar's entire volume to its VWAP bin. Label these **bar-profile proxies**, not tick-level volume-at-price. Flat profiles with `qhi=qlo` are unavailable. They are different from concentration across time bars.

### F. Opening participation and trapped gaps

Let `P^-` be the previous official session close, `O_day` today's first RTH open, and `dg=sign(O_day-P^-)`. Require a nonzero gap and a verified comparable price basis. `VWAP_open(k)` uses only the first `k` completed minutes.

| ID | Feature | Exact formula at t | Versions | Mechanism |
|---|---|---|---|---|
| N25 | Opening burst concentration surprise | `f_today / median(f_prior20)`, where `f=V_firstminute/sum_first5 V_j` | Available after first 5 minutes; 15 valid prior sessions | Was the opening volume unusually concentrated in the first minute? This includes continuous trading and is not a measured auction imbalance. |
| N26 | Gap acceptance by opening VWAP | `dg*(VWAP_open(k)-O_day)/A_day^-` | `k=5,15`; available only after minute k | Opening participants moved the average traded price farther in the gap direction versus away from it. |
| N27 | Trapped opening-gap volume proxy | `-dg*1{dg*(C_t-P^-)<0} * [sum_first15 V_j*1{dg*(Q_j-P^-)>0}/sum_first15 V_j]` | After first 15 minutes | An opened gap has reversed through the prior close, leaving substantial opening bar volume on the other side. |

Opening snapshots N25/N26 remain fixed after becoming available; they do not acquire later information. N27's current-price condition can change causally during the session. Do not convert repeated snapshots into independent trade counts.

## 4. Existing leads to retain — distinguish promise from execution failure

Use fresh audited calculations, not invalid old EMA caches. Below are exact mathematical definitions for clean, full-window versions; version changed missing-history/zero-denominator semantics under new IDs instead of overwriting legacy evidence.

| ID | Existing feature and clean formula | Windows for this run | Why retain |
|---|---|---|---|
| R01 | Positive-jump fraction: `sum_W 1{abs(u_j-med_j)>3*MADscale_j AND u_j>0}/n`; `med_j=median(u_(j-n)..u_(j-1))`, `MADscale_j=1.4826*median(abs(u_k-med_j))` on that prior window | `n=10,30`; require every prior scale positive | Paired tail contexts had substantial gross surface differences; one had positive annual quote replay. |
| R02 | Negative-return mass: `sum_W max(-u_j,0)` | `n=5,15,30` | Informative descriptive parent in tail/selling-flow contexts; alone is not proven alpha. |
| R03 | Roll spread proxy: `2*sqrt(max(-Cov(deltaC_j,deltaC_(j-1)),0))/C_t`, sample covariance `ddof=1` over `n` valid adjacent difference pairs | `n=15,30`; requires `n+2` closes | Jump × Roll is the weak positive quote-tested lead. Proxy is not NBBO spread. |
| R04 | ATR-band extension: `(C_t-mean_W C_j)/mean_W TR_j` | `n=5,15,30` | Useful location parent; its old acceleration strategy lost quote diagnostics. Retain as control/partner, not as a survivor. |
| R05 | Half-window acceleration: `(C_t/C_(t-n/2)-1)-(C_(t-n/2)/C_(t-n)-1)` | `n=10,30` | New event/participation context may distinguish its mechanism; old unconditional pairing failed. |
| R06 | Trend slope t-stat: OLS `ln(C_j)=a+b*x_j+error_j` on `n+1` closes, `x` evenly spaced -1 to +1; `b/sqrt((SSE/(n-1))*[(X'X)^-1]_(b,b))` | `n=15,30` | Existing trend/VWAP disagreement was a descriptive lead, without validated strong execution. |
| R07 | Legacy VWAP drift: `Slope(Q_j,1)` over `W_n` | `n=15,30` | Retain the actual per-bar VWAP slope; do not relabel it as session-VWAP slope. |
| R08 | Momentum direction agreement: `sign(C_t/C_(t-f)-1)*sign(C_t/C_(t-s)-1)` | `(f,s)=(1,5),(5,30)` | Existing range-conditioned structure; discrete context, not a continuous strength rank. |

**Verified prior result:** jump × Roll, 240-minute short, ten slots: +5.54% funded discovery return at zero offset, 714 fills; only seven positive months and negative return after removing the five best days. That is a reason to preserve the mechanism for comparison, not to add filters until it becomes a “printer.” Below-average-price/acceleration and selling-flow probes lost at every requested price. Source: [prior research report](INTRADAY_CAUSAL_RESTART_20260930.md).

## 5. Exact targeted pairs for the next run

`ID_window` selects exactly that variant; event variants specify maximum age or breakout lookback. These 30 configurations are the initial pair list. Discovery may show either continuation or reversal, but must retain both parent marginals and neighboring cells.

| Pair | Feature A | Feature B | Question / rationale |
|---|---|---|---|
| P01 | N01_a10 | N02_a10 | Shock retained with participation versus unsupported retention. |
| P02 | N01_a30 | N03_a30 | Quiet acceptance versus volatile exhaustion. |
| P03 | N01_a30 | N04_a30 | Does the same retention state behave differently after it settles? |
| P04 | N20_a30 | N02_a30 | Event cost acceptance supported by directional activity. |
| P05 | N20_a30 | N21_a30 | Price extension from event VWAP versus divergence of the paths. |
| P06 | N05_15 | N06_15 | Impact asymmetry when unusually large activity makes little progress. |
| P07 | N05_15 | N07_15 | Directional impact and disagreement between price and volume. |
| P08 | N06_5 | N09_5 | Quiet high-volume absorption inside overlapping ranges. |
| P09 | N07_5 | N10 | Price/volume disagreement confirmed by the minute's VWAP close. |
| P10 | N08_30 | N15_5 | Participation-led movement that is genuinely stock-specific. |
| P11 | N11_k20 | N12_k20 | Frozen level strength versus time spent accepting that level. |
| P12 | N11_k20 | N14_k20 | Breakout acceptance with participation versus thin failure. |
| P13 | N11_k20 | N13_k20 | What happens after a real retest of the original level? |
| P14 | N12_k20 | N06_5 | Absorption following sustained breakout-side dwell. |
| P15 | N11_k60 | N14_k60 | Same mechanism at a broader pre-existing level; one declared scale neighbor. |
| P16 | N15_5 | N18_5 | Isolated move with supportive peers versus contradictory peers. |
| P17 | N16 | N18_5 | Accelerating sector-relative movement with peer confirmation. |
| P18 | N17 | N15_5 | Prior-only expected catch-up versus a stock already ahead/behind. |
| P19 | N15_15 | N19 | Stock-relative displacement during sector rotation. |
| P20 | N22_15 | N24_15 | Bar volume largely on one side of current price, concentrated at a price region. |
| P21 | N23_15 | N24_15 | Distance from a strong recent volume node versus a diffuse profile. |
| P22 | N23_30 | N05_15 | Volume-node displacement with asymmetric price impact. |
| P23 | N28_15 | N15_5 | Volume-weighted trend disagreement in an isolated stock move. |
| P24 | N25 | N26_k5 | Unusual opening burst followed by gap acceptance or rejection. |
| P25 | N27 | N05_15 | Trapped gap-volume proxy with impact favoring the reversal direction. |
| P26 | N26_k15 | N18_15 | Gap acceptance versus sector participation. |
| P27 | R01_30 | R03_30 | Recalculate the existing concept pair at one-minute timing; compare separately with its frozen historical rule. |
| P28 | R01_30 | N05_15 | Tail activity with actual directional-impact asymmetry, not just a spread proxy. |
| P29 | R02_15 | N06_5 | Selling pressure plus observed absorption rather than a blind falling-price fade. |
| P30 | R04_15 | N28_15 | Price extension whose ordinary trend disagrees with the volume-weighted trend. |

Do **not** require each single to be profitable before examining its listed pair. Include weak-single/strong-dual structures. Conversely, a visually attractive tiny cell cannot justify dozens of extra filters. Old R04 × R05 and R06 × R07 can be preserved as historical comparison surfaces without adding them to the new 30-pair search budget. Keep the old frozen five-minute jump × Roll policy and its results as an immutable comparison; clean one-minute recalculations are a new trial, not a reproduction of that policy.

## 6. Representations and analysis targets

**Decision grid:** every completed minute, with actual availability respected. Keep the legacy five-minute grid only as a reporting/thinning comparison, not another independent discovery campaign.

**Representations:** save raw values and one causal percentile view for each version. For stock-specific continuous features, `P=(average_cross_sectional_rank-0.5)/N` over eligible available stocks at that clock. For shared sector/market context, opening fixed snapshots and sparse event-age context, use the feature's empirical percentile against the preceding 20 completed sessions at the same minute: `(count(past<x)+0.5*count(past=x))/N`, minimum 15 observations. Do not cross-sectionally rank a market-wide constant or treat identical sector states as independent evidence. If sparse event history is insufficient, leave that percentile unavailable and retain raw diagnostics. R08 stays a discrete state. No added monotone copies, negated copies or complement features.

**Pair maps:** r3 for every listed pair; r5/r10 only for supported neighboring regions. Bin as `min(r-1,floor(r*P))`. Log all examined resolutions/regions as discovery trials. Event-present flags are eligibility context, not fitted thresholds.

**Return targets:** `h={1,2,5,10,15,30,60,120,240}` elapsed minutes plus EOD. At signal time save raw completed close `P_e=C_t^raw`; fixed-horizon reference exit is `P_x=C_(t+h)^raw`. EOD reference is the completed close one minute before the **official** session close. Only admit fixed-horizon observations whose exits fit within that boundary. Missing horizon bars are missing outcomes, never compressed row-index horizons or silently shortened holds.

For each horizon, store raw arithmetic `y=P_x/P_e-1` and descriptive benchmark excess `y-y_SPY` using matching clock/reference bars. This gives **20 primary labels**. Long reference return is `y`; short return on entry notional is `1-P_x/P_e`. Residual targets are deferred until their prior-only beta inputs pass the new audit. Beta/sector excess is not executable return without separately pricing hedge legs.

Also store signed MFE/MAE versus entry reference, first times to favorable/adverse 5/10/20bp barriers, and favorable-excursion giveback at exit. These are future **labels**, never features. A minute containing both barrier touches has unknown order until replayed with appropriate data. No profit-target/stop combination grid in initial discovery.

**Event/opportunity metadata:** preserve SID, session, decision/availability timestamps, event anchor and direction, age, exact target reference prices, feature/rank values and missingness. Report total eligible observations and independent state episodes separately. An episode starts on an observed transition from false to true and ends on an observed false state or session end; missing data is unknown, not proof of a reset. Preserve event IDs so repeated observations following one shock or breakout are identifiable. These are analysis observations, not order attempts or fills.

## 7. Required analysis outputs

For every listed single and pair, produce:

- Feature definitions, exact window/version IDs, input availability, valid counts and missing-data coverage.
- Single and dual surfaces by target, direction, resolution and state/region, with matched parent marginals, incremental interaction lift and neighboring-cell support.
- Counts, means, medians, positive-return fractions and return quantiles; total observations plus distinct sessions, SIDs and event episodes.
- All 12 discovery months, weekly summaries and chronological folds. These are within-year stability diagnostics, not sealed OOS tests.
- MFE/MAE, favorable/adverse barrier timing and giveback distributions, explicitly separated from causal feature inputs.
- Breadth and concentration of the descriptive effect across symbols, days, PIT sectors, prior-known liquidity groups and broad session-time buckets. Preserve both broad effects and local specialists; do not fit ticker whitelists.
- Raw and benchmark-excess effects and parent-relative contrasts. Preserve weak-single/strong-dual structures without requiring profitable parents first.
- Complete manifests linking feature version, pair definition, target timing, eligibility, surface files and underlying observations, so later strategy research can reconstruct a candidate without guessing.

Keep the full supported surface geometry. Do not reduce the output to one strategy score or only the best annual cell. Where a feature's PIT metadata or history is unavailable, record that limitation and exclude that feature version explicitly; do not substitute a different formula under the same ID.

**Initial addition budget:** 28 bar/event/peer formula IDs, eight retained formula IDs, 30 explicit pair configurations, one-minute decisions and 20 primary return labels. Only the window variants declared above belong to this plan; no automatic cross-product of every feature pair or formula. Exact quote execution and finite-capital strategy testing happen after these analysis data identify a defensible mechanism.
