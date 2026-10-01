"""HF contracts adapted to the shared production CUDA and concurrency engines.

Exact medians and target-specific episodes remain CPU distribution work. Inputs
are decoded once, targets are device-resident when admitted, and one coordinator
owns publication. Empty surfaces are published, never removed from the plan.
"""
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json,os,time,threading
import duckdb,numpy as np,pandas as pd,psutil,torch
from .resource_policy import ResourcePolicy
from .segmented_cuda import FusedSegmentedBatch
from quant_pipeline.alpha_discovery.feature_autoscale import AdaptiveFeatureConcurrency


def prepare_inputs(root,machine,telemetry):
    from quant_pipeline.hf_intraday.runner import write_json
    from quant_pipeline.hf_intraday.spec import FEATURES,TARGETS
    root=Path(root); folder=root/'cache/hf_execution'; folder.mkdir(parents=True,exist_ok=True)
    signature=[dict(name=p.name,size=p.stat().st_size,mtime=p.stat().st_mtime_ns)
               for p in sorted((root/'observations').glob('*.parquet'))]
    marker=folder/'inputs.json'; database=folder/'inputs.duckdb'
    if marker.exists() and database.exists():
        metadata=json.loads(marker.read_text(encoding='utf-8'))
        if metadata['sources']!=signature: raise RuntimeError('Prepared HF inputs changed')
        return database,metadata
    pending=folder/'inputs.partial.duckdb'
    if pending.exists(): pending.unlink()
    telemetry.event('hf_inputs_start',stage='hf:prepare-scan')
    columns=['symbol','session_date','month','minute']+[f'q_{key}' for key in FEATURES]+list(TARGETS)
    policy=ResourcePolicy(machine)
    with duckdb.connect(str(pending)) as con:
        con.execute(f"SET memory_limit='{policy.duckdb_gib()}GB'")
        con.execute('SET temp_directory=?',[str(machine['duckdb_temp'])])
        con.execute('SET threads=?',[os.cpu_count() or 1])
        fields=','.join('"'+key+'"' for key in columns)
        con.execute(f'CREATE TABLE hf_inputs AS SELECT row_number() OVER ()-1 AS _hf_rowid,{fields} FROM read_parquet(?)',
                    [(root/'observations/*.parquet').as_posix()])
        counts=','.join(f'count(*) FILTER(WHERE isfinite("{key}")) AS "{key}"' for key in columns[4:])
        finite=con.execute('SELECT '+counts+' FROM hf_inputs').fetchdf().iloc[0].to_dict()
        rows=con.execute('SELECT count(*) FROM hf_inputs').fetchone()[0]
    os.replace(pending,database)
    metadata=dict(sources=signature,rows=rows,finite={key:int(value) for key,value in finite.items()})
    write_json(marker,metadata)
    return database,metadata


