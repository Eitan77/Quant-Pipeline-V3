from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd



def _cluster_segments(codes: np.ndarray):
    """Prepare contiguous reductions once per chunk, shared by targets/resolutions."""
    codes=np.asarray(codes,dtype=np.int64)
    if codes.ndim!=1 or (codes<0).any(): raise ValueError("Cluster codes must be nonnegative and one-dimensional")
    if not len(codes): return np.array([],dtype=np.int64),np.array([],dtype=np.int64),None
    order=None
    if np.any(codes[1:]<codes[:-1]):
        order=np.argsort(codes,kind="stable"); codes=codes[order]
    starts=np.r_[0,np.flatnonzero(codes[1:]!=codes[:-1])+1]
    return codes[starts],starts,order


def _cluster_reduce(contribution: np.ndarray, valid: np.ndarray, segments):
    groups,starts,order=segments
    if not len(starts):
        return np.empty((0,contribution.shape[1])),np.empty((0,contribution.shape[1]),dtype=np.int64)
    values=np.where(valid,contribution,0)
    if order is not None: values=values[order]; valid=valid[order]
    return np.add.reduceat(values,starts,axis=0),np.add.reduceat(valid,starts,axis=0,dtype=np.int64)


def _cluster_fold_map(codes: np.ndarray, folds: np.ndarray, groups: int):
    """First observed fold per group, exactly matching the original mapping."""
    codes=np.asarray(codes,dtype=np.int64); folds=np.asarray(folds,dtype=np.int16)
    if codes.shape!=folds.shape: raise ValueError("Cluster/fold codes must align")
    labels,starts,order=_cluster_segments(codes)
    first=starts if order is None else order[starts]
    output=np.full(groups,-1,dtype=np.int16); output[labels]=folds[first]
    return output


