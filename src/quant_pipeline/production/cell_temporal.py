from __future__ import annotations
from pathlib import Path
import numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
from quant_pipeline.production.outputs import ProductionData,iter_dual_batches

SCHEMA=pa.schema([("pair_id",pa.string()),("target_id",pa.string()),("resolution",pa.int16()),
    ("fold_positive_fraction",pa.list_(pa.float32())),("fold_negative_fraction",pa.list_(pa.float32())),
    ("worst_fold_bps",pa.list_(pa.float32())),("best_fold_bps",pa.list_(pa.float32())),
    ("median_fold_bps",pa.list_(pa.float32())),("fold_dispersion_bps",pa.list_(pa.float32())),("minimum_fold_n",pa.list_(pa.uint32()))])

def _reduce(counts,sums):
    means=np.divide(sums,counts,out=np.full_like(sums,np.nan,dtype=float),where=counts>0)*1e4; rows=[]
    for pair in range(counts.shape[0]):
        out={k:[] for k in SCHEMA.names[3:]}
        for cell in range(counts.shape[2]):
            valid=counts[pair,:,cell]>0; local=means[pair,valid,cell]; ns=counts[pair,valid,cell]
            out["fold_positive_fraction"].append(float(np.mean(local>0)) if len(local) else np.nan); out["fold_negative_fraction"].append(float(np.mean(local<0)) if len(local) else np.nan); out["worst_fold_bps"].append(float(np.min(local)) if len(local) else np.nan); out["best_fold_bps"].append(float(np.max(local)) if len(local) else np.nan); out["median_fold_bps"].append(float(np.median(local)) if len(local) else np.nan); out["fold_dispersion_bps"].append(float(np.std(local,ddof=1)) if len(local)>1 else np.nan); out["minimum_fold_n"].append(int(ns.min()) if len(ns) else 0)
        rows.append(out)
    return rows

def _pair_block_size(torch,device,*,folds:int,cells:int,row_chunk:int,maximum:int)->int:
    if device.type!="cuda": return max(1,min(maximum,32))
    free,_=torch.cuda.mem_get_info(device); budget=min(int(free*.70),int(10.5*1024**3)); per_pair=max(1,folds*cells*16+row_chunk*40)
    return max(1,min(maximum,budget//per_pair))

def build_cell_temporal_summary(*,legacy_run,dual_path:Path,research:dict)->Path:
    import torch
    data=ProductionData(legacy_run); destination=legacy_run.root/"cell_temporal_summary.parquet"; destination.unlink(missing_ok=True); writer=None; pair_cap=int(research.get("cell_evidence",{}).get("pair_block_max",64)); row_chunk=int(research.get("cell_evidence",{}).get("observation_chunk",250_000)); device=torch.device(legacy_run.config.compute.gpu_device if legacy_run.config.compute.prefer_cuda and torch.cuda.is_available() else "cpu"); columns=["pair_id","feature_a","feature_b","target_id","v3_resolution"]
    try:
        for record_batch in iter_dual_batches(dual_path,columns=columns):
            frame=record_batch.to_pandas(); frame["grid"]=[data.grid(x) for x in frame.feature_a]
            for (grid,target_id,resolution),group in frame.groupby(["grid","target_id","v3_resolution"],sort=False):
                obs=data.observations(grid); sessions=np.sort(pd.unique(pd.to_datetime(obs.session_date))); lookup={session:fold for fold,values in enumerate(np.array_split(sessions,int(legacy_run.config.stability["chronological_folds"]))) for session in values}; fold_codes=pd.to_datetime(obs.session_date).map(lookup).to_numpy(np.int64); folds=max(fold_codes)+1; target=np.asarray(legacy_run._target_ids_and_vector(grid,obs,target_id),dtype=float); cells=int(resolution)**2; pair_block=_pair_block_size(torch,device,folds=folds,cells=cells,row_chunk=row_chunk,maximum=pair_cap)
                for offset in range(0,len(group),pair_block):
                    part=group.iloc[offset:offset+pair_block]; pairs=len(part); counts=torch.zeros((pairs,folds,cells),dtype=torch.int64,device=device); sums=torch.zeros((pairs,folds,cells),dtype=torch.float64,device=device); pair_numbers=torch.arange(pairs,dtype=torch.int64,device=device)[None,:]; records=part[["feature_a","feature_b"]].to_dict("records")
                    for start in range(0,len(obs),row_chunk):
                        end=min(start+row_chunk,len(obs)); a=np.column_stack([data.bins_slice(grid,x["feature_a"],int(resolution),start,end) for x in records]); b=np.column_stack([data.bins_slice(grid,x["feature_b"],int(resolution),start,end) for x in records]); y=target[start:end]
                        ad=torch.as_tensor(a,dtype=torch.int64,device=device); bd=torch.as_tensor(b,dtype=torch.int64,device=device); yd=torch.as_tensor(y,dtype=torch.float64,device=device); fold=torch.as_tensor(fold_codes[start:end],dtype=torch.int64,device=device); valid=(ad>=0)&(bd>=0)&torch.isfinite(yd)[:,None]; cell=ad*int(resolution)+bd; key=pair_numbers*folds*cells+fold[:,None]*cells+cell; flat=key[valid]; values=yd[:,None].expand(-1,pairs)[valid]
                        counts.add_(torch.bincount(flat,minlength=pairs*folds*cells).reshape(pairs,folds,cells)); local=torch.zeros(pairs*folds*cells,dtype=torch.float64,device=device); local.scatter_add_(0,flat,values); sums.add_(local.reshape(pairs,folds,cells))
                    reduced=_reduce(counts.cpu().numpy(),sums.cpu().numpy()); rows=[]
                    for base,metrics in zip(part.to_dict("records"),reduced): rows.append({"pair_id":base["pair_id"],"target_id":base["target_id"],"resolution":int(base["v3_resolution"]),**metrics})
                    table=pa.Table.from_pylist(rows,schema=SCHEMA); writer=writer or pq.ParquetWriter(destination,SCHEMA,compression="zstd"); writer.write_table(table); del counts,sums
    finally:
        if writer: writer.close()
    if writer is None: pq.write_table(pa.Table.from_pylist([],schema=SCHEMA),destination,compression="zstd")
    return destination
