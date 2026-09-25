from __future__ import annotations
from pathlib import Path
from hashlib import sha256
import json,os
import duckdb,numpy as np,pandas as pd,pyarrow as pa,pyarrow.dataset as ds,pyarrow.parquet as pq
from quant_pipeline.production.outputs import ProductionData

SCHEMA=pa.schema([("pair_id",pa.string()),("target_id",pa.string()),("resolution",pa.int16()),
    ("eligible_symbol_count",pa.list_(pa.uint16())),("positive_symbol_fraction",pa.list_(pa.float32())),
    ("negative_symbol_fraction",pa.list_(pa.float32())),("symbol_effect_dispersion_bps",pa.list_(pa.float32())),
    ("best_positive_local_bps",pa.list_(pa.float32())),("best_negative_local_bps",pa.list_(pa.float32())),
    ("top_symbol_contribution_share",pa.list_(pa.float32())),("top5_symbol_contribution_share",pa.list_(pa.float32())),
    ("cancellation_score",pa.list_(pa.float32()))])

def _summaries(counts,sums,minimum):
    means=np.divide(sums,counts,out=np.full_like(sums,np.nan,dtype=float),where=counts>0)*1e4
    eligible=counts>=minimum; local=np.where(eligible,means,np.nan); n=eligible.sum(axis=1)
    positive=(local>0).sum(axis=1); negative=(local<0).sum(axis=1)
    local_total=np.where(eligible,local,0.0).sum(axis=1)
    local_mean=np.divide(local_total,n,out=np.zeros_like(local_total),where=n>0)
    centered=np.where(eligible,local-local_mean[:,None,:],0.0)
    squared=(centered*centered).sum(axis=1)
    dispersion=np.sqrt(np.divide(squared,n-1,out=np.full_like(squared,np.nan),where=n>1))
    best_positive=np.max(np.where(local>0,local,-np.inf),axis=1); best_positive[~np.isfinite(best_positive)]=np.nan
    best_negative=np.min(np.where(local<0,local,np.inf),axis=1); best_negative[~np.isfinite(best_negative)]=np.nan
    contribution=np.where(eligible,np.abs(sums),0.0); total=contribution.sum(axis=1); top1=contribution.max(axis=1)
    keep=min(5,contribution.shape[1]); top5=np.partition(contribution,contribution.shape[1]-keep,axis=1)[:,-keep:,:].sum(axis=1)
    global_n=counts.sum(axis=1); global_mean=np.divide(sums.sum(axis=1),global_n,out=np.full_like(total,np.nan),where=global_n>0)*1e4
    local_abs=np.nansum(np.abs(local),axis=1); cancellation=np.divide(local_abs,n,out=np.full_like(total,np.nan),where=n>0)/np.maximum(np.abs(global_mean),1e-9)
    fraction_positive=np.divide(positive,n,out=np.full_like(total,np.nan),where=n>0); fraction_negative=np.divide(negative,n,out=np.full_like(total,np.nan),where=n>0)
    top1_share=np.divide(top1,total,out=np.full_like(total,np.nan),where=total!=0); top5_share=np.divide(top5,total,out=np.full_like(total,np.nan),where=total!=0)
    metrics=(np.minimum(n,65535),fraction_positive,fraction_negative,dispersion,best_positive,best_negative,top1_share,top5_share,cancellation)
    return [{name:values[pair].tolist() for name,values in zip(SCHEMA.names[3:],metrics)} for pair in range(counts.shape[0])]

def _completed(parts:Path):
    files=list(parts.glob("*.parquet"))
    if not files:return set()
    frame=ds.dataset([str(path) for path in files],format="parquet").to_table(columns=["pair_id","target_id","resolution"]).to_pandas()
    return set(frame.itertuples(index=False,name=None))

def _compact(parts:Path,destination:Path):
    temporary=destination.with_suffix(".parquet.partial"); temporary.unlink(missing_ok=True); writer=None
    try:
        for path in sorted(parts.glob("*.parquet")):
            for batch in pq.ParquetFile(path).iter_batches(batch_size=65_536):
                table=pa.Table.from_batches([batch],schema=SCHEMA); writer=writer or pq.ParquetWriter(temporary,SCHEMA,compression="zstd"); writer.write_table(table)
    finally:
        if writer:writer.close()
    if writer is None:pq.write_table(pa.Table.from_pylist([],schema=SCHEMA),temporary,compression="zstd")
    os.replace(temporary,destination)