def _summarize_arrays(c: np.ndarray, s: np.ndarray, ss: np.ndarray, bins: int,
                      pairs: int, target_count: int) -> pd.DataFrame:
    cells=bins*bins; rows=pairs*target_count
    means=np.divide(s,c,out=np.full_like(s,np.nan),where=c>0)
    overall=np.divide(s.sum(1),c.sum(1),out=np.zeros(rows),where=c.sum(1)>0)
    c3=c.reshape(rows,bins,bins); s3=s.reshape(rows,bins,bins)
    ma=np.divide(s3.sum(2),c3.sum(2),out=np.zeros((rows,bins)),where=c3.sum(2)>0)
    mb=np.divide(s3.sum(1),c3.sum(1),out=np.zeros((rows,bins)),where=c3.sum(1)>0)
    inc=means.reshape(rows,bins,bins)-ma[:,:,None]-mb[:,None,:]+overall[:,None,None]
    flat_inc=inc.reshape(rows,cells); safe=np.where(np.isfinite(flat_inc),np.abs(flat_inc),-np.inf)
    selected=safe.argmax(1); effect=flat_inc[np.arange(rows),selected]
    retention=np.zeros(rows); plateau=np.ones(rows,dtype=np.int16)
    for index in range(rows):
        row,column=divmod(int(selected[index]),bins); peak=effect[index]
        neighbors=[(row+dr,column+dc) for dr,dc in ((-1,0),(1,0),(0,-1),(0,1)) if 0<=row+dr<bins and 0<=column+dc<bins]
        values=np.asarray([inc[index,r,c_] for r,c_ in neighbors],dtype=float)
        if len(values) and np.isfinite(peak) and peak!=0:
            aligned=values[np.sign(values)==np.sign(peak)]
            retention[index]=float(np.nanmedian(np.abs(aligned))/abs(peak)) if len(aligned) else 0.0
            plateau[index]+=int(np.sum((np.sign(values)==np.sign(peak))&(np.abs(values)>=.5*abs(peak))))
    variance=np.divide(ss-np.divide(np.square(s),c,out=np.zeros_like(s),where=c>0),np.maximum(c-1,1),out=np.full_like(s,np.nan),where=c>1)
    se=np.sqrt(variance[np.arange(rows),selected]/np.maximum(c[np.arange(rows),selected],1))
    best=np.max(np.where(c>0,means,-np.inf),axis=1); worst=np.min(np.where(c>0,means,np.inf),axis=1)
    best[~np.isfinite(best)]=np.nan; worst[~np.isfinite(worst)]=np.nan
    result=pd.DataFrame({"pair_index":np.repeat(np.arange(pairs),target_count),"target_index":np.tile(np.arange(target_count),pairs),
        "n_obs":c.sum(1),"selected_cell":selected.astype(np.int16),"selected_cell_effect":effect,"selected_cell_se":se,
        "max_abs_incremental_cell":np.max(safe,axis=1),"best_cell_effect":best,"worst_cell_effect":worst,
        "neighbor_effect_retention":retention,"plateau_area":plateau,
        "surface_interaction_energy":np.nansum(np.square(inc)*c3,axis=(1,2))/np.maximum(c.sum(1),1),"cell_min_count":c.min(1)})
    selected_n=c[np.arange(rows),selected]; selected_frequency=selected_n/np.maximum(c.sum(1),1)
    selected_state_return=means[np.arange(rows),selected]; selected_interaction_lift=flat_inc[np.arange(rows),selected]
    result["selected_n"]=selected_n; result["selected_frequency"]=selected_frequency
    result["selected_state_return"]=selected_state_return; result["selected_state_bps"]=selected_state_return*10_000.0
    result["selected_interaction_lift"]=selected_interaction_lift; result["selected_interaction_lift_bps"]=selected_interaction_lift*10_000.0
    result["weighted_state_contribution"]=selected_state_return*selected_frequency; result["weighted_state_contribution_bps"]=result["weighted_state_contribution"]*10_000.0
    result["weighted_interaction_contribution"]=selected_interaction_lift*selected_frequency; result["weighted_interaction_contribution_bps"]=result["weighted_interaction_contribution"]*10_000.0
    result["selected_direction"]=np.sign(selected_state_return).astype(np.int8); result["legacy_incremental_cell_effect"]=result["selected_cell_effect"]; result["selection_test_effect"]=np.nan
    return result


