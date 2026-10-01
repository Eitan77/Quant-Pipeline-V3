from pathlib import Path
from hashlib import sha256
import json,os
import duckdb,numpy as np,pandas as pd,torch
import pyarrow.parquet as pq
from quant_pipeline.hashing import content_hash
from quant_pipeline.production.legacy_core import LegacyCoreAdapter
from quant_pipeline.data.source_manifest import build_production_source_manifest
from .engine import HFEngine
from .spec import SPEC,FEATURES,TARGETS,validate_pack
from .scan import atomic_frame,tasks,cell_count

def fingerprint(research):
    code={p.name:sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*') if p.suffix in {'.py','.json'}}
    shared=Path(__file__).parent.parent
    for relative in ('production/hf_execution.py','production/segmented_cuda.py','production/resource_policy.py','alpha_discovery/feature_autoscale.py'):
        path=shared/relative
        code[relative]=sha256(path.read_bytes()).hexdigest()
    return content_hash(dict(request=research,implementation=code))

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.partial');temp.write_text(json.dumps(value,indent=2,default=str),encoding='utf-8');os.replace(temp,path)

def preflight(research):
    settings=validate_pack(research['hf_intraday']); plan=tasks(settings)
    return dict(features=len(FEATURES),targets=len(TARGETS),exact_pairs=len(SPEC['pairs']),
                surface_tasks=len(plan),cell_targets=sum(cell_count(t)*len(TARGETS) for t in plan),
                fingerprint=fingerprint(research),settings=settings,production_launched=False)

def load_daily_eligibility(core,start,end):
    """Known before today's open, including eligible names with no bars today."""
    source=core.config.source; universe=core.config.universe
    with duckdb.connect(source.duckdb_path,read_only=True) as con:
        # Ticker changes share one model/history axis. This label is only a
        # deterministic fallback; emitted symbols come from each observed bar.
        names=con.execute(f"SELECT security_id,min(symbol) AS symbol FROM {source.security_master_table} WHERE symbol NOT IN ('SPY','QQQ') GROUP BY security_id ORDER BY security_id").fetchdf()
        eligibility=con.execute(f'''WITH daily AS (
            SELECT security_id,session_date,arg_max(close,bar_start_ts_utc) AS session_close,
                sum(coalesce(vwap,close)*volume) AS dollar_volume
            FROM {source.bars_1m_raw_table} WHERE session_date BETWEEN ? AND ? GROUP BY 1,2
        ), history AS (SELECT *,
            median(dollar_volume) OVER (PARTITION BY security_id ORDER BY session_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS prior20_dv,
            count(dollar_volume) OVER (PARTITION BY security_id ORDER BY session_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS prior20_count
            FROM daily)
        SELECT m.security_id,m.session_date,coalesce(m.in_universe
            AND h.session_close>=? AND h.prior20_dv>=? AND h.prior20_count=20,false) AS eligible
        FROM {source.membership_table} m ASOF LEFT JOIN history h
            ON m.security_id=h.security_id AND m.session_date>h.session_date
        WHERE m.session_date BETWEEN ? AND ?''',
            [start,end,float(universe['minimum_price']),float(universe['minimum_prior_20d_median_dollar_volume']),start,end]).fetchdf()
    return names,eligibility

def regular_day(frame,market_open,market_close):
    starts=pd.to_datetime(frame.bar_start_ts_utc,utc=True)
    ends=starts+pd.Timedelta(minutes=1)
    available=pd.to_datetime(frame.availability_ts_utc,utc=True) if 'availability_ts_utc' in frame else ends
    return frame.loc[(starts>=market_open)&(ends<=market_close)&(available<=market_close)].copy()

def build_artifacts(root,research,allowed_fingerprints):
    """Validate completed sessions without replaying their causal feature state."""
    from quant_pipeline.alpha_discovery.data.calendar import schedule
    dates=[str(d)[:10] for d in schedule(**research['periods']['discovery']).session_date]
    actual=sorted(p.stem for p in (root/'build_checkpoints').glob('*.json'))
    if actual!=dates: raise RuntimeError('HF build session coverage is incomplete')
    paths=[]; rows=0
    for date in dates:
        marker=root/'build_checkpoints'/f'{date}.json'
        if json.loads(marker.read_text())['fingerprint'] not in allowed_fingerprints:
            raise RuntimeError('HF build identity mismatch')
        observation=root/'observations'/f'{date}.parquet'
        values=root/'feature_values'/f'{date}.parquet'
        obs=pq.read_metadata(observation); features=pq.read_metadata(values)
        if obs.num_rows!=features.num_rows: raise RuntimeError('HF feature/target row mismatch')
        if not set(TARGETS).union(f'q_{key}' for key in FEATURES).issubset(obs.schema.names):
            raise RuntimeError('HF observation columns are incomplete')
        if not set(FEATURES).issubset(features.schema.names): raise RuntimeError('HF feature columns are incomplete')
        rows+=obs.num_rows
        paths.extend((marker,observation,values,root/'observations'/f'{date}.models.npz',root/'peer_models'/f'{date}.parquet'))
    paths.extend(root/name for name in ('model_coverage.parquet','finite_coverage.parquet','feature_registry.parquet','target_registry.parquet'))
    if rows==0: raise RuntimeError('No eligible HF discovery observations')
    signature=[dict(path=p.relative_to(root).as_posix(),size=p.stat().st_size,mtime=p.stat().st_mtime_ns) for p in paths]
    return dict(sessions=len(dates),observations=rows,artifacts=signature)

def completed_build(root,research,ident,source_hash):
    path=root/'build_complete.json'
    if not path.exists(): return None
    manifest=json.loads(path.read_text())
    if manifest['fingerprint']!=ident or manifest['source_manifest_hash']!=source_hash:
        raise RuntimeError('HF completed build identity changed')
    actual=build_artifacts(root,research,manifest['build_fingerprints'])
    if any(actual[key]!=manifest[key] for key in actual): raise RuntimeError('HF completed build artifacts changed')
    return manifest

def finish_hf(root,research,machine,settings,device,telemetry,observed,source_hash):
    from quant_pipeline.production.hf_execution import execute_hf
    coverage=pd.read_parquet(root/'finite_coverage.parquet').iloc[0]
    missing=[key for key in (*FEATURES,*TARGETS) if coverage[key]==0]
    if missing: raise RuntimeError(f'HF scan blocked: zero finite coverage for {missing}')
    metrics=execute_hf(root,settings,device,telemetry,machine)
    manifest=preflight(research)|metrics|dict(production_launched=True,observations=observed,
        replication_accessed=False,final_holdout_accessed=False,execution_model=False,
        output_format='partitioned_parquet_datasets',source_manifest_hash=source_hash)
    write_json(root/'EVIDENCE_COMPLETE.json',manifest)
    return dict(evidence_complete=True,mandatory_coverage_complete=True,**metrics)

def run_hf(research,machine,repo_root,telemetry):
    from quant_pipeline.production.state_helpers import validate_discovery_subrange
    from quant_pipeline.config import DISCOVERY_ENVELOPE
    validate_discovery_subrange(research['periods']['discovery'],DISCOVERY_ENVELOPE)
    if research.get('allow_replication_access') or research.get('allow_final_holdout_access'):
        raise PermissionError('HF discovery cannot access sealed periods')
    settings=validate_pack(research['hf_intraday']);root=Path(machine['run_root'])/research['run_name']
    ident=fingerprint(research);identity=root/'hf_identity.json'
    if identity.exists() and json.loads(identity.read_text())['fingerprint']!=ident:
        raise RuntimeError('HF request or implementation changed; use a new run name')
    write_json(identity,dict(fingerprint=ident))
    source=build_production_source_manifest(data_root=Path(machine['data_root']),repo_root=repo_root)
    source_path=root/'source_manifest.json'
    if source_path.exists() and json.loads(source_path.read_text())['source_manifest_hash']!=source['source_manifest_hash']:
        raise RuntimeError('HF sources changed; use a new run name')
    write_json(source_path,source)
    device=machine.get('gpu_device','cuda:0') if torch.cuda.is_available() else 'cpu'
    reused=completed_build(root,research,ident,source['source_manifest_hash'])
    if reused is not None:
        telemetry.event('hf_build_reused',stage='hf:prepare-scan',sessions=reused['sessions'],observations=reused['observations'])
        return finish_hf(root,research,machine,settings,device,telemetry,reused['observations'],source['source_manifest_hash'])
    atomic_frame(pd.DataFrame(SPEC['features']).assign(grid='intraday_1m',availability='completed_minute_close',price_basis='split_consistent'),root/'feature_registry.parquet')
    atomic_frame(pd.DataFrame(SPEC['targets']).assign(grid='intraday_1m',entry_reference='C_t',same_session=True),root/'target_registry.parquet')
    prep=dict(research)
    prep['external_smoke']=dict(decision_grids={'intraday_1m':True,'intraday_5m':False,'daily_close':False,'preclose_1555':False},
        warmup={'auto_derive_transitive_history':False,'snapshot_start':'2024-04-01','fail_if_full_coverage_warmup_missing':True})
    core=LegacyCoreAdapter(prep,machine,repo_root,source['source_manifest_hash'],telemetry).build_run()
    core.initialize()
    core.progress_callback=lambda unit,completed,expected:telemetry.progress(f'hf:core:{unit}',completed,expected)
    for stage in ('validate-config','snapshot','build-panel'):
        telemetry.event('hf_stage_start',stage='hf:'+stage); core.execute(stage)
    panel=root/'cache/calculation_panels/intraday_1m.parquet'
    con=duckdb.connect(); con.execute(f"SET memory_limit='{float(machine.get('duckdb_memory_limit_gb',18))}GB'")
    con.execute('SET temp_directory=?',[str(machine['duckdb_temp'])])
    threads=machine.get('duckdb_threads','auto')
    con.execute(f"SET threads={(os.cpu_count() or 1) if threads=='auto' else int(threads)}")
    panel_sql=panel.as_posix().replace("'","''")
    con.execute(f"CREATE VIEW hf_panel AS SELECT * FROM read_parquet('{panel_sql}')")
    names,daily_eligibility=load_daily_eligibility(core,'2024-04-01',research['periods']['discovery']['end'])
    sids=names.security_id.tolist(); lookup={sid:i for i,sid in enumerate(sids)}
    daily_eligibility['session_date']=daily_eligibility.session_date.astype(str).str[:10]
    if daily_eligibility.duplicated(['security_id','session_date']).any(): raise RuntimeError('Duplicate PIT eligibility keys')
    eligible_dates={date:group for date,group in daily_eligibility.groupby('session_date',sort=False)}
    sessions=[str(x[0])[:10] for x in con.execute('SELECT DISTINCT session_date FROM hf_panel ORDER BY 1').fetchall()]
    from quant_pipeline.alpha_discovery.data.calendar import schedule
    calendar=schedule('2024-04-01',research['periods']['discovery']['end'])
    bounds={str(row.session_date)[:10]:(row.market_open,row.market_close) for row in calendar.itertuples()}
    device=machine.get('gpu_device','cuda:0') if torch.cuda.is_available() else 'cpu'
    engine=HFEngine(settings,device,history_root=root/'cache/hf_history'); observed=0; model_coverage=[]
    for d,date in enumerate(sessions):
        df=con.execute('SELECT * FROM hf_panel WHERE session_date=?',[date]).fetchdf()
        if date not in bounds: raise RuntimeError(f'Non-session source date {date}')
        market_open,market_close=bounds[date]
        df=regular_day(df,market_open,market_close)
        minute=pd.to_datetime(df.bar_start_ts_utc,utc=True).dt.tz_convert('America/New_York')
        df['minute']=(minute.dt.hour*60+minute.dt.minute-570).astype(int)
        if df.duplicated(['security_id','minute']).any(): raise RuntimeError('Duplicate exact-minute source keys')
        benchmark=df[df.symbol=='SPY']; market=np.full(390,np.nan)
        market[benchmark.minute.to_numpy()]=benchmark.close.to_numpy()
        if benchmark.empty: raise RuntimeError(f'Missing SPY on {date}')
        arr={key:np.full((390,len(sids)),np.nan) for key in ('open','high','low','close','volume','vwap','trade_count','split_factor')}
        stocks=df[df.security_id.isin(lookup)]; ii=stocks.minute.to_numpy(); jj=stocks.security_id.map(lookup).to_numpy()
        for key in arr: arr[key][ii,jj]=stocks[key].to_numpy()
        bar_symbols=np.full(arr['close'].shape,'',dtype=object)
        bar_symbols[ii,jj]=stocks.symbol.to_numpy()
        close_local=market_close.tz_convert('America/New_York')
        arr['session_end_minute']=int(close_local.hour*60+close_local.minute-571)
        eligible=np.zeros(len(sids),bool)
        known=eligible_dates.get(date)
        if known is not None:
            known_ids=known.loc[known.eligible&known.security_id.isin(lookup),'security_id'].map(lookup).to_numpy(dtype=int)
            eligible[known_ids]=True
        f,y,q,models=engine.build(arr,market,eligible)
        if date<research['periods']['discovery']['start']:
            telemetry.progress('hf:warmup',d+1,len(sessions),session=date,device=device)
            continue
        destination=root/'observations'/f'{date}.parquet'
        day_marker=root/'build_checkpoints'/f'{date}.json'
        feature_destination=root/'feature_values'/destination.name
        model_destination=root/'observations'/f'{date}.models.npz'
        peer_destination=root/'peer_models'/destination.name
        if not (destination.exists() and feature_destination.exists() and model_destination.exists() and peer_destination.exists() and day_marker.exists()):
            t,i=np.where(eligible[None,:]&np.isfinite(arr['close']))
            rows=dict(symbol=bar_symbols[t,i],security_id=np.array(sids)[i],session_date=date,
                      month=date[:7],minute=t,decision_minute=t+571)
            rows.update({key:value[t,i] for key,value in y.items()})
            rows.update({f'q_{key}':value[t,i] for key,value in q.items()})
            atomic_frame(pd.DataFrame(rows),destination)
            # Persist causal values and model metadata independently of future labels.
            values=dict(symbol=bar_symbols[t,i],security_id=np.array(sids)[i],session_date=date,minute=t)
            values.update({key:value[t,i] for key,value in f.items()})
            atomic_frame(pd.DataFrame(values),feature_destination)
            # Save peer choices, weights and coefficients as audit-friendly tables.
            peer_rows=[]
            for stock,peer in enumerate(models['peers']):
                if peer is None: continue
                js,weights=peer
                for slot,(peerid,weight) in enumerate(zip(js,weights)):
                    lead1=models['lead1'][stock];lead2=models['lead2'][stock]
                    peer_rows.append(dict(security_id=sids[stock],peer_security_id=sids[peerid],weight=weight,
                        coef_1m=None if lead1 is None else lead1[slot],
                        coef_2m_current=None if lead2 is None else lead2[slot],
                        coef_2m_lag=None if lead2 is None else lead2[len(js)+slot]))
            atomic_frame(pd.DataFrame(peer_rows,columns=['security_id','peer_security_id','weight','coef_1m','coef_2m_current','coef_2m_lag']),peer_destination)
            np.savez_compressed(model_destination,beta=models['beta'],loadings=models['loadings'],security_id=np.array(sids))
            write_json(day_marker,dict(session_date=date,training_sessions=[x for x in sessions[:d][-settings['model_sessions']:]],
                                      tod_sessions=sessions[:d][-60:],fingerprint=ident))
        observed+=int((eligible[None,:]&np.isfinite(arr['close'])).sum())
        model_coverage.append(dict(session_date=date,eligible=int(eligible.sum()),beta=int(np.isfinite(models['beta']).sum()),
            pca=int(np.isfinite(models['loadings']).all(axis=1).sum()),peer_lead=int(sum(x is not None for x in models['lead1']))))
        telemetry.progress('hf:build',d+1,len(sessions),session=date,device=device)
    atomic_frame(pd.DataFrame(model_coverage),root/'model_coverage.parquet')
    if observed==0: raise RuntimeError('No eligible discovery observations; cannot publish completed evidence')
    if not list((root/'observations').glob('*.parquet')): raise RuntimeError('No governed HF discovery observations')
    # Feature/rank/target finite counts are diagnostic; unavailable items are never silently dropped.
    source_glob=(root/'observations'/'*.parquet').as_posix()
    finite=[f'count(*) FILTER(WHERE isfinite("q_{key}")) AS "{key}"' for key in FEATURES]
    finite += [f'count(*) FILTER(WHERE isfinite("{key}")) AS "{key}"' for key in TARGETS]
    coverage=con.execute('SELECT '+','.join(finite)+' FROM read_parquet(?)',[source_glob]).fetchdf()
    atomic_frame(coverage,root/'finite_coverage.parquet')
    # Release the 60-session feature state before DuckDB distribution scans.
    engine.close()
    del engine,df,stocks,arr,f,y,q
    import gc
    gc.collect()
    con.close()
    built=build_artifacts(root,research,{ident})
    write_json(root/'build_complete.json',built|dict(fingerprint=ident,build_fingerprints=[ident],source_manifest_hash=source['source_manifest_hash']))
    return finish_hf(root,research,machine,settings,device,telemetry,observed,source['source_manifest_hash'])