def _pair_block_size(torch,device,*,axis_count:int,cells:int,row_chunk:int,maximum:int,target_count:int=1)->int:
    if device.type!="cuda": return max(1,min(maximum,32))
    free,_=torch.cuda.mem_get_info(device); budget=min(int(free*.65),int(9.5*1024**3)); per_pair=max(1,axis_count*cells*16*target_count+row_chunk*28)
    return max(1,min(maximum,budget//per_pair))

def build_cell_specialist_summary(*,legacy_run,dual_path:Path,research:dict,stage_id:str)->Path:
    import torch
    data=ProductionData(legacy_run); destination=legacy_run.root/"cell_specialist_summary.parquet"; destination.unlink(missing_ok=True); parts=legacy_run.root/"cell_specialist_parts"/stage_id; parts.mkdir(parents=True,exist_ok=True); completed=_completed(parts); expected=pq.ParquetFile(dual_path).metadata.num_rows; progress=legacy_run.root/"v3_progress"/"cell_specialist.json"; progress.parent.mkdir(exist_ok=True)
    pair_cap=int(research.get("cell_evidence",{}).get("pair_block_max",64)); row_chunk=int(research.get("cell_evidence",{}).get("observation_chunk",250_000)); minimum=int(research.get("specialist",{}).get("min_local_n",20)); device=torch.device(legacy_run.config.compute.gpu_device if legacy_run.config.compute.prefer_cuda and torch.cuda.is_available() else "cpu")
    with duckdb.connect() as con:
        pairs=con.execute("SELECT DISTINCT pair_id,feature_a,feature_b,v3_resolution FROM read_parquet(?) ORDER BY v3_resolution,pair_id",[str(dual_path)]).fetchdf()
        links=con.execute("SELECT DISTINCT feature_a,target_id FROM read_parquet(?)",[str(dual_path)]).fetchdf()
    pairs["grid"]=[data.grid(x) for x in pairs.feature_a]; links["grid"]=[data.grid(x) for x in links.feature_a]
    targets_by_grid={grid:list(group.target_id.drop_duplicates()) for grid,group in links.groupby("grid",sort=False)}
    pending=[]; pending_keys=[]; pending_rows=0
    def flush():
        nonlocal pending,pending_keys,pending_rows,completed
        if not pending:return
        table=pa.concat_tables(pending); digest=sha256("\n".join(f"{a}|{b}|{c}" for a,b,c in pending_keys).encode()).hexdigest()[:20]; final=parts/f"part-{digest}.parquet"; temporary=final.with_suffix(".parquet.partial")
        if not final.exists():pq.write_table(table,temporary,compression="zstd"); os.replace(temporary,final)
        completed.update(pending_keys); payload={"stage":"cell_specialist","completed":len(completed),"expected":expected,"percent":100.0*len(completed)/expected}; tmp=progress.with_suffix(".partial"); tmp.write_text(json.dumps(payload,sort_keys=True),encoding="utf-8"); os.replace(tmp,progress)
        pending=[]; pending_keys=[]; pending_rows=0
    try:
        for (grid,resolution),group in pairs.groupby(["grid","v3_resolution"],sort=False):
            obs=data.observations(grid); security_codes,security_values=pd.factorize(obs.security_id,sort=True); security_count=len(security_values); cells=int(resolution)**2; target_ids=targets_by_grid[grid]; targets={target_id:np.asarray(legacy_run._target_ids_and_vector(grid,obs,target_id),dtype=float) for target_id in target_ids}
            pair_block=_pair_block_size(torch,device,axis_count=security_count,cells=cells,row_chunk=row_chunk,maximum=pair_cap,target_count=len(target_ids))
            for offset in range(0,len(group),pair_block):
                part=group.iloc[offset:offset+pair_block]; needed={target_id:np.array([(pair_id,target_id,int(resolution)) not in completed for pair_id in part.pair_id],dtype=bool) for target_id in target_ids}; active=[target_id for target_id in target_ids if needed[target_id].any()]
                if not active:continue
                pair_count=len(part); counts=torch.zeros((len(active),pair_count,security_count,cells),dtype=torch.int64,device=device); sums=torch.zeros((len(active),pair_count,security_count,cells),dtype=torch.float64,device=device); pair_numbers=torch.arange(pair_count,dtype=torch.int64,device=device)[None,:]
                records=part[["feature_a","feature_b"]].to_dict("records")
                for start in range(0,len(obs),row_chunk):
                    end=min(start+row_chunk,len(obs)); a=np.column_stack([data.bins_slice(grid,x["feature_a"],int(resolution),start,end) for x in records]); b=np.column_stack([data.bins_slice(grid,x["feature_b"],int(resolution),start,end) for x in records])
                    ad=torch.as_tensor(a,dtype=torch.int64,device=device); bd=torch.as_tensor(b,dtype=torch.int64,device=device); sec=torch.as_tensor(security_codes[start:end],dtype=torch.int64,device=device); bin_valid=(ad>=0)&(bd>=0); cell=ad*int(resolution)+bd; key=pair_numbers*security_count*cells+sec[:,None]*cells+cell
                    for target_number,target_id in enumerate(active):
                        yd=torch.as_tensor(targets[target_id][start:end],dtype=torch.float64,device=device); valid=bin_valid&torch.isfinite(yd)[:,None]; flat=key[valid]; values=yd[:,None].expand(-1,pair_count)[valid]
                        counts[target_number].view(-1).add_(torch.bincount(flat,minlength=pair_count*security_count*cells)); sums[target_number].view(-1).scatter_add_(0,flat,values)
                for target_number,target_id in enumerate(active):
                    keep=needed[target_id]; selected=part.loc[keep]; selected_keys=[(pair_id,target_id,int(resolution)) for pair_id in selected.pair_id]
                    reduced=_summaries(counts[target_number].cpu().numpy()[keep],sums[target_number].cpu().numpy()[keep],minimum); rows=[]
                    for base,metrics in zip(selected.to_dict("records"),reduced):rows.append({"pair_id":base["pair_id"],"target_id":target_id,"resolution":int(resolution),**metrics})
                    pending.append(pa.Table.from_pylist(rows,schema=SCHEMA)); pending_keys.extend(selected_keys); pending_rows+=len(rows)
                    if pending_rows>=2048:flush()
                del counts,sums
    finally:
        flush()
    _compact(parts,destination)
    return destination