def connect_inputs(database,machine,workers,memory_gb):
    # Each worker has an independent memory/CPU budget; the prepared file is read-only.
    con=duckdb.connect()
    con.execute(f"SET memory_limit='{memory_gb}GB'")
    con.execute('SET temp_directory=?',[str(machine['duckdb_temp'])])
    con.execute('SET threads=?',[max(1,(os.cpu_count() or 1)//workers)])
    escaped=Path(database).as_posix().replace("'","''")
    con.execute(f"ATTACH '{escaped}' AS hf_cache (READ_ONLY)")
    return con


class ResidentTargets:
    def __init__(self,con,rows,targets,device,enabled,reserve_bytes=1<<30):
        self.targets=targets; self.values=None; self.lock=threading.Lock()
        if not enabled or device=='cpu' or not targets: return
        free,_=torch.cuda.mem_get_info(device)
        size=rows*len(targets)*8
        if size+reserve_bytes>free: return
        self.values=torch.empty((rows,len(targets)),dtype=torch.float64,device=device)
        fields=','.join('"'+key+'"' for key in targets)
        for batch in con.execute(f'SELECT _hf_rowid,{fields} FROM hf_cache.hf_inputs').to_arrow_reader(250_000):
            ids=batch.column(0).to_numpy(zero_copy_only=False)
            y=np.column_stack([batch.column(i+1).to_numpy(zero_copy_only=False) for i in range(len(targets))])
            self.values.index_copy_(0,torch.as_tensor(ids,device=device),torch.as_tensor(y,device=device))
        torch.cuda.synchronize(device)


def fused_moments(con,task,targets,device,resident,row_chunk=250_000):
    from quant_pipeline.hf_intraday.scan import codes,cell_count
    cells=cell_count(task); nt=len(targets)
    if device=='cpu':
        n=np.zeros((cells,nt),np.int64); s=np.zeros((cells,nt)); q=s.copy()
    else:
        # The shared kernel's exact joint-code mode also supports arbitrary HF
        # state masks, including 1-cell tails; no quantile or tail approximation.
        shape=(nt,1,1,cells)
        n=torch.zeros(shape,dtype=torch.int64,device=device)
        s=torch.zeros(shape,dtype=torch.float64,device=device); q=torch.zeros_like(s)
        moments=SimpleNamespace(n=n,s=s,q=q,device=n.device,shape=shape,cells=cells,singles=True)
        native_task=dict(grouping_id='all',group_start=0,group_stop=1,resolution=task['resolution'])
        fused=FusedSegmentedBatch([(native_task,moments)],[0],None,joint_codes=np.arange(cells))
    features=[f'q_{task["a"]}']+([f'q_{task["b"]}'] if task['b'] else [])
    fields=['_hf_rowid']+features+([] if resident.values is not None else targets)
    from quant_pipeline.hf_intraday.scan import sql_state
    query='SELECT '+','.join('"'+key+'"' for key in fields)+' FROM hf_cache.hf_inputs WHERE ('+sql_state(task)+')>=0'
    for batch in con.execute(query).to_arrow_reader(row_chunk):
        arrays=[batch.column(i).to_numpy(zero_copy_only=False) for i in range(batch.num_columns)]
        state=codes(task,arrays[1],arrays[2] if task['b'] else None)
        if device=='cpu':
            y=np.column_stack(arrays[1+len(features):])
            for j in range(nt):
                good=(state>=0)&np.isfinite(y[:,j]); index=state[good]
                n[:,j]+=np.bincount(index,minlength=cells)
                s[:,j]+=np.bincount(index,weights=y[good,j],minlength=cells)
                q[:,j]+=np.bincount(index,weights=y[good,j]**2,minlength=cells)
        else:
            # Share the resident target allocation and shared production stream.
            with resident.lock:
                packed=torch.as_tensor(np.where(state>=0,state,255).astype(np.uint8)[:,None],device=device)
                y=(resident.values.index_select(0,torch.as_tensor(arrays[0],device=device)) if resident.values is not None
                   else torch.as_tensor(np.column_stack(arrays[1+len(features):]),dtype=torch.float64,device=device))
                fused.update((packed,y),{'all':np.zeros(len(state),np.int64)})
                torch.cuda.synchronize(device)
    if device!='cpu':
        n,s,q=(value[:,0,0,:].T.cpu().numpy() for value in (n,s,q))
    return n,s,q


def distributions(con,task,targets,batch_size):
    from quant_pipeline.hf_intraday.scan import sql_state
    frames=[]
    for start in range(0,len(targets),batch_size):
        chosen=targets[start:start+batch_size]
        fields=','.join(f'"{key}"*10000 AS y{j}' for j,key in enumerate(chosen))
        lags=','.join(f'lag(CASE WHEN isfinite(y{j}) THEN minute END IGNORE NULLS) OVER w AS prev{j}' for j in range(len(chosen)))
        aggregates=[]
        metrics=['observations','unique_episodes','unique_symbols','mean_bps','median_bps','win_rate','dispersion_bps','standard_error_bps']
        for j in range(len(chosen)):
            valid=f'isfinite(y{j})'; filt=f' FILTER(WHERE {valid})'
            aggregates.extend([f'count(*){filt} AS m{j}_0',
                f'count(*) FILTER(WHERE {valid} AND (prev{j} IS NULL OR minute-prev{j}<>1)) AS m{j}_1',
                f'count(DISTINCT symbol){filt} AS m{j}_2',f'avg(y{j}){filt} AS m{j}_3',
                f'median(y{j}){filt} AS m{j}_4',f'avg((y{j}>0)::INTEGER){filt} AS m{j}_5',
                f'stddev_samp(y{j}){filt} AS m{j}_6',
                f'(stddev_samp(y{j}){filt})/sqrt(count(*){filt}) AS m{j}_7'])
        finite_any=' OR '.join(f'isfinite(y{j})' for j in range(len(chosen)))
        query=f'''WITH assigned AS (SELECT symbol,session_date,minute,month,{fields},{sql_state(task)} AS cell
                FROM hf_cache.hf_inputs), active AS (SELECT * FROM assigned WHERE cell>=0 AND ({finite_any})),
            episodes AS (SELECT *,{lags} FROM active
                WINDOW w AS (PARTITION BY symbol,session_date,cell ORDER BY minute))
            SELECT cell,CASE WHEN grouping(symbol)=0 THEN 'symbol' WHEN grouping(month)=0 THEN 'month' ELSE 'all' END AS grouping,
                coalesce(symbol,month,'all') AS group_value,{','.join(aggregates)}
            FROM episodes GROUP BY GROUPING SETS ((cell),(cell,symbol),(cell,month)) ORDER BY 1,2,3'''
        wide=con.execute(query).fetchdf()
        for j,key in enumerate(chosen):
            columns=['cell','grouping','group_value']+[f'm{j}_{m}' for m in range(8)]
            frame=wide[columns].rename(columns={f'm{j}_{m}':metric for m,metric in enumerate(metrics)})
            frame=frame.loc[frame.observations>0].copy(); frame['target']=key; frames.append(frame)
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()


def finish_result(task,frame,targets,moments):
    from quant_pipeline.hf_intraday.spec import SPEC,TARGETS
    from quant_pipeline.hf_intraday.scan import cell_count
    cells=cell_count(task); frames=[]; counts,sums,sumsq=moments
    for key in TARGETS:
        df=frame.loc[frame.target==key].drop(columns='target').copy() if not frame.empty else pd.DataFrame()
        allrows=df[df.grouping=='all'].set_index('cell') if not df.empty else pd.DataFrame()
        j=targets.index(key) if key in targets else None
        missing=[]
        for cell in range(cells):
            actual=int(allrows.loc[cell,'observations']) if cell in allrows.index else 0
            expected=0 if j is None else counts[cell,j]
            if actual!=expected: raise RuntimeError(f'Fused/SQL count mismatch: {task["key"]}/{key}/{cell}')
            if actual:
                mean=sums[cell,j]/actual*10000
                if not np.isclose(mean,allrows.loc[cell,'mean_bps'],atol=1e-8,rtol=1e-9): raise RuntimeError('Fused/SQL mean mismatch')
                if actual>1:
                    sd=np.sqrt(max(0,(sumsq[cell,j]-sums[cell,j]**2/actual)/(actual-1)))*10000
                    if not np.isclose(sd,allrows.loc[cell,'dispersion_bps'],atol=1e-7,rtol=1e-7): raise RuntimeError('Fused/SQL dispersion mismatch')
            else:
                missing.append(dict(cell=cell,grouping='all',group_value='all',observations=0,unique_episodes=0,unique_symbols=0,
                    mean_bps=np.nan,median_bps=np.nan,win_rate=np.nan,dispersion_bps=np.nan,standard_error_bps=np.nan))
        if missing: df=pd.concat([df,pd.DataFrame(missing)],ignore_index=True)
        df['target']=key; frames.append(df)
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


def scan_surface(database,metadata,task,machine,workers,memory_gb,device,resident,batch_size):
    from quant_pipeline.hf_intraday.scan import cell_count
    targets=resident.targets
    empty=any(metadata['finite'][f'q_{key}']==0 for key in [task['a']]+([task['b']] if task['b'] else []))
    if empty or not targets:
        zeros=np.zeros((cell_count(task),len(targets)))
        return finish_result(task,pd.DataFrame(),targets,(zeros.astype(np.int64),zeros,zeros))
    with connect_inputs(database,machine,workers,memory_gb) as con:
        moments=fused_moments(con,task,targets,device,resident)
        # Empty state masks require no distribution reads, but still publish all cells.
        frame=distributions(con,task,targets,batch_size) if moments[0].any() else pd.DataFrame()
    return finish_result(task,frame,targets,moments)


def execute_hf(root,settings,device,telemetry,machine):
    from quant_pipeline.hf_intraday.scan import tasks,cell_count,atomic_frame
    from quant_pipeline.hf_intraday.spec import TARGETS
    from quant_pipeline.hf_intraday.runner import write_json
    database,metadata=prepare_inputs(root,machine,telemetry); root=Path(root)
    policy=ResourcePolicy(machine); autoscale=machine.get('feature_autoscale',{})
    memory_gb=min(4,policy.duckdb_gib()); worker_bytes=int(memory_gb*(1<<30)*1.25)
    maximum=max(1,min(policy.compatibility_workers(),max(1,(psutil.virtual_memory().available-policy.host_reserve)//worker_bytes)))
    controller=AdaptiveFeatureConcurrency(minimum=min(maximum,int(autoscale.get('min_workers',1))),maximum=maximum,
        initial=min(maximum,int(autoscale.get('initial_workers',1))),step=int(autoscale.get('step_workers',1)),
        tuning_window_seconds=float(autoscale.get('tuning_window_seconds',10)),tuning_min_completions=int(autoscale.get('tuning_min_completions',8)),
        min_gain_fraction=float(autoscale.get('min_gain_fraction',.02)),regression_fraction=float(autoscale.get('regression_fraction',.05)),
        memory_guard_multiplier=float(autoscale.get('memory_guard_multiplier',1.25)),default_worker_memory_bytes=worker_bytes,
        cooldown_seconds=float(autoscale.get('cooldown_seconds',5)))
    if not autoscale.get('enabled',False): controller.current=1
    controller.begin_wave(time.perf_counter())
    if not autoscale.get('enabled',False): controller.current=1
    targets=[key for key in TARGETS if metadata['finite'][key]>0]
    with connect_inputs(database,machine,maximum,memory_gb) as con:
        resident=ResidentTargets(con,metadata['rows'],targets,device,bool(machine.get('evidence_resident_inputs',False)))
    batch_size=max(1,min(8,int(memory_gb*(1<<30)/max(1,metadata['rows']*8*6))))
    telemetry.event('hf_execution_admitted',stage='hf:scan',backend='production_fused_cuda' if device!='cpu' else 'production_cpu',
        target_resident=resident.values is not None,workers=controller.current,worker_cap=maximum,target_batch=batch_size)
    plan=tasks(settings); pending=[]; completed=0
    def paths(task):
        folder={'single':'single_results.parquet','dual':'dual_results.parquet','tail':'tail_results.parquet'}[task['kind']]
        return root/folder/f'{task["key"]}.parquet',root/'scan_checkpoints'/f'{task["key"]}.json',root/'candidate_summary.parquet'/f'{task["key"]}.parquet',root/'candidate_event_paths.parquet'/f'{task["key"]}.parquet'
    for task in plan:
        if all(path.exists() for path in paths(task)): completed+=1
        else: pending.append(task)
    telemetry.progress('hf:scan',completed,len(plan),workers=controller.current,backend='shared_production')
    iterator=iter(pending); live={}; started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=maximum) as pool:
        exhausted=False
        while live or not exhausted:
            while len(live)<controller.current and not exhausted:
                try: task=next(iterator)
                except StopIteration: exhausted=True; break
                future=pool.submit(scan_surface,database,metadata,task,machine,maximum,memory_gb,device,resident,batch_size)
                live[future]=task
            if not live: break
            done,_=wait(live,timeout=30,return_when=FIRST_COMPLETED)
            if not done:
                telemetry.event('hf_scan_heartbeat',stage='hf:scan',completed=completed,expected=len(plan),active_surfaces=len(live))
            for future in done:
                task=live.pop(future); result=future.result()
                destination,marker,summary,paths_file=paths(task)
                atomic_frame(result,destination); selected=result[result.grouping=='all'].copy(); atomic_frame(selected,summary)
                event_paths=selected[selected.target.str.match(r'fwd_(raw|beta_resid|factor_resid)_(1|2|3|5|10)m$')].copy()
                event_paths['offset_minutes']=event_paths.target.str.extract(r'_(\d+)m$')[0].astype(int)
                atomic_frame(event_paths,paths_file); write_json(marker,dict(task=task,rows=len(result),backend='shared_production'))
                completed+=1
                telemetry.progress('hf:scan',completed,len(plan),surface=task['key'],workers=controller.current)
                controller.observe(work_units=1,peak_rss_bytes=worker_bytes,now=time.perf_counter())
            if autoscale.get('enabled',False):
                event=controller.evaluate(available_bytes=psutil.virtual_memory().available,reserve_bytes=policy.host_reserve,now=time.perf_counter())
                if event: telemetry.event('hf_scan_autoscale',stage='hf:scan',**event)
    expected=sum(cell_count(task)*len(TARGETS) for task in plan)
    with duckdb.connect() as con:
        actual=con.execute('SELECT count(*) FROM read_parquet(?)',[(root/'candidate_summary.parquet/*.parquet').as_posix()]).fetchone()[0]
    if actual!=expected: raise RuntimeError(f'HF coverage mismatch {actual} != {expected}')
    telemetry.event('hf_scan_complete',stage='hf:scan',elapsed_scan_seconds=time.perf_counter()-started)
    return dict(surface_tasks=len(plan),expected_cell_targets=expected,actual_cell_targets=actual,
        execution_backend='shared_production')
