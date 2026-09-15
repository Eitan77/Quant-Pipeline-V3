from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


_PLACEBO_INPUTS = None


def _placebo_statistic(args) -> float:
    seed,x,y,group_rows=args
    rng=np.random.default_rng(seed); shuffled=x.copy()
    for rows in group_rows: shuffled[rows]=rng.permutation(shuffled[rows])
    return float(spearmanr(shuffled,y).statistic)


def _initialize_placebo_worker(x, y, group_rows) -> None:
    global _PLACEBO_INPUTS
    _PLACEBO_INPUTS = (x, y, group_rows)


def _placebo_seed_statistic(seed) -> float:
    return _placebo_statistic((seed, *_PLACEBO_INPUTS))


def _cuda_placebo_statistics(x: np.ndarray, y: np.ndarray, groups: np.ndarray,
                             runs: int, seed: int) -> np.ndarray | None:
    try:
        import torch
        if not torch.cuda.is_available(): return None
        from scipy.stats import rankdata
        _,inverse=np.unique(groups,return_inverse=True); counts=np.bincount(inverse)
        if not len(counts): return None
        width=int(counts.max()); order=np.argsort(inverse,kind="stable")
        starts=np.cumsum(np.r_[0,counts[:-1]]); sorted_positions=np.arange(len(order))-np.repeat(starts,counts)
        positions=np.empty(len(order),dtype=np.int64); positions[order]=sorted_positions
        xr=rankdata(x).astype(np.float32); yr=rankdata(y).astype(np.float32)
        xr-=xr.mean(); yr-=yr.mean(); shape=(len(counts),width)
        x_matrix=np.zeros(shape,dtype=np.float32); y_matrix=np.zeros(shape,dtype=np.float32); mask=np.zeros(shape,dtype=bool)
        x_matrix[inverse,positions]=xr; y_matrix[inverse,positions]=yr; mask[inverse,positions]=True
        denominator=float(np.sqrt(np.sum(xr*xr,dtype=np.float64)*np.sum(yr*yr,dtype=np.float64)))
        if not np.isfinite(denominator) or denominator==0: return np.full(runs,np.nan)
        device=torch.device("cuda"); xt=torch.from_numpy(x_matrix).to(device); yt=torch.from_numpy(y_matrix).to(device)
        mt=torch.from_numpy(mask).to(device); generator=torch.Generator(device=device); generator.manual_seed(int(seed))
        output=[]; batch_size=8
        with torch.inference_mode():
            for start in range(0,runs,batch_size):
                size=min(batch_size,runs-start)
                keys=torch.rand((size,*shape),device=device,generator=generator)
                keys.masked_fill_(~mt.unsqueeze(0),2.0)
                permutation=torch.argsort(keys,dim=2)
                shuffled=torch.gather(xt.unsqueeze(0).expand(size,-1,-1),2,permutation)
                output.append(((shuffled*yt.unsqueeze(0)).sum(dim=(1,2))/denominator).cpu().numpy())
        return np.concatenate(output).astype(float,copy=False)
    except (ImportError,RuntimeError):
        return None


def placebo_test(score: np.ndarray, target: np.ndarray, decision_codes: np.ndarray, runs: int = 1000,
                 seed: int = 1729, workers: int = 1) -> pd.DataFrame:
    valid = np.isfinite(score) & np.isfinite(target); x, y, groups = score[valid], target[valid], decision_codes[valid]
    observed=float(spearmanr(x,y).statistic)
    statistics=_cuda_placebo_statistics(x,y,groups,runs,seed)
    if statistics is not None:
        p = (1 + np.sum(np.abs(statistics) >= abs(observed))) / (runs + 1)
        return pd.DataFrame({"observed_statistic": [observed], "empirical_p_value": [p], "number_of_placebo_runs": [runs], "placebo_mean": [np.nanmean(statistics)], "placebo_std": [np.nanstd(statistics,ddof=1)]})
    group_rows=tuple(np.flatnonzero(groups==group) for group in np.unique(groups))
    seeds=np.random.SeedSequence(seed).spawn(runs)
    if int(workers)>1:
        from concurrent.futures import ProcessPoolExecutor
        from ..resources import _system_memory
        payload_bytes=x.nbytes+y.nbytes+sum(rows.nbytes for rows in group_rows)
        available,_=_system_memory()
        memory_workers=max(1,int(available*.90/max(64*(1<<20),payload_bytes*2)))
        worker_count=min(int(workers),runs,memory_workers)
        with ProcessPoolExecutor(max_workers=worker_count,initializer=_initialize_placebo_worker,
                                 initargs=(x,y,group_rows)) as pool:
            statistics=np.fromiter(pool.map(_placebo_seed_statistic,seeds,
                chunksize=max(1,runs//(worker_count*4))),dtype=float,count=runs)
    else:
        statistics=np.fromiter((_placebo_statistic((child_seed,x,y,group_rows)) for child_seed in seeds),dtype=float,count=runs)
    p = (1 + np.sum(np.abs(statistics) >= abs(observed))) / (runs + 1)
    return pd.DataFrame({"observed_statistic": [observed], "empirical_p_value": [p], "number_of_placebo_runs": [runs], "placebo_mean": [statistics.mean()], "placebo_std": [statistics.std(ddof=1)]})
