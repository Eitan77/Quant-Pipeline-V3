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


def _torch_rankdata_columns(values, valid, torch):
    """Average-tie ranks for a bounded batch of independently masked columns."""
    rows, columns = values.shape
    masked = torch.where(valid, values, torch.inf)
    order = torch.argsort(masked, dim=0, stable=True)
    ordered = torch.gather(values, 0, order)
    ordered_valid = torch.gather(valid, 0, order)
    starts = ordered_valid.clone()
    if rows > 1:
        starts[1:] &= ordered[1:] != ordered[:-1]
    groups = torch.cumsum(starts.to(torch.int64), dim=0) - 1
    offsets = torch.arange(columns, device=values.device, dtype=torch.int64)[None, :] * rows
    flat_groups = groups + offsets
    positions = torch.arange(1, rows + 1, device=values.device, dtype=torch.float64)[:, None].expand(-1, columns)
    sums = torch.zeros(rows * columns, device=values.device, dtype=torch.float64)
    sizes = torch.zeros_like(sums)
    selected = ordered_valid
    sums.scatter_add_(0, flat_groups[selected], positions[selected])
    sizes.scatter_add_(0, flat_groups[selected], torch.ones_like(positions[selected]))
    ranked_ordered = torch.zeros_like(positions)
    ranked_ordered[selected] = (sums / sizes.clamp_min(1))[flat_groups[selected]]
    ranked = torch.zeros_like(ranked_ordered)
    ranked.scatter_(0, order, ranked_ordered)
    counts = valid.sum(dim=0).to(torch.float64)
    centered = torch.where(valid, ranked - ranked.sum(dim=0) / counts.clamp_min(1), 0.0)
    return centered, ordered, counts


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
    """Exact CUDA singles using bounded target tiles and batched reductions."""
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
    free_bytes,_ = torch.cuda.mem_get_info(device)
    bytes_per_target=max(1,len(target_array))*96
    target_batch=max(1,min(len(target_ids),8,int((free_bytes*.30)//bytes_per_target)))
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
            for target_start in range(0,len(target_ids),target_batch):
                target_end=min(target_start+target_batch,len(target_ids)); y=target_tensor[:,target_start:target_end]
                valid=finite_x[:,None]&torch.isfinite(y); width=target_end-target_start
                x_columns=x[:,None].expand(-1,width)
                xr,ordered_x,n=_torch_rankdata_columns(x_columns,valid,torch)
                yr,_,_=_torch_rankdata_columns(y,valid,torch)
                denominator=torch.sqrt(xr.square().sum(0)*yr.square().sum(0))
                ic=torch.where((n>=3)&(denominator>0),(xr*yr).sum(0)/denominator,nan)
                positions=(n.clamp_min(1)-1)*.1
                lower=positions.floor().to(torch.int64); upper=torch.minimum(lower+1,(n.clamp_min(1)-1).to(torch.int64))
                columns=torch.arange(width,device=device)
                weight=positions-lower
                low=ordered_x[lower,columns]*(1-weight)+ordered_x[upper,columns]*weight
                positions=(n.clamp_min(1)-1)*.9
                lower=positions.floor().to(torch.int64); upper=torch.minimum(lower+1,(n.clamp_min(1)-1).to(torch.int64))
                weight=positions-lower
                high=ordered_x[lower,columns]*(1-weight)+ordered_x[upper,columns]*weight
                low_mask=valid&(x_columns<=low); high_mask=valid&(x_columns>=high)
                low_n=low_mask.sum(0).clamp_min(1); high_n=high_mask.sum(0).clamp_min(1)
                spread=torch.where(n>=20,(torch.where(high_mask,y,0).sum(0)/high_n-
                                           torch.where(low_mask,y,0).sum(0)/low_n),nan)
                if signals is None:
                    position=high_mask.to(torch.float64)-low_mask.to(torch.float64)
                else:
                    position=signals[:,1,None].to(torch.float64).expand(-1,width)*valid
                values=torch.where(valid,position*y.to(torch.float64),0.0); safe_n=n.clamp_min(1)
                effect=values.sum(0)/safe_n; active_n=(position!=0).sum(0).to(torch.float64)
                if cluster_tensor is not None:
                    index=cluster_tensor[:,None].expand(-1,width)
                    cluster_sums=torch.zeros((total_clusters,width),dtype=torch.float64,device=device)
                    cluster_counts=torch.zeros_like(cluster_sums)
                    cluster_sums.scatter_add_(0,index,values)
                    cluster_counts.scatter_add_(0,index,valid.to(torch.float64))
                    nonempty=cluster_counts>0; cluster_count=nonempty.sum(0).to(torch.float64)
                    centered=cluster_sums-cluster_counts*effect
                    correction=cluster_count/torch.clamp(cluster_count-1,min=1)
                    variance=correction*centered.square().sum(0)/(safe_n*safe_n)
                    se=torch.sqrt(torch.clamp(variance,min=0)); statistic=torch.where(se>0,effect/se,nan)
                    contributions=cluster_sums.abs(); total=contributions.sum(0)
                    share=torch.where(total>0,contributions.max(0).values/total,nan)
                    if signals is not None:
                        neighbor_low=torch.where(valid,signals[:,0,None].to(torch.float64)*y,0.0).sum(0)/safe_n
                        neighbor_high=torch.where(valid,signals[:,2,None].to(torch.float64)*y,0.0).sum(0)/safe_n
                    else: neighbor_low=neighbor_high=torch.full_like(effect,float("nan"))
                else:
                    effect=se=statistic=share=torch.full_like(effect,float("nan"))
                    cluster_count=torch.zeros_like(effect); neighbor_low=neighbor_high=torch.full_like(effect,float("nan"))
                packed=torch.stack((n,ic,spread,effect,se,statistic,cluster_count,active_n,share,neighbor_low,neighbor_high),dim=1).cpu().numpy()
                for offset,target_id in enumerate(target_ids[target_start:target_end]):
                    nv,icv,spreadv,effectv,sev,statv,cc,activev,sharev,nlow,nhigh=packed[offset]
                    row={"feature_id":feature_id,"target_id":target_id,"n_obs":int(nv),"rank_ic":icv,
                         "top_bottom_spread":spreadv,"signal_policy":"decision_cross_section" if signals is not None else "descriptive_full_sample"}
                    if cluster_tensor is not None:
                        neighbors=[nlow,nhigh]; aligned=[abs(v)/abs(effectv) for v in neighbors if np.isfinite(v) and effectv and np.sign(v)==np.sign(effectv)]
                        row.update(candidate_effect=effectv,cluster_se=sev,test_statistic=statv,
                                   p_value=float(2*norm.sf(abs(statv))) if np.isfinite(statv) else np.nan,
                                   cluster_count=int(cc),cell_min_count=int(activev),outlier_cluster_share=sharev,
                                   neighbor_effect_retention=float(np.median(aligned)) if aligned else 0.,
                                   plateau_area=1+sum(v>=.5 for v in aligned),robustness_status="MEASURED" if signals is not None else "NOT_MEASURED")
                    rows.append(row)
            del x, signals
    torch.cuda.synchronize(device)
    return pd.DataFrame(rows)
