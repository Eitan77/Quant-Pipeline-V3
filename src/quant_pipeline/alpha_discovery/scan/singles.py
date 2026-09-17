"""Bounded single-feature reductions with exact pairwise rank-mask semantics."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from scipy.stats import norm
from ..candidates import single_positions
from .inference import clustered_mean_test


def single_backend(prefer_cuda: bool = False, device_name: str = "cuda:0") -> str:
    if prefer_cuda:
        try:
            import torch
            if torch.cuda.is_available(): return f"torch:{torch.device(device_name)}"
        except (ImportError, RuntimeError):
            pass
    return "numpy:cpu"


def scan_singles(features, targets, feature_ids, target_ids, clusters=None, decision_ts=None,
                 *, prefer_cuda: bool = False, device_name: str = "cuda:0"):
    if features.shape != (len(targets), len(feature_ids)) or targets.shape[1] != len(target_ids):
        raise ValueError("Single-scan dimensions disagree")
    if single_backend(prefer_cuda, device_name).startswith("torch:cuda"):
        return _scan_singles_cuda(features, targets, feature_ids, target_ids, clusters, decision_ts, device_name)
    return _scan_singles_cpu(features, targets, feature_ids, target_ids, clusters, decision_ts)


def _scan_singles_cpu(features, targets, feature_ids, target_ids, clusters=None, decision_ts=None):
    rows=[]
    for fi, feature_id in enumerate(feature_ids):
        x=np.asarray(features[:,fi],float); finite=np.isfinite(x)
        # A feature-only signal is reusable across targets and must not depend on missing labels.
        signals = {tail:single_positions(x,1,tail,decision_ts=decision_ts) for tail in (.05,.1,.2)} if decision_ts is not None else None
        cache={}
        for ti,target_id in enumerate(target_ids):
            y=np.asarray(targets[:,ti],float); valid=finite & np.isfinite(y); n=int(valid.sum())
            key=np.packbits(valid).tobytes()
            if key not in cache:
                xv=x[valid]; ranks=rankdata(xv); centered=ranks-ranks.mean() if n else ranks
                low,high=np.quantile(xv,[.1,.9]) if n>=20 else (np.nan,np.nan)
                cache[key]=(centered,float(np.dot(centered,centered)),xv<=low,xv>=high)
                # Retain at most four masks per feature, avoiding unbounded mask/rank storage.
                if len(cache)>4: cache.pop(next(iter(cache)))
            a,ss,low_mask,high_mask=cache[key]
            yr=y[valid]; b=rankdata(yr); b-=b.mean() if n else 0
            denom=np.sqrt(ss*np.dot(b,b)); ic=float(np.dot(a,b)/denom) if n>=3 and denom else np.nan
            position=signals[.1] if signals is not None else np.zeros(len(x))
            if signals is None:
                position[valid]=high_mask.astype(float)-low_mask.astype(float)
            active=valid & (position!=0)
            spread=float(yr[high_mask].mean()-yr[low_mask].mean()) if n>=20 else np.nan
            row={"feature_id":feature_id,"target_id":target_id,"n_obs":n,"rank_ic":ic,"top_bottom_spread":spread,
                 "signal_policy":"decision_cross_section" if signals is not None else "descriptive_full_sample"}
            if clusters is not None:
                values=np.where(valid,position*y,np.nan)
                test=clustered_mean_test(values,np.asarray(clusters))
                effect=test["mean"]
                neighbors=[]
                if signals is not None:
                    for tail in (.05,.2): neighbors.append(float(np.nanmean(np.where(valid,signals[tail]*y,np.nan))))
                aligned=[abs(v)/abs(effect) for v in neighbors if np.isfinite(v) and effect and np.sign(v)==np.sign(effect)]
                contributions=pd.Series(np.where(valid,position*y,0)).groupby(np.asarray(clusters),sort=False).sum().abs()
                share=float(contributions.max()/contributions.sum()) if contributions.sum()>0 else np.nan
                row.update(candidate_effect=effect,cluster_se=test["cluster_se"],test_statistic=test["t"],p_value=test["p"],
                           cluster_count=test["clusters"],cell_min_count=int(active.sum()),outlier_cluster_share=share,
                           neighbor_effect_retention=float(np.median(aligned)) if aligned else 0.,
                           plateau_area=1+sum(v>=.5 for v in aligned),robustness_status="MEASURED" if signals is not None else "NOT_MEASURED")
            rows.append(row)
    return pd.DataFrame(rows)


def _torch_rankdata(values, torch):
    """Exact average-tie ranks on CUDA, matching scipy.stats.rankdata."""
    count = values.numel()
    if not count: return values
    order = torch.argsort(values, stable=True)
    ordered = values[order]
    starts = torch.ones(count, dtype=torch.bool, device=values.device)
    if count > 1: starts[1:] = ordered[1:] != ordered[:-1]
    groups = torch.cumsum(starts.to(torch.int64), 0) - 1
    positions = torch.arange(1, count + 1, dtype=torch.float64, device=values.device)
    # A count-sized workspace avoids synchronizing CUDA merely to read the
    # number of tie groups.  Unused tail entries are harmless.
    sums = torch.zeros(count, dtype=torch.float64, device=values.device)
    sizes = torch.zeros(count, dtype=torch.float64, device=values.device)
    sums.scatter_add_(0, groups, positions)
    sizes.scatter_add_(0, groups, torch.ones_like(positions))
    ranked = torch.empty(count, dtype=torch.float64, device=values.device)
    ranked[order] = (sums / sizes)[groups]
    return ranked


def _sorted_quantile(ordered, q: float):
    position = (ordered.numel() - 1) * q
    lower = int(position); upper = min(lower + 1, ordered.numel() - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _cuda_cross_sectional_signals(x, decision_codes, within_group, group_count, max_group_size, torch):
    """Build the governed 5/10/20% decision-time tails with one segmented CUDA sort."""
    finite = torch.isfinite(x)
    grouped = torch.full((group_count, max_group_size), torch.inf, dtype=x.dtype, device=x.device)
    grouped[decision_codes[finite], within_group[finite]] = x[finite]
    ordered = torch.sort(grouped, dim=1).values
    counts = torch.isfinite(grouped).sum(dim=1)
    groups = torch.arange(group_count, device=x.device)
    usable = counts >= 20
    outputs = []
    for tail in (.05, .1, .2):
        thresholds = []
        for q in (tail, 1.0 - tail):
            position = (counts.clamp_min(1).to(torch.float64) - 1) * q
            lower = position.floor().to(torch.int64).clamp_max(max_group_size - 1)
            upper = (lower + 1).clamp_max(max_group_size - 1)
            weight = (position - lower).to(x.dtype)
            thresholds.append(ordered[groups, lower] * (1 - weight) + ordered[groups, upper] * weight)
        low, high = thresholds
        valid = finite & usable[decision_codes] & (low[decision_codes] < high[decision_codes])
        signal = torch.zeros_like(x)
        signal[valid & (x >= high[decision_codes])] = 1
        signal[valid & (x <= low[decision_codes])] = -1
        outputs.append(signal)
    return torch.stack(outputs, dim=1)


def _scan_singles_cuda(features, targets, feature_ids, target_ids, clusters, decision_ts, device_name):
    """Exact CUDA singles with one host synchronization per feature.

    Kernels still use bounded feature/target workspaces, but scalar metrics stay
    on device until every target for the feature is complete.  This removes the
    repeated ``Tensor.item()`` barriers that previously left the GPU idle.
    """
    import torch
    device = torch.device(device_name)
    feature_array = np.asarray(features)
    target_array = np.asarray(targets)
    target_tensor = torch.tensor(target_array, dtype=torch.float32, device=device)
    if clusters is not None:
        _, compact_clusters = np.unique(np.asarray(clusters), return_inverse=True)
        cluster_tensor = torch.as_tensor(compact_clusters, dtype=torch.int64, device=device)
        total_clusters = int(compact_clusters.max()) + 1 if len(compact_clusters) else 0
    else:
        cluster_tensor = None; total_clusters = 0
    if decision_ts is not None:
        host_decision_codes, _ = pd.factorize(np.asarray(decision_ts), sort=False)
        if len(host_decision_codes) and np.any(host_decision_codes[1:] < host_decision_codes[:-1]):
            raise ValueError("CUDA singles requires decision-time-sorted observations")
        host_counts = np.bincount(host_decision_codes)
        host_offsets = np.cumsum(host_counts) - host_counts
        host_within = np.arange(len(host_decision_codes), dtype=np.int64) - host_offsets[host_decision_codes]
        decision_codes = torch.as_tensor(host_decision_codes, dtype=torch.int64, device=device)
        within_group = torch.as_tensor(host_within, dtype=torch.int64, device=device)
        group_count = len(host_counts); max_group_size = int(host_counts.max()) if len(host_counts) else 0
    else:
        decision_codes = within_group = None; group_count = max_group_size = 0
    rows = []; nan = torch.tensor(float("nan"), dtype=torch.float64, device=device)
    with torch.no_grad():
        for fi, feature_id in enumerate(feature_ids):
            host_x = np.asarray(feature_array[:, fi], dtype=np.float32)
            x = torch.as_tensor(host_x, dtype=torch.float32, device=device)
            finite_x = torch.isfinite(x)
            if decision_ts is not None:
                signals = _cuda_cross_sectional_signals(
                    x, decision_codes, within_group, group_count, max_group_size, torch
                )
            else:
                signals = None
            device_rows = []
            for ti, target_id in enumerate(target_ids):
                y = target_tensor[:, ti]
                valid = finite_x & torch.isfinite(y)
                xv = x[valid].to(torch.float64); yv = y[valid].to(torch.float64)
                n = xv.numel()
                if n:
                    pass
                else:
                    xv = torch.empty(0, dtype=torch.float64, device=device)
                    yv = torch.empty(0, dtype=torch.float64, device=device)
                if n >= 3:
                    xr = _torch_rankdata(xv, torch); yr = _torch_rankdata(yv, torch)
                    xr -= xr.mean(); yr -= yr.mean()
                    denominator = torch.sqrt(torch.dot(xr, xr) * torch.dot(yr, yr))
                    ic = torch.where(denominator > 0, torch.dot(xr, yr) / denominator, nan)
                else:
                    ic = nan
                if n >= 20:
                    ordered_x = torch.sort(xv).values
                    low = _sorted_quantile(ordered_x, .1); high = _sorted_quantile(ordered_x, .9)
                    low_mask = xv <= low; high_mask = xv >= high
                    spread = yv[high_mask].mean() - yv[low_mask].mean()
                else:
                    low_mask = high_mask = None; spread = nan
                if signals is None:
                    position = torch.zeros(n, dtype=torch.float64, device=device)
                    if n >= 20: position = high_mask.to(torch.float64) - low_mask.to(torch.float64)
                else:
                    position = signals[:, 1][valid].to(torch.float64)
                values = position * yv
                active = position != 0
                if cluster_tensor is not None:
                    if n >= 3:
                        codes = cluster_tensor[valid]
                        counts = torch.bincount(codes, minlength=total_clusters).to(torch.float64)
                        cluster_sums = torch.zeros(total_clusters, dtype=torch.float64, device=device)
                        cluster_sums.scatter_add_(0, codes, values)
                        mean = values.mean()
                        nonempty = counts > 0; cluster_count = nonempty.sum().to(torch.float64)
                        centered_sums = cluster_sums[nonempty] - counts[nonempty] * mean
                        correction = cluster_count / torch.clamp(cluster_count - 1, min=1)
                        variance = correction * torch.dot(centered_sums, centered_sums) / (n * n)
                        se = torch.sqrt(torch.clamp(variance, min=0)); effect = mean
                        statistic = torch.where(se > 0, effect / se, nan)
                        contributions = cluster_sums.abs(); contribution_sum = contributions.sum()
                        share = torch.where(contribution_sum > 0, contributions.max() / contribution_sum, nan)
                    else:
                        effect = se = statistic = share = nan
                        cluster_count = torch.zeros((), dtype=torch.float64, device=device)
                    neighbors = []
                    if signals is not None and n:
                        for index in (0, 2):
                            neighbors.append((signals[:, index][valid].to(torch.float64) * yv).mean())
                    while len(neighbors) < 2: neighbors.append(nan)
                else:
                    effect = se = statistic = share = nan
                    cluster_count = torch.zeros((), dtype=torch.float64, device=device)
                    neighbors = [nan, nan]
                device_rows.append(torch.stack((
                    torch.tensor(float(n), dtype=torch.float64, device=device), ic, spread,
                    effect, se, statistic, cluster_count, active.sum().to(torch.float64), share,
                    neighbors[0], neighbors[1],
                )))
            packed = torch.stack(device_rows).cpu().numpy()
            for ti, target_id in enumerate(target_ids):
                n,ic,spread,effect,se,statistic,cluster_count,active_n,share,neighbor_low,neighbor_high = packed[ti]
                row = {"feature_id":feature_id,"target_id":target_id,"n_obs":int(n),"rank_ic":ic,
                       "top_bottom_spread":spread,
                       "signal_policy":"decision_cross_section" if signals is not None else "descriptive_full_sample"}
                if cluster_tensor is not None:
                    neighbors=[neighbor_low,neighbor_high]
                    aligned=[abs(value)/abs(effect) for value in neighbors
                             if np.isfinite(value) and effect and np.sign(value)==np.sign(effect)]
                    p_value=float(2*norm.sf(abs(statistic))) if np.isfinite(statistic) else np.nan
                    row.update(candidate_effect=effect,cluster_se=se,test_statistic=statistic,p_value=p_value,
                               cluster_count=int(cluster_count),cell_min_count=int(active_n),outlier_cluster_share=share,
                               neighbor_effect_retention=float(np.median(aligned)) if aligned else 0.,
                               plateau_area=1+sum(value>=.5 for value in aligned),
                               robustness_status="MEASURED" if signals is not None else "NOT_MEASURED")
                rows.append(row)
            del x, signals
    torch.cuda.synchronize(device)
    return pd.DataFrame(rows)
