"""Independent legacy scanner oracle; test use only."""
import numpy as np
import pandas as pd
import torch
from quant_pipeline.hf_intraday.spec import SPEC,TARGETS
from quant_pipeline.hf_intraday.scan import codes,cell_count,sql_state

def gpu_moments(con,source,task,device):
    names=[f"q_{task['a']}"]+([f"q_{task['b']}"] if task['b'] else [])
    cols=','.join('"'+x+'"' for x in names+list(TARGETS))
    ncell=cell_count(task); nt=len(TARGETS)
    count=torch.zeros((ncell,nt),dtype=torch.int64,device=device)
    sums=torch.zeros((ncell,nt),dtype=torch.float64,device=device); sumsq=sums.clone()
    reader=con.execute(f'SELECT {cols} FROM read_parquet(?)',[source]).fetch_record_batch(100_000)
    for batch in reader:
        arrays=[batch.column(i).to_numpy(zero_copy_only=False) for i in range(batch.num_columns)]
        st=codes(task,arrays[0],arrays[1] if task['b'] else None)
        offset=len(names); y=torch.as_tensor(np.column_stack(arrays[offset:]),dtype=torch.float64,device=device)
        state=torch.as_tensor(st,device=device); valid=(state[:,None]>=0)&torch.isfinite(y)
        idx=state.clamp(min=0)[:,None].expand(-1,nt)
        clean=torch.where(valid,y,0.0)
        count.scatter_add_(0,idx,valid.long()); sums.scatter_add_(0,idx,clean); sumsq.scatter_add_(0,idx,clean**2)
    return count.cpu().numpy(),sums.cpu().numpy(),sumsq.cpu().numpy()


def scan_task(con,source,task,device):
    counts,sums,sumsq=gpu_moments(con,source,task,device)
    frames=[]; state=sql_state(task); ncell=cell_count(task)
    for j,target in enumerate(TARGETS):
        # Each target has its own finite-label mask and independent episode count.
        query=f'''WITH assigned AS (
            SELECT symbol,session_date,minute,month,"{target}"*10000 AS y,{state} AS cell
            FROM read_parquet(?)
        ), active AS (SELECT * FROM assigned WHERE cell>=0 AND isfinite(y)),
        episodes AS (SELECT *, CASE WHEN minute-lag(minute) OVER
            (PARTITION BY symbol,session_date,cell ORDER BY minute)=1 THEN 0 ELSE 1 END AS episode
            FROM active)
        SELECT cell,CASE WHEN grouping(symbol)=0 THEN 'symbol' WHEN grouping(month)=0 THEN 'month' ELSE 'all' END AS grouping,
            coalesce(symbol,month,'all') AS group_value,count(*)::BIGINT AS observations,
            sum(episode)::BIGINT AS unique_episodes,count(DISTINCT symbol)::BIGINT AS unique_symbols,
            avg(y) AS mean_bps,median(y) AS median_bps,avg((y>0)::INTEGER) AS win_rate,
            stddev_samp(y) AS dispersion_bps,stddev_samp(y)/sqrt(count(*)) AS standard_error_bps
        FROM episodes GROUP BY GROUPING SETS ((cell),(cell,symbol),(cell,month)) ORDER BY 1,2,3'''
        df=con.execute(query,[source]).fetchdf()
        allrows=df[df.grouping=='all'].set_index('cell') if not df.empty else pd.DataFrame()
        for cell in range(ncell):
            actual=int(allrows.loc[cell,'observations']) if cell in allrows.index else 0
            if actual!=counts[cell,j]: raise RuntimeError(f'GPU/SQL count mismatch: {task["key"]}/{target}/{cell}')
            if actual:
                mean=sums[cell,j]/actual*10000
                if not np.isclose(mean,allrows.loc[cell,'mean_bps'],atol=1e-8,rtol=1e-9):
                    raise RuntimeError('GPU/SQL mean mismatch')
                if actual>1:
                    sd=np.sqrt(max(0,(sumsq[cell,j]-sums[cell,j]**2/actual)/(actual-1)))*10000
                    if not np.isclose(sd,allrows.loc[cell,'dispersion_bps'],atol=1e-7,rtol=1e-7):
                        raise RuntimeError('GPU/SQL dispersion mismatch')
            else:
                empty=dict(cell=cell,grouping='all',group_value='all',observations=0,unique_episodes=0,
                           unique_symbols=0,mean_bps=np.nan,median_bps=np.nan,win_rate=np.nan,
                           dispersion_bps=np.nan,standard_error_bps=np.nan)
                df=pd.concat((df,pd.DataFrame([empty])),ignore_index=True)
        df['target']=target
        frames.append(df)
    result=pd.concat(frames,ignore_index=True)
    result['surface_id']=task['key']; result['feature_a']=task['a']; result['feature_b']=task['b']
    result['resolution']=task['resolution']; result['tail_fraction']=task['tail']; result['tail_side']=task['side']
    result['state_a']=result.cell//task['resolution'] if task['b'] and task['tail'] is None else result.cell if not task['b'] else 0
    result['state_b']=result.cell%task['resolution'] if task['b'] else -1
    result['direction']=np.where(result.mean_bps>0,1,np.where(result.mean_bps<0,-1,0))
    result['t_stat']=result.mean_bps/result.standard_error_bps.replace(0,np.nan)
    result['basis']=result.target.map({x['id']:x['basis'] for x in SPEC['targets']})
    result['bin_definition']='same_clock_prior60_empirical_midrank'
    result['inference']='descriptive_observation_SE; overlapping observations; episodes reported separately'
    return result

