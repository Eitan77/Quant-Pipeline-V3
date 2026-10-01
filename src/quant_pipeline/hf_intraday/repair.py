"""Targeted HF column repair using completed parent builds and causal warmup."""
from pathlib import Path
import json,shutil
import duckdb,numpy as np,pandas as pd
from .engine import HFEngine,FACTOR_FEATURES,EVENT_FEATURES,FACTOR_TARGETS
from .math import lag
from .spec import FEATURES,TARGETS
from .scan import atomic_frame

REPAIR_KEYS=('e1','u1','u2',*FACTOR_FEATURES,*EVENT_FEATURES)

def merge_repair(observations,values,f,y,q,minutes,indices):
    """Only assign affected columns; preserve row order and all other columns."""
    observations=observations.copy();values=values.copy()
    for key in FACTOR_FEATURES:values[key]=f[key][minutes,indices]
    for key in (*FACTOR_FEATURES,*EVENT_FEATURES):observations['q_'+key]=q[key][minutes,indices]
    for key in FACTOR_TARGETS:observations[key]=y[key][minutes,indices]
    return observations,values

def run_repair(root,research,machine,repo_root,telemetry,settings,device,ident,source):
    from .runner import (write_json,load_daily_eligibility,regular_day,build_artifacts,finish_hf)
    from quant_pipeline.production.legacy_core import LegacyCoreAdapter
    from quant_pipeline.alpha_discovery.data.calendar import schedule
    spec=research['hf_repair'];run_root=Path(machine['run_root'])
    if set(spec)!={'source_run','seed_run'}:raise ValueError('Unsupported repair selection')
    if any(Path(name).name!=name for name in spec.values()):raise ValueError('Repair sources must be owned run names')
    parent=run_root/spec['source_run'];seed=run_root/spec['seed_run']
    original=json.loads((parent/'build_complete.json').read_text())
    built=build_artifacts(parent,research,original['build_fingerprints'])
    if any(built[k]!=original[k] for k in built):raise RuntimeError('Parent build artifacts changed')
    if original['source_manifest_hash']!=source['source_manifest_hash']:raise RuntimeError('Repair source mismatch')
    import yaml
    prior=yaml.safe_load((parent/'request.yaml').read_text())
    current={k:v for k,v in research.items() if k not in ('run_name','hf_repair')}
    if current!={k:v for k,v in prior.items() if k!='run_name'}:raise RuntimeError('Repair changed the research contract')
    for name in ('feature_registry.parquet','target_registry.parquet'):
        shutil.copy2(parent/name,root/name)
    prep=dict(research);prep['external_smoke']=dict(decision_grids={'intraday_1m':True,'intraday_5m':False,'daily_close':False,'preclose_1555':False},warmup={'auto_derive_transitive_history':False,'snapshot_start':'2024-04-01','fail_if_full_coverage_warmup_missing':True})
    core=LegacyCoreAdapter(prep,machine,repo_root,source['source_manifest_hash']).build_run()
    names,known=load_daily_eligibility(core,'2024-04-01',research['periods']['discovery']['end'])
    sids=names.security_id.tolist();lookup={sid:i for i,sid in enumerate(sids)}
    axis=np.load(next((parent/'observations').glob('*.models.npz')))['security_id']
    if sids!=axis.tolist():raise RuntimeError('Repair security axes changed')
    known['session_date']=known.session_date.astype(str).str[:10]
    if known.duplicated(['security_id','session_date']).any():raise RuntimeError('Duplicate PIT keys')
    eligible_dates={date:group for date,group in known.groupby('session_date',sort=False)}
    con=duckdb.connect();con.execute(f"SET memory_limit='{machine.get('duckdb_memory_limit_gb',6)}GB'")
    con.execute('SET threads=?',[4]);con.execute('SET temp_directory=?',[str(machine['duckdb_temp'])])
    panel=(parent/'cache/calculation_panels/intraday_1m.parquet').as_posix().replace("'","''")
    con.execute(f"CREATE VIEW panel AS SELECT * FROM read_parquet('{panel}')")
    sessions=[str(x[0])[:10] for x in con.execute('SELECT DISTINCT session_date FROM panel ORDER BY 1').fetchall()]
    cal=schedule('2024-04-01',research['periods']['discovery']['end'])
    bounds={str(row.session_date)[:10]:(row.market_open,row.market_close) for row in cal.itertuples()}
    def day(date):
        frame=con.execute('SELECT * FROM panel WHERE session_date=?',[date]).fetchdf()
        frame=regular_day(frame,*bounds[date])
        clock=pd.to_datetime(frame.bar_start_ts_utc,utc=True).dt.tz_convert('America/New_York')
        frame['minute']=(clock.dt.hour*60+clock.dt.minute-570).astype(int)
        if frame.duplicated(['security_id','minute']).any():raise RuntimeError('Duplicate source minute')
        spy=frame[frame.symbol=='SPY'];market=np.full(390,np.nan);market[spy.minute]=spy.close
        if spy.empty:raise RuntimeError('Missing SPY')
        stocks=frame[frame.security_id.isin(lookup)];ii=stocks.minute.to_numpy();jj=stocks.security_id.map(lookup).to_numpy()
        bars={key:np.full((390,len(sids)),np.nan) for key in ('close','vwap','volume','split_factor')}
        for key in bars:bars[key][ii,jj]=stocks[key].to_numpy()
        eligible=np.zeros(len(sids),bool);k=eligible_dates.get(date)
        if k is not None:
            jj=k.loc[k.eligible&k.security_id.isin(lookup),'security_id'].map(lookup).to_numpy(dtype=int);eligible[jj]=True
        return bars,market,eligible
    seed_spec=json.loads((root/'repair_seed.json').read_text());count=seed_spec['completed_sessions']
    if sessions[count-1]!=seed_spec['last_session'] or seed_spec['source_manifest_hash']!=source['source_manifest_hash']:
        raise RuntimeError('Warmup seed provenance mismatch')
    if json.loads((seed/'hf_identity.json').read_text())['fingerprint']!=seed_spec['fingerprint']:
        raise RuntimeError('Warmup seed identity changed')
    if [record['name'] for record in seed_spec['files']]!=[f'{i:06d}.npy' for i in range(count-60,count)]:
        raise RuntimeError('Warmup seed session coverage changed')
    engine=HFEngine(settings,device,history_root=root/'cache/hf_history')
    seed_keys=seed_spec['history_keys'];columns=[seed_keys.index(key) for key in REPAIR_KEYS]
    for record in seed_spec['files']:
        path=seed/'cache/hf_history'/record['name'];stat=path.stat()
        if stat.st_size!=record['size'] or stat.st_mtime_ns!=record['mtime']:raise RuntimeError('Warmup seed artifact changed')
        array=np.load(path,mmap_mode='r')
        if array.shape!=(len(seed_keys),390,len(sids)):raise RuntimeError('Warmup seed shape changed')
        engine._save_history({key:array[column] for key,column in zip(REPAIR_KEYS,columns)})
        array._mmap.close()
    for date in sessions[count-settings['model_sessions']:count]:
        bars,market,eligible=day(date);valid=eligible[None,:]&np.isfinite(bars['close'])
        engine.returns.append(np.where(valid,bars['close']/lag(bars['close'])-1,np.nan))
        engine.markets.append(market/lag(market)-1)
        engine.liquidity.append(np.where(valid,bars['vwap']*bars['volume']*bars['split_factor'],np.nan))
    telemetry.event('hf_targeted_seed_reused',stage='hf:targeted-warmup',sessions=count,history_sessions=len(engine.history),reused_feature_values=97,reused_feature_bins=95,reused_targets=19)
    coverage=[];observed=0
    for d,date in enumerate(sessions[count:],start=count):
        bars,market,eligible=day(date);warmup=date<research['periods']['discovery']['start']
        obs=values=recovery=liq=None
        if not warmup:
            obs=pd.read_parquet(parent/'observations'/f'{date}.parquet');values=pd.read_parquet(parent/'feature_values'/f'{date}.parquet')
            if not obs[['security_id','minute']].equals(values[['security_id','minute']]):raise RuntimeError('Parent row keys differ')
            if obs.duplicated(['security_id','minute']).any():raise RuntimeError('Parent row keys duplicate')
            ii=obs.minute.to_numpy(dtype=int);jj=obs.security_id.map(lookup).to_numpy(dtype=int)
            expected=eligible[None,:]&np.isfinite(bars['close'])
            if len(obs)!=expected.sum() or not expected[ii,jj].all():raise RuntimeError('Repair observation alignment changed')
            recovery={key:np.full_like(bars['close'],np.nan) for key in EVENT_FEATURES}
            for key in EVENT_FEATURES:recovery[key][ii,jj]=values[key].to_numpy()
            liq=np.full(len(sids),np.nan)
            ranks=values.groupby('security_id',sort=False).liquidity_rank_20d.first()
            liq[[lookup[sid] for sid in ranks.index]]=ranks.to_numpy()
        f,y,q,models=engine.repair(bars,market,eligible,recovery,liq)
        if warmup:
            telemetry.progress('hf:targeted-warmup',d+1,len(sessions),session=date,device=device);continue
        original_beta=np.load(parent/'observations'/f'{date}.models.npz')['beta']
        np.testing.assert_allclose(models['beta'],original_beta,atol=1e-12,rtol=1e-10,equal_nan=True)
        obs,values=merge_repair(obs,values,f,y,q,ii,jj)
        marker=root/'build_checkpoints'/f'{date}.json'
        companions=[root/'observations'/f'{date}.parquet',root/'feature_values'/f'{date}.parquet',root/'observations'/f'{date}.models.npz',root/'peer_models'/f'{date}.parquet']
        if marker.exists() and json.loads(marker.read_text())['fingerprint']!=ident:
            raise RuntimeError('Repaired build identity changed')
        if not (marker.exists() and all(path.exists() for path in companions)):
            atomic_frame(obs,root/'observations'/f'{date}.parquet');atomic_frame(values,root/'feature_values'/f'{date}.parquet')
            np.savez_compressed(root/'observations'/f'{date}.models.npz',beta=original_beta,loadings=models['loadings'],security_id=np.array(sids))
            peer_rows=[]
            for stock,peer in enumerate(models['peers']):
                if peer is None:continue
                js,weights=peer
                for slot,(j,weight) in enumerate(zip(js,weights)):
                    a=models['lead1'][stock];b=models['lead2'][stock]
                    peer_rows.append(dict(security_id=sids[stock],peer_security_id=sids[j],weight=weight,coef_1m=None if a is None else a[slot],coef_2m_current=None if b is None else b[slot],coef_2m_lag=None if b is None else b[len(js)+slot]))
            atomic_frame(pd.DataFrame(peer_rows,columns=['security_id','peer_security_id','weight','coef_1m','coef_2m_current','coef_2m_lag']),root/'peer_models'/f'{date}.parquet')
            write_json(marker,dict(session_date=date,fingerprint=ident,training_sessions=sessions[:d][-settings['model_sessions']:],tod_sessions=sessions[:d][-60:],reused_from=parent.name,recomputed_feature_values=list(FACTOR_FEATURES),recomputed_feature_bins=list(FACTOR_FEATURES+EVENT_FEATURES),recomputed_targets=list(FACTOR_TARGETS)))
        observed+=len(obs);coverage.append(dict(session_date=date,eligible=int(eligible.sum()),beta=int(np.isfinite(original_beta).sum()),pca=int(np.isfinite(models['loadings']).all(1).sum()),peer_lead=int(sum(x is not None for x in models['lead1']))))
        telemetry.progress('hf:targeted-build',len(coverage),built['sessions'],session=date,device=device)
    engine.close();con.close()
    atomic_frame(pd.DataFrame(coverage),root/'model_coverage.parquet')
    with duckdb.connect() as check:
        fields=[f'count(*) FILTER(WHERE isfinite("q_{key}")) AS "{key}"' for key in FEATURES]+[f'count(*) FILTER(WHERE isfinite("{key}")) AS "{key}"' for key in TARGETS]
        finite=check.execute('SELECT '+','.join(fields)+' FROM read_parquet(?)',[(root/'observations/*.parquet').as_posix()]).fetchdf()
    atomic_frame(finite,root/'finite_coverage.parquet')
    built=build_artifacts(root,research,{ident})
    write_json(root/'build_complete.json',built|dict(fingerprint=ident,build_fingerprints=[ident],source_manifest_hash=source['source_manifest_hash']))
    return finish_hf(root,research,machine,settings,device,telemetry,observed,source['source_manifest_hash'])