@dataclass
class DualTileScanner:
    bins: int = 3
    device_name: str = "cuda:0"
    prefer_cuda: bool = True
    memory_fraction: float = 0.80
    screening_dtype: str = "float32"

    def __post_init__(self) -> None:
        import torch
        self.torch = torch
        self.device = torch.device(self.device_name if self.prefer_cuda and torch.cuda.is_available() else "cpu")

    @property
    def backend(self) -> str: return f"torch:{self.device}"

    def estimate_peak_bytes(self, rows: int, pairs: int, targets: int = 1) -> int:
        cells = self.bins * self.bins
        work = 4 if self.screening_dtype == "float32" else 8
        # Device inputs, decoded int64 bins/cells, validity masks, bincount
        # indexes, selected float64 values, and allocator workspaces coexist at
        # peak.  Accounting for all of them prevents WDDM from silently
        # spilling an oversized CUDA tile into shared host memory.
        raw = rows * pairs * (2 + 24 + 3 + 16 + 16 + work) + rows * targets * work
        raw += pairs * targets * cells * 24
        return int(raw * 1.25)  # allocator/workspace headroom

    def recommended_shape(self, observations: int, targets: int = 1, minimum_pairs: int = 1,
                          maximum_pairs: int = 8192) -> tuple[int, int]:
        if self.device.type == "cuda":
            budget = int(self.torch.cuda.mem_get_info(self.device)[0] * self.memory_fraction)
        else:
            budget = 1 << 30
        rows, pairs = min(max(observations, 1), 1_000_000), maximum_pairs
        while self.estimate_peak_bytes(rows, pairs, targets) > budget and (rows > 4096 or pairs > minimum_pairs):
            estimate=self.estimate_peak_bytes(rows,pairs,targets)
            fitted=max(minimum_pairs,int(pairs*budget/max(estimate,1)*.95))
            if fitted < pairs: pairs=fitted
            else: rows=max(4096,rows//2)
        if self.estimate_peak_bytes(rows, pairs, targets) > budget: raise MemoryError("No safe dual scan tile fits configured memory")
        return min(rows, observations), pairs

    def recommended_pair_block(self, observations: int, minimum: int = 1, maximum: int = 8192) -> int:
        return self.recommended_shape(observations, minimum_pairs=minimum, maximum_pairs=maximum)[1]

    def scan(self, bins_a: np.ndarray, bins_b: np.ndarray, target: np.ndarray,
             valid_a: np.ndarray | None = None, valid_b: np.ndarray | None = None,
             row_chunk_size: int | None = None) -> pd.DataFrame:
        a_host, b_host, y_host = np.asarray(bins_a, np.int8), np.asarray(bins_b, np.int8), np.asarray(target)
        if a_host.shape != b_host.shape or a_host.ndim != 2 or a_host.shape[0] != len(y_host): raise ValueError("Dual tile dimensions disagree")
        chunk = row_chunk_size or self.recommended_shape(len(y_host), maximum_pairs=max(1, a_host.shape[1]))[0]
        def reader(start, end):
            va = None if valid_a is None else valid_a[start:end]
            vb = None if valid_b is None else valid_b[start:end]
            return a_host[start:end], b_host[start:end], y_host[start:end], va, vb
        return self.scan_reader(len(y_host), a_host.shape[1], reader, chunk, include_surfaces=True)

    def scan_reader(self, observations: int, pairs: int, reader, row_chunk_size: int | None = None,
                    include_surfaces: bool = False, cluster_codes: np.ndarray | None = None,
                    fold_codes: np.ndarray | None = None, target_count: int = 1) -> pd.DataFrame:
        """Scan bounded `(a, b, y, valid_a, valid_b)` slices supplied by reader."""
        cells, t = self.bins * self.bins, self.torch
        chunk = row_chunk_size or self.recommended_shape(observations, maximum_pairs=max(1, pairs))[0]
        work_dtype = t.float32 if self.screening_dtype == "float32" else t.float64
        if target_count < 1: raise ValueError("target_count must be positive")
        counts = t.zeros((pairs, target_count, cells), dtype=t.int64, device=self.device)
        sums = t.zeros_like(counts, dtype=t.float64); sumsq = t.zeros_like(sums)
        pair_numbers = t.arange(pairs, dtype=t.int64, device=self.device)[None, :]
        for start in range(0, observations, chunk):
            end = min(start + chunk, observations)
            a_host, b_host, y_host, valid_a, valid_b = reader(start, end)
            a = t.as_tensor(a_host, dtype=t.int64, device=self.device)
            b = t.as_tensor(b_host, dtype=t.int64, device=self.device)
            y = t.tensor(y_host, dtype=work_dtype, device=self.device)
            if y.ndim == 1: y = y[:, None]
            if y.shape[1] != target_count: raise ValueError("Reader target width disagrees with target_count")
            bin_valid = (a >= 0) & (a < self.bins) & (b >= 0) & (b < self.bins)
            if valid_a is not None: bin_valid &= t.as_tensor(valid_a, dtype=t.bool, device=self.device)
            if valid_b is not None: bin_valid &= t.as_tensor(valid_b, dtype=t.bool, device=self.device)
            cell_index = pair_numbers * cells + a * self.bins + b
            for target_index in range(target_count):
                valid = bin_valid & t.isfinite(y[:, target_index])[:, None]
                flat = cell_index[valid]
                selected = y[:, target_index, None].expand(-1, pairs)[valid].to(t.float64)
                local_count = t.bincount(flat, minlength=pairs * cells).reshape(pairs, cells)
                local_sum = t.zeros(pairs * cells, dtype=t.float64, device=self.device)
                local_sumsq = t.zeros_like(local_sum)
                local_sum.scatter_add_(0, flat, selected)
                local_sumsq.scatter_add_(0, flat, selected.square())
                counts[:, target_index, :].add_(local_count)
                sums[:, target_index, :].add_(local_sum.reshape(pairs, cells))
                sumsq[:, target_index, :].add_(local_sumsq.reshape(pairs, cells))
        c = counts.cpu().numpy().reshape(pairs * target_count, cells)
        s = sums.cpu().numpy().reshape(pairs * target_count, cells)
        ss = sumsq.cpu().numpy().reshape(pairs * target_count, cells)
        result_pairs = pairs * target_count
        means = np.divide(s, c, out=np.full_like(s, np.nan), where=c > 0)
        overall = np.divide(s.sum(1), c.sum(1), out=np.zeros(result_pairs), where=c.sum(1) > 0)
        c3, s3 = c.reshape(result_pairs, self.bins, self.bins), s.reshape(result_pairs, self.bins, self.bins)
        ma = np.divide(s3.sum(2), c3.sum(2), out=np.zeros((result_pairs, self.bins)), where=c3.sum(2) > 0)
        mb = np.divide(s3.sum(1), c3.sum(1), out=np.zeros((result_pairs, self.bins)), where=c3.sum(1) > 0)
        inc = means.reshape(result_pairs, self.bins, self.bins) - ma[:, :, None] - mb[:, None, :] + overall[:, None, None]
        flat_inc = inc.reshape(result_pairs, cells); safe = np.where(np.isfinite(flat_inc), np.abs(flat_inc), -np.inf)
        selected_cell = safe.argmax(1); selected_effect = flat_inc[np.arange(result_pairs), selected_cell]
        neighbor_retention = np.zeros(result_pairs); plateau_area = np.ones(result_pairs, dtype=np.int16)
        for pair in range(result_pairs):
            row, column = divmod(int(selected_cell[pair]), self.bins); peak = selected_effect[pair]
            neighbors = [(row + dr, column + dc) for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                         if 0 <= row + dr < self.bins and 0 <= column + dc < self.bins]
            values = np.asarray([inc[pair, r, c] for r, c in neighbors], dtype=float)
            if len(values) and np.isfinite(peak) and peak != 0:
                aligned = values[np.sign(values) == np.sign(peak)]
                neighbor_retention[pair] = float(np.nanmedian(np.abs(aligned)) / abs(peak)) if len(aligned) else 0.0
                plateau_area[pair] += int(np.sum((np.sign(values) == np.sign(peak)) & (np.abs(values) >= .5 * abs(peak))))
        variance = np.divide(ss - np.divide(np.square(s), c, out=np.zeros_like(s), where=c > 0), np.maximum(c - 1, 1), out=np.full_like(s, np.nan), where=c > 1)
        selected_se = np.sqrt(variance[np.arange(result_pairs), selected_cell] / np.maximum(c[np.arange(result_pairs), selected_cell], 1))
        best=np.max(np.where(c>0,means,-np.inf),axis=1); worst=np.min(np.where(c>0,means,np.inf),axis=1)
        best[~np.isfinite(best)]=np.nan; worst[~np.isfinite(worst)]=np.nan
        result = pd.DataFrame({"pair_index": np.repeat(np.arange(pairs), target_count),
            "target_index": np.tile(np.arange(target_count), pairs), "n_obs": c.sum(1), "selected_cell": selected_cell.astype(np.int16),
            "selected_cell_effect": selected_effect, "selected_cell_se": selected_se, "max_abs_incremental_cell": np.max(safe, axis=1),
            "best_cell_effect":best,"worst_cell_effect":worst,
            "neighbor_effect_retention": neighbor_retention, "plateau_area": plateau_area,
            "surface_interaction_energy": np.nansum(np.square(inc) * c3, axis=(1, 2)) / np.maximum(c.sum(1), 1), "cell_min_count": c.min(1)})
        selected_n=c[np.arange(result_pairs),selected_cell]; selected_frequency=selected_n/np.maximum(c.sum(1),1)
        selected_state_return=means[np.arange(result_pairs),selected_cell]
        result["selected_n"]=selected_n; result["selected_frequency"]=selected_frequency
        result["selected_state_return"]=selected_state_return; result["selected_state_bps"]=selected_state_return*10_000.0
        result["selected_interaction_lift"]=selected_effect; result["selected_interaction_lift_bps"]=selected_effect*10_000.0
        result["weighted_state_contribution"]=selected_state_return*selected_frequency; result["weighted_state_contribution_bps"]=result["weighted_state_contribution"]*10_000.0
        result["weighted_interaction_contribution"]=selected_effect*selected_frequency; result["weighted_interaction_contribution_bps"]=result["weighted_interaction_contribution"]*10_000.0
        result["selected_direction"]=np.sign(selected_state_return).astype(np.int8); result["legacy_incremental_cell_effect"]=result["selected_cell_effect"]; result["selection_test_effect"]=np.nan
        if cluster_codes is not None:
            from scipy.stats import norm
            codes = np.asarray(cluster_codes, dtype=np.int64); groups = int(codes.max()) + 1 if len(codes) else 0
            cluster_sum = np.zeros((result_pairs, groups), dtype=np.float64); cluster_count = np.zeros((result_pairs, groups), dtype=np.int64)
            frequency = c[np.arange(result_pairs), selected_cell] / np.maximum(c.sum(1), 1)
            for start in range(0, observations, chunk):
                end = min(start + chunk, observations); ah, bh, yh, _, _ = reader(start, end)
                segments=_cluster_segments(codes[start:end])
                cells_now = ah.astype(np.int16) * self.bins + bh.astype(np.int16)
                yh = np.asarray(yh); yh = yh[:, None] if yh.ndim == 1 else yh
                bin_valid = (ah >= 0) & (bh >= 0)
                for target_index in range(target_count):
                    rows = np.arange(pairs) * target_count + target_index
                    valid = np.isfinite(yh[:, target_index])[:, None] & bin_valid
                    contribution = ((cells_now == selected_cell[rows][None, :]) - frequency[rows][None, :]) * yh[:, target_index, None]
                    sums,counts=_cluster_reduce(contribution,valid,segments)
                    index=np.ix_(rows,segments[0])
                    cluster_sum[index]+=sums.T; cluster_count[index]+=counts.T
            n = np.maximum(cluster_count.sum(1), 1); mean = cluster_sum.sum(1) / n
            residual = cluster_sum - mean[:, None] * cluster_count
            correction = groups / max(groups - 1, 1); se = np.sqrt(correction * np.square(residual).sum(1)) / n
            z = np.divide(mean, se, out=np.full(result_pairs, np.nan), where=se > 0)
            raw_p = 2 * norm.sf(np.abs(z)); adjusted_for_cell_selection = np.minimum(1.0, raw_p * cells)
            result["candidate_effect"] = mean; result["selection_test_effect"]=mean; result["cluster_se"] = se; result["test_statistic"] = z
            result["p_value"] = adjusted_for_cell_selection; result["cluster_count"] = groups
            result["outlier_cluster_share"] = np.max(np.abs(cluster_sum), axis=1) / np.maximum(np.sum(np.abs(cluster_sum), axis=1), 1e-15)
            if fold_codes is not None:
                group_fold=_cluster_fold_map(codes,fold_codes,groups)
                fold_effects = []
                for fold in sorted(set(group_fold[group_fold >= 0].tolist())):
                    mask = group_fold == fold; denominator = np.maximum(cluster_count[:, mask].sum(1), 1)
                    fold_effects.append(cluster_sum[:, mask].sum(1) / denominator)
                stacked = np.column_stack(fold_effects) if fold_effects else np.empty((result_pairs, 0))
                result["fold_effects"] = list(stacked)
                result["fold_sign_consistency"] = np.abs(np.sign(stacked).mean(1)) if stacked.shape[1] else np.nan
                result["fold_magnitude_ratio"] = np.nanmin(np.abs(stacked), axis=1) / np.maximum(np.nanmax(np.abs(stacked), axis=1), 1e-15) if stacked.shape[1] else np.nan
        if include_surfaces:
            result["surface_counts"] = list(c); result["surface_means"] = list(means); result["incremental_surface"] = list(flat_inc)
        if target_count == 1: result.drop(columns="target_index", inplace=True)
        if self.device.type == "cuda": t.cuda.synchronize(self.device)
        return result

    def scan_packed_resolutions(self, observations: int, pairs: int, reader,
                                resolutions: tuple[int, ...] = (3, 5, 10),
                                row_chunk_size: int | None = None, target_count: int = 1,
                                cluster_codes: np.ndarray | None = None,
                                fold_codes: np.ndarray | None = None) -> dict[int, pd.DataFrame]:
        """Accumulate every governed resolution while reading each packed tile once."""
        t=self.torch; resolutions=tuple(dict.fromkeys(int(value) for value in resolutions))
        if set(resolutions)-{3,5,10}: raise ValueError("Packed scanner supports only 3/5/10")
        chunk=row_chunk_size or self.recommended_shape(observations,targets=target_count,maximum_pairs=max(1,pairs))[0]
        work_dtype=t.float32 if self.screening_dtype=="float32" else t.float64
        states={}
        for bins in resolutions:
            cells=bins*bins
            states[bins]=[t.zeros((pairs,target_count,cells),dtype=t.int64,device=self.device),
                          t.zeros((pairs,target_count,cells),dtype=t.float64,device=self.device),
                          t.zeros((pairs,target_count,cells),dtype=t.float64,device=self.device)]
        pair_numbers=t.arange(pairs,dtype=t.int64,device=self.device)[None,:]
        left_device=right_device=None
        for start in range(0,observations,chunk):
            end=min(start+chunk,observations); payload=reader(start,end)
            if len(payload)==3:
                packed_a,packed_b,y_host=payload
                pa=t.as_tensor(packed_a,dtype=t.uint8,device=self.device); pb=t.as_tensor(packed_b,dtype=t.uint8,device=self.device)
            else:
                packed,left_index,right_index,y_host=payload
                packed_device=t.as_tensor(packed,dtype=t.uint8,device=self.device)
                if left_device is None:
                    left_device=t.as_tensor(left_index,dtype=t.int64,device=self.device)
                    right_device=t.as_tensor(right_index,dtype=t.int64,device=self.device)
                pa=packed_device.index_select(1,left_device); pb=packed_device.index_select(1,right_device)
            y=t.tensor(y_host,dtype=work_dtype,device=self.device); y=y[:,None] if y.ndim==1 else y
            missing=(pa==255)|(pb==255)
            for bins in resolutions:
                if bins==3: a=pa.remainder(3).to(t.int64); b=pb.remainder(3).to(t.int64)
                elif bins==5: a=pa.div(3,rounding_mode="floor").remainder(5).to(t.int64); b=pb.div(3,rounding_mode="floor").remainder(5).to(t.int64)
                else: a=pa.div(15,rounding_mode="floor").to(t.int64); b=pb.div(15,rounding_mode="floor").to(t.int64)
                counts,sums,sumsq=states[bins]; cells=bins*bins; bin_valid=~missing
                cell_index=pair_numbers*cells+a*bins+b
                for target_index in range(target_count):
                    valid=bin_valid&t.isfinite(y[:,target_index])[:,None]
                    flat=cell_index[valid]
                    selected=y[:,target_index,None].expand(-1,pairs)[valid].to(t.float64)
                    local_count=t.bincount(flat,minlength=pairs*cells).reshape(pairs,cells)
                    local_sum=t.zeros(pairs*cells,dtype=t.float64,device=self.device); local_sumsq=t.zeros_like(local_sum)
                    local_sum.scatter_add_(0,flat,selected); local_sumsq.scatter_add_(0,flat,selected.square())
                    counts[:,target_index,:].add_(local_count)
                    sums[:,target_index,:].add_(local_sum.reshape(pairs,cells))
                    sumsq[:,target_index,:].add_(local_sumsq.reshape(pairs,cells))
        results={}
        for bins,(counts,sums,sumsq) in states.items():
            cells=bins*bins
            c=counts.cpu().numpy().reshape(pairs*target_count,cells)
            s=sums.cpu().numpy().reshape(pairs*target_count,cells)
            ss=sumsq.cpu().numpy().reshape(pairs*target_count,cells)
            results[bins]=_summarize_arrays(c,s,ss,bins,pairs,target_count)
        if cluster_codes is not None:
            from scipy.stats import norm
            codes=np.asarray(cluster_codes,dtype=np.int64); groups=int(codes.max())+1 if len(codes) else 0
            group_fold=_cluster_fold_map(codes,fold_codes,groups) if fold_codes is not None else None
            if self.device.type=="cuda":
                # Keep the inference pass on CUDA.  The prior implementation
                # copied every tile back to NumPy and reduced targets serially,
                # leaving both the GPU and most CPU cores idle.
                cluster_device={bins:[t.zeros((pairs,target_count,groups),dtype=t.float64,device=self.device),
                                      t.zeros((pairs,target_count,groups),dtype=t.int64,device=self.device)] for bins in resolutions}
                selected_device={bins:t.as_tensor(results[bins].selected_cell.to_numpy(np.int64).reshape(pairs,target_count),device=self.device) for bins in resolutions}
                frequency_device={bins:t.as_tensor(results[bins].selected_frequency.to_numpy(copy=True).reshape(pairs,target_count),dtype=t.float64,device=self.device) for bins in resolutions}
                inference_chunk=self.recommended_shape(observations,targets=1,maximum_pairs=max(1,pairs))[0]
                for start in range(0,observations,inference_chunk):
                    end=min(start+inference_chunk,observations); payload=reader(start,end)
                    if len(payload)==3:
                        packed_a,packed_b,y_host=payload
                        pa=t.as_tensor(packed_a,dtype=t.uint8,device=self.device); pb=t.as_tensor(packed_b,dtype=t.uint8,device=self.device)
                    else:
                        packed,left_index,right_index,y_host=payload
                        packed_device=t.as_tensor(packed,dtype=t.uint8,device=self.device)
                        li=t.as_tensor(left_index,dtype=t.int64,device=self.device); ri=t.as_tensor(right_index,dtype=t.int64,device=self.device)
                        pa=packed_device.index_select(1,li); pb=packed_device.index_select(1,ri)
                    y=t.as_tensor(y_host,dtype=work_dtype,device=self.device); y=y[:,None] if y.ndim==1 else y
                    bin_valid=(pa!=255)&(pb!=255)
                    group_codes=t.as_tensor(codes[start:end],dtype=t.int64,device=self.device)
                    group_pair=group_codes[:,None]*pairs+pair_numbers
                    for bins in resolutions:
                        if bins==3: a=pa.remainder(3).to(t.int64); b=pb.remainder(3).to(t.int64)
                        elif bins==5: a=pa.div(3,rounding_mode="floor").remainder(5).to(t.int64); b=pb.div(3,rounding_mode="floor").remainder(5).to(t.int64)
                        else: a=pa.div(15,rounding_mode="floor").to(t.int64); b=pb.div(15,rounding_mode="floor").to(t.int64)
                        cells_now=a*bins+b; cluster_sum_device,cluster_count_device=cluster_device[bins]
                        for target_index in range(target_count):
                            valid=bin_valid&t.isfinite(y[:,target_index])[:,None]
                            flat=group_pair.expand(-1,pairs)[valid]
                            contribution=((cells_now==selected_device[bins][:,target_index][None,:]).to(t.float64)-frequency_device[bins][:,target_index][None,:])*y[:,target_index,None]
                            values=contribution[valid]
                            local_count=t.bincount(flat,minlength=groups*pairs).reshape(groups,pairs).T
                            local_sum=t.zeros(groups*pairs,dtype=t.float64,device=self.device)
                            local_sum.scatter_add_(0,flat,values)
                            cluster_count_device[:,target_index,:].add_(local_count)
                            cluster_sum_device[:,target_index,:].add_(local_sum.reshape(groups,pairs).T)
                cluster={bins:[values[0].cpu().numpy().reshape(pairs*target_count,groups),
                               values[1].cpu().numpy().reshape(pairs*target_count,groups)] for bins,values in cluster_device.items()}
            else:
                cluster={bins:[np.zeros((pairs*target_count,groups)),np.zeros((pairs*target_count,groups),dtype=np.int64)] for bins in resolutions}
                for start in range(0,observations,chunk):
                    end=min(start+chunk,observations); payload=reader(start,end)
                    if len(payload)==3: pa,pb,yh=payload
                    else:
                        packed,left_index,right_index,yh=payload
                        pa=packed[:,left_index]; pb=packed[:,right_index]
                    yh=np.asarray(yh); yh=yh[:,None] if yh.ndim==1 else yh
                    segments=_cluster_segments(codes[start:end])
                    for bins in resolutions:
                        from ..cache.rank_store import unpack_bins
                        ah=unpack_bins(pa,bins).astype(np.int16); bh=unpack_bins(pb,bins).astype(np.int16); cells_now=ah*bins+bh
                        result=results[bins]; selected=result.selected_cell.to_numpy(np.int16); frequency=result.selected_frequency.to_numpy()
                        cluster_sum,cluster_count=cluster[bins]; bin_valid=(ah>=0)&(bh>=0)
                        for target_index in range(target_count):
                            rows=np.arange(pairs)*target_count+target_index; valid=np.isfinite(yh[:,target_index])[:,None]&bin_valid
                            contribution=((cells_now==selected[rows][None,:])-frequency[rows][None,:])*yh[:,target_index,None]
                            sums,counts=_cluster_reduce(contribution,valid,segments)
                            index=np.ix_(rows,segments[0])
                            cluster_sum[index]+=sums.T; cluster_count[index]+=counts.T
            for bins,result in results.items():
                cluster_sum,cluster_count=cluster[bins]; n=np.maximum(cluster_count.sum(1),1); mean=cluster_sum.sum(1)/n
                residual=cluster_sum-mean[:,None]*cluster_count; correction=groups/max(groups-1,1)
                se=np.sqrt(correction*np.square(residual).sum(1))/n; z=np.divide(mean,se,out=np.full(len(mean),np.nan),where=se>0)
                result["candidate_effect"]=mean; result["selection_test_effect"]=mean; result["cluster_se"]=se; result["test_statistic"]=z
                result["p_value"]=np.minimum(1.0,2*norm.sf(np.abs(z))*bins*bins); result["cluster_count"]=groups
                result["outlier_cluster_share"]=np.max(np.abs(cluster_sum),axis=1)/np.maximum(np.sum(np.abs(cluster_sum),axis=1),1e-15)
                if fold_codes is not None:
                    effects=[]
                    for fold in sorted(set(group_fold[group_fold>=0].tolist())):
                        mask=group_fold==fold; effects.append(cluster_sum[:,mask].sum(1)/np.maximum(cluster_count[:,mask].sum(1),1))
                    stacked=np.column_stack(effects) if effects else np.empty((pairs*target_count,0))
                    result["fold_effects"]=list(stacked); result["fold_sign_consistency"]=np.abs(np.sign(stacked).mean(1)) if stacked.shape[1] else np.nan
                    result["fold_magnitude_ratio"]=np.nanmin(np.abs(stacked),axis=1)/np.maximum(np.nanmax(np.abs(stacked),axis=1),1e-15) if stacked.shape[1] else np.nan
        if self.device.type=="cuda": t.cuda.synchronize(self.device)
        for result in results.values(): result.attrs.clear()
        return results
