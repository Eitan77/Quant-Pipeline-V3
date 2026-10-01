"""Discovery-only strategy research. Outputs are separate from canonical evidence."""
import json, sys, time
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

ROOT = Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923')
OUT = ROOT/'research/intraday_strategy_20260928'
OUT.mkdir(parents=True, exist_ok=True)
COSTS = [-1, 0, 1, 2, 3, 4, 5]

def connection():
    con=duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    con.execute('SET threads=4')
    con.execute(f"SET temp_directory='{OUT.as_posix()}/tmp'")
    return con

def screen():
    c=connection()
    files=[str(p) for folder in ['dual_coarse_results','dual_fine_results','dual_exact_results']
           for p in (ROOT/folder/'intraday_5m').rglob('*.parquet')]
    c.read_parquet(files,union_by_name=True).create_view('surfaces')
    coverage=c.execute('select target_id,resolution,count(*) surfaces,sum(len(surface_counts)) cells from surfaces group by all order by 1,2').fetchdf()
    coverage.to_parquet(OUT/'coverage.parquet',index=False)
    print('COVERAGE',coverage.groupby('resolution')[['surfaces','cells']].sum().to_dict(),flush=True)
    # Retain every surface cell, including cells omitted by old minimum-frequency screens.
    c.execute(f"""COPY (SELECT pair_id,feature_a,feature_b,target_id,resolution,
       unnest(range(0,len(surface_counts))) cell,unnest(surface_counts) n,
       unnest(surface_sums)*10000 sum_bps,unnest(surface_sumsq)*1e8 sumsq_bps,
       n_obs FROM surfaces) TO '{(OUT/'all_cells.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    c.read_parquet(str(OUT/'all_cells.parquet')).create_view('cells')
    # Broad diversity: every target, both signs, and both absolute edge and participation.
    selected=[]
    for metric in ['abs(sum_bps/n)', 'abs(sum_bps)/sqrt(n)', 'abs(sum_bps)']:
        frame=c.execute(f"""WITH ranked AS (SELECT *,sum_bps/n gross_bps,
        sign(sum_bps)::int direction,row_number() OVER(PARTITION BY target_id,sign(sum_bps),
        split_part(feature_a,'__',1) ORDER BY {metric} DESC) family_rank FROM cells WHERE n>=1000)
        SELECT * FROM ranked WHERE family_rank<=1 QUALIFY row_number() OVER
        (PARTITION BY target_id,direction ORDER BY {metric} DESC)<=12""").fetchdf()
        selected.append(frame)
    f=pd.concat(selected).drop_duplicates(['pair_id','target_id','resolution','cell'])
    f.to_parquet(OUT/'surface_shortlist.parquet',index=False)
    # Include globally cancelled pairs with large local effects, without calling those maxima strategies.
    c.read_parquet(str(ROOT/'cell_specialist_summary.parquet')).create_view('specialists')
    cancellation=c.execute("""SELECT pair_id,max(list_max(best_positive_local_bps)-list_min(best_negative_local_bps)) spread
      FROM specialists WHERE target_id LIKE '%intraday_5m' GROUP BY 1 ORDER BY spread DESC LIMIT 25""").fetchdf()
    pairs=c.execute('select distinct pair_id,feature_a,feature_b from surfaces').fetchdf()
    # Resolve diverse pair set; evaluate all states/horizons/time groups, not just picked cells.
    scores=f.groupby('pair_id').agg(votes=('target_id','size')).reset_index().sort_values('votes',ascending=False)
    chosen=set(scores.head(100).pair_id)|set(cancellation.pair_id)
    pairs[pairs.pair_id.isin(chosen)].to_parquet(OUT/'pair_shortlist.parquet',index=False)
    meta={'evidence_id':json.loads((ROOT/'evidence/reader.json').read_text())['evidence_id'],
          'discovery':['2025-05-01','2026-04-30'],'cost_bps_per_side':COSTS,
          'surface_rows':int(coverage.surfaces.sum()),'surface_cells':int(coverage.cells.sum()),
          'pair_followups':len(chosen),'holdout_accessed':False}
    (OUT/'scope.json').write_text(json.dumps(meta,indent=2))
    print(meta,flush=True)
    print(f[f.target_id.str.contains('__raw__')].sort_values('gross_bps',ascending=False)[['feature_a','feature_b','target_id','resolution','cell','n','gross_bps']].head(12).to_string(index=False),flush=True)

def conditional():
    import torch
    from quant_pipeline.production.evidence_store import EvidenceReader
    from quant_pipeline.production.segmented_cuda import ResidentEvidenceGrid
    from quant_pipeline.production.segmented_scan import SegmentedMoments
    torch.set_num_threads(4)
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    resident=ResidentEvidenceGrid(reader,torch.device('cuda:0'),reserve_bytes=1500_000_000)
    # One exact time-of-day x month histogram supplies full-year and monthly screens.
    codes=resident.groups[resident.family_index['time_bucket']]*12+resident.groups[resident.family_index['month']]
    resident.groups=codes[None,:].contiguous()
    resident.family_index={'time_month':0}
    targets=[t for t in resident.targets if '__raw__' in t]
    pairs=pd.read_parquet(OUT/'pair_shortlist.parquet')
    chunks=[]
    for singles, definitions in [(True,[(f,f,'') for f in resident.features]),
                                 (False,list(pairs[['pair_id','feature_a','feature_b']].itertuples(index=False,name=None)))]:
        for start in range(0,len(definitions),16):
            subset=definitions[start:start+16]
            moment=SegmentedMoments(pairs=len(subset),targets=len(targets),groups=60,resolution=10,
                singles=singles,device='cuda:0',max_state_bytes=500_000_000,track_sumsq=False)
            task={'grouping_id':'time_month','group_start':0,'group_stop':60,'resolution':10}
            resident.accumulate([(task,moment)],[(a,) if singles else (a,b) for _,a,b in subset],targets,lambda:False)
            n=moment.n.cpu().numpy().reshape(len(targets),len(subset),5,12,-1)
            s=moment.s.cpu().numpy().reshape(n.shape)*1e4
            total=n.sum(axis=3); sums=s.sum(axis=3)
            ti,pi,gi,ci=np.where(total>=250)
            rows=[]
            for t,p,g,cell in zip(ti,pi,gi,ci):
                nn=total[t,p,g,cell];ss=sums[t,p,g,cell];direction=1 if ss>=0 else -1
                mn=n[t,p,g,:,cell];ms=s[t,p,g,:,cell]
                means=np.divide(ms,mn,out=np.zeros(12),where=mn>0)
                rows.append((subset[p][0],subset[p][1],subset[p][2],targets[t],10,int(cell),int(g),
                    int(nn),float(ss/nn),direction,int((mn>0).sum()),int(((means*direction>0)&(mn>0)).sum()),
                    float(np.median(means*direction)),mn.tolist(),ms.tolist()))
            chunks.append(pd.DataFrame(rows,columns=['pair_id','feature_a','feature_b','target_id','resolution','cell',
                'time_group','n','raw_bps','direction','months','positive_months','median_month_bps','month_n','month_sum_bps']))
            del moment
            print('CONDITIONAL', 'single' if singles else 'dual',min(start+16,len(definitions)),len(definitions),flush=True)
    result=pd.concat(chunks,ignore_index=True)
    result.to_parquet(OUT/'conditional_cells.parquet',index=False)
    print('CONDITIONAL COMPLETE',len(result),flush=True)

def prices():
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    c=duckdb.connect(source,read_only=True)
    c.execute("SET memory_limit='5GB'");c.execute('SET threads=4')
    c.execute(f"SET temp_directory='{OUT.as_posix()}/prices_tmp'")
    c.execute(f"""COPY (SELECT security_id,bar_start_ts_utc,open FROM bars_1m_raw
      WHERE session_date BETWEEN DATE '2025-05-01' AND DATE '2026-04-30'
      AND CAST(timezone('America/New_York',bar_start_ts_utc) AS TIME)>=TIME '09:30:00'
      AND CAST(timezone('America/New_York',bar_start_ts_utc) AS TIME)<TIME '16:00:00'
      AND open>0) TO '{(OUT/'raw_opens.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    print('RAW OPENS READY',flush=True)

def obs_arrays():
    import exchange_calendars as xc
    f=pd.read_parquet(ROOT/'cache/features/intraday_5m/observations.parquet')
    assert np.array_equal(f.observation_id.to_numpy(),np.arange(len(f)))
    dates=pd.to_datetime(f.session_date)
    assert str(dates.min().date())=='2025-05-01' and str(dates.max().date())=='2026-04-30'
    day,days=pd.factorize(dates,sort=True);sec,securities=pd.factorize(f.security_id,sort=True)
    t=f.decision_ts.astype('int64').to_numpy()//60_000_000_000
    # Arrow timestamps can have us resolution: normalize explicitly.
    t=f.decision_ts.to_numpy(dtype='datetime64[ns]').astype('int64')//60_000_000_000
    cal=xc.get_calendar('XNYS')
    closes=np.array([cal.session_close(d).value//60_000_000_000 for d in days])
    return f,t,day,days,sec,securities,closes

def allocate(indices,t,exits,sec,day,slots=10,seed=0):
    # Entry timestamp then a fixed date/security hash; no return-dependent tie breaking.
    h=((sec[indices].astype(np.uint64)+1)*np.uint64(2654435761)+(day[indices].astype(np.uint64)+seed)*np.uint64(2246822519))%np.uint64(4294967291)
    order=np.lexsort((h,t[indices]))
    free=np.full(slots,-1,dtype=np.int64);active=np.full(int(sec[indices].max(initial=0))+1,-1,dtype=np.int64)
    kept=[]
    for i in indices[order]:
        entry=t[i]+1
        if active[sec[i]]>entry:continue
        slot=int(np.argmin(free))
        if free[slot]>entry:continue
        kept.append(i);free[slot]=exits[i];active[sec[i]]=exits[i]
    return np.asarray(kept,dtype=np.int64)

def metrics(returns,days_index,total_days=251):
    daily=np.bincount(days_index,weights=returns,minlength=total_days)
    equity=np.cumprod(1+daily/10000)
    peak=np.maximum.accumulate(np.r_[1,equity])[1:]
    return {'bps_day':float(daily.mean()),'return_pct':float((equity[-1]-1)*100),
        'sharpe':float(daily.mean()/daily.std(ddof=1)*np.sqrt(252)) if daily.std()>0 else 0,
        'max_dd_pct':float((1-equity/peak).max()*100),'positive_days':int((daily>0).sum())}

def candidates():
    from quant_pipeline.production.evidence_store import EvidenceReader
    from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
    f=pd.read_parquet(OUT/'conditional_cells.parquet')
    f['edge']=f.raw_bps.abs();f['family']=f.feature_a.str.split('__').str[0]
    picks=[]
    for minimum_months,positive in [(9,7),(4,4)]:
        g=f[(f.months>=minimum_months)&(f.positive_months>=positive)&(f.n>=500)].copy()
        for cost in [0,2,6,10]:
            g['score']=(g.edge-cost)*np.minimum(g.n/251,80)
            p=g.sort_values('score',ascending=False).drop_duplicates(['target_id','direction','time_group','family'])
            picks.append(p.groupby(['target_id','direction','time_group'],sort=False).head(2 if minimum_months==9 else 1))
    selected=pd.concat(picks).drop_duplicates(['pair_id','target_id','cell','time_group']).copy()
    selected['candidate_id']=['C%04d'%i for i in range(len(selected))]
    selected.to_parquet(OUT/'candidate_definitions.parquet',index=False)
    print('CANDIDATE RULES',len(selected),flush=True)
    obs,t,day,days,sec,securities,closes=obs_arrays()
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    time_group=reader.read_groups('time_bucket',0,reader.rows)
    results=[];saved=[]
    for pair,group in selected.groupby('pair_id',sort=False):
        a=decode_packed_bins(reader.read_columns('bins',[group.feature_a.iloc[0]],0,reader.rows)[:,0],10)
        bname=group.feature_b.iloc[0]
        b=decode_packed_bins(reader.read_columns('bins',[bname],0,reader.rows)[:,0],10) if bname else None
        code=a if b is None else np.where((a>=0)&(b>=0),a*10+b,-1)
        for row in group.itertuples():
            y=reader.read_columns('targets',[row.target_id],0,reader.rows)[:,0]
            h=row.target_id.split('__')[0].replace('target_','')
            exits=closes[day]-5 if h=='eod' else t+1+int(h[:-1])
            mask=(code==row.cell)&(time_group==row.time_group)&np.isfinite(y)&(exits<=closes[day]-5)&(exits>t+1)
            ix=np.flatnonzero(mask)
            chosen=allocate(ix,t,exits,sec,day)
            gross=y[chosen]*row.direction*10000
            entry={'candidate_id':row.candidate_id,'signals':len(ix),'taken':len(chosen),'active_days':len(np.unique(day[chosen])),
                   'symbols':len(np.unique(sec[chosen])),'gross_bps':float(gross.mean()) if len(chosen) else 0}
            for cost in COSTS:
                entry.update({f'{k}_c{cost}':v for k,v in metrics((gross-2*cost)/10,day[chosen]).items()})
            results.append(entry)
            if len(chosen):saved.append(pd.DataFrame({'candidate_id':row.candidate_id,'observation_id':chosen,'bar_gross_bps':gross}))
        if len(results)%20< len(group):print('CAPITAL SCREEN',len(results),len(selected),flush=True)
    pd.DataFrame(results).to_parquet(OUT/'capital_screen.parquet',index=False)
    pd.concat(saved).to_parquet(OUT/'capital_screen_trades.parquet',index=False)
    print('CAPITAL SCREEN COMPLETE',flush=True)

def price_matrix():
    obs,t,day,days,sec,securities,closes=obs_arrays()
    del obs
    labels=pd.DataFrame({'security_id':securities,'sid':np.arange(len(securities))})
    dates=pd.DataFrame({'session_date':days.date,'did':np.arange(len(days)), 'open_min':closes-390})
    # Early closes still open at 09:30, not close minus 390.
    import exchange_calendars as xc
    cal=xc.get_calendar('XNYS')
    dates['open_min']=[cal.session_open(d).value//60_000_000_000 for d in days]
    c=connection();c.register('labels',labels);c.register('dates',dates)
    a=np.lib.format.open_memmap(OUT/'opens.npy',mode='w+',dtype=np.float64,shape=(len(days),len(securities),390))
    a[:]=np.nan
    cur=c.execute("""SELECT did,sid,(epoch(bar_start_ts_utc)/60-open_min)::int minute_index,open
      FROM read_parquet(?) JOIN labels USING(security_id)
      JOIN dates ON CAST(timezone('America/New_York',bar_start_ts_utc) AS DATE)=session_date""",[str(OUT/'raw_opens.parquet')])
    n=0
    for batch in cur.fetch_record_batch(250000):
        f=batch.to_pandas();valid=f.minute_index.between(0,389)
        f=f[valid];a[f.did.to_numpy(),f.sid.to_numpy(),f.minute_index.to_numpy()]=f.open.to_numpy();n+=len(f)
    a.flush()
    (OUT/'price_axes.json').write_text(json.dumps({'days':[str(x.date()) for x in days],
        'securities':list(securities),'open_minutes':dates.open_min.tolist(),'close_minutes':closes.tolist(),'rows':n}))
    print('PRICE MATRIX',n,a.shape,flush=True)

def fast_allocate(indices,t,exits,sec,day,slots=10,seed=0):
    h=((sec[indices].astype(np.uint64)+1)*np.uint64(2654435761)+(day[indices].astype(np.uint64)+seed)*np.uint64(2246822519))%np.uint64(4294967291)
    ordered=indices[np.lexsort((h,t[indices]))];entries=t[ordered]+1
    free=np.full(slots,-1,dtype=np.int64);active=np.full(int(sec[indices].max(initial=0))+1,-1,dtype=np.int64)
    kept=[];j=0
    while j<len(ordered):
        slot=int(np.argmin(free))
        if entries[j]<free[slot]:
            j=int(np.searchsorted(entries,free[slot],side='left'))
            if j>=len(ordered):break
        i=ordered[j];j+=1
        if active[sec[i]]>t[i]+1:continue
        kept.append(i);free[slot]=exits[i];active[sec[i]]=exits[i]
    return np.asarray(kept,dtype=np.int64)

def replay():
    from quant_pipeline.production.evidence_store import EvidenceReader
    from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
    defs=pd.read_parquet(OUT/'candidate_definitions.parquet');screen=pd.read_parquet(OUT/'capital_screen.parquet').merge(defs,on='candidate_id')
    # Retain all horizon families and both directions, as well as overall capital winners.
    chosen=[]
    for cost in [0,1,2,5]:
        g=screen[screen.active_days>=50].sort_values(f'bps_day_c{cost}',ascending=False)
        chosen.extend(g.head(20).candidate_id)
        chosen.extend(g.groupby(['target_id','direction']).head(2).candidate_id)
    chosen.extend(screen.sort_values('bps_day_c1',ascending=False).head(12).candidate_id)
    selected=defs[defs.candidate_id.isin(chosen)]
    selected.to_parquet(OUT/'replay_definitions.parquet',index=False)
    obs,t,day,days,sec,securities,closes=obs_arrays()
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes'])
    prices=np.load(OUT/'opens.npy',mmap_mode='r')
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    tg=reader.read_groups('time_bucket',0,reader.rows)
    rows=[];all_trades=[];all_events=[];seen={}
    entry_min=t+1-opens[day]
    entry_price=prices[day,sec,np.clip(entry_min,0,389)]
    for pair,group in selected.groupby('pair_id',sort=False):
        a=decode_packed_bins(reader.read_columns('bins',[group.feature_a.iloc[0]],0,reader.rows)[:,0],10)
        bname=group.feature_b.iloc[0];b=decode_packed_bins(reader.read_columns('bins',[bname],0,reader.rows)[:,0],10) if bname else None
        code=a if b is None else np.where((a>=0)&(b>=0),a*10+b,-1)
        for row in group.itertuples():
            horizon=row.target_id.split('__')[0].replace('target_','')
            exits=closes[day]-5 if horizon=='eod' else t+1+int(horizon[:-1])
            exit_min=exits-opens[day]
            xp=prices[day,sec,np.clip(exit_min,0,389)]
            mask=(code==row.cell)&(tg==row.time_group)&(exits<=closes[day]-5)&(exits>t+1)&np.isfinite(entry_price)&np.isfinite(xp)
            ix=np.flatnonzero(mask)
            from hashlib import sha256
            key=sha256(ix.tobytes()+str((horizon,row.direction)).encode()).hexdigest()
            if key in seen:
                rows.append({'candidate_id':row.candidate_id,'duplicate_of':seen[key]});continue
            seen[key]=row.candidate_id
            gross=row.direction*(xp[ix]/entry_price[ix]-1)*10000
            all_events.append(pd.DataFrame({'candidate_id':row.candidate_id,'observation_id':ix,'exit_minute':exits[ix],
                'gross_bps':gross,'entry_price':entry_price[ix],'exit_price':xp[ix]}))
            for slots in [5,10,25]:
                for seed in [0,1,2]:
                    selected_ix=fast_allocate(ix,t,exits,sec,day,slots,seed)
                    pnl=row.direction*(xp[selected_ix]/entry_price[selected_ix]-1)*10000
                    out={'candidate_id':row.candidate_id,'slots':slots,'seed':seed,'signals':len(ix),'trades':len(selected_ix),
                        'active_days':len(np.unique(day[selected_ix])),'symbols':len(np.unique(sec[selected_ix])),
                        'gross_bps':float(pnl.mean()) if len(pnl) else 0,'trades_day':len(selected_ix)/251}
                    for cost in COSTS:
                        out.update({f'{k}_c{cost}':v for k,v in metrics((pnl-2*cost)/slots,day[selected_ix]).items()})
                    rows.append(out)
                    if seed==0:all_trades.append(pd.DataFrame({'candidate_id':row.candidate_id,'slots':slots,'observation_id':selected_ix,'gross_bps':pnl}))
            if len(seen)%10==0:print('RAW REPLAY',len(seen),'unique of',len(selected),flush=True)
    pd.DataFrame(rows).to_parquet(OUT/'replay_results.parquet',index=False)
    pd.concat(all_events).to_parquet(OUT/'replay_events.parquet',index=False)
    pd.concat(all_trades).to_parquet(OUT/'replay_trades.parquet',index=False)
    print('REPLAY COMPLETE',len(seen),flush=True)

def ranks():
    from quant_pipeline.production.evidence_store import EvidenceReader
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    wanted=[f'{f}__30m__raw__intraday_5m' for f in ['distance_from_low','ema_distance','close_vs_vwap',
        'breakdown_distance','return_acceleration_halves','return_acceleration_thirds','p95_subreturn','parkinson_vol']]
    refs={}
    for meta in (ROOT/'cache/features/intraday_5m').glob('*.json'):
        m=json.loads(meta.read_text())
        for i,f in enumerate(m.get('columns',[])):
            if f in wanted:refs[f]=(meta.with_suffix('.npy'),i)
    values=[];checks={}
    for f in wanted:
        p,i=refs[f];v=np.load(p,mmap_mode='r')[:,i]
        corrected=f.startswith('ema_distance') and (OUT/'causal_ema.npy').exists()
        if corrected:v=np.load(OUT/'causal_ema.npy',mmap_mode='r')
        rank=pd.Series(v).groupby(t,sort=False).rank(method='average',pct=True).to_numpy(np.float32)
        bins=reader.read_columns('bins',[f],0,reader.rows)[:,0]
        valid=np.isfinite(rank)&(bins!=255)
        decoded=np.minimum((rank[valid]*10).astype(int),9)
        checks[f]={'valid':int(valid.sum()),'disagreements':int((decoded!=bins[valid]//15).sum())}
        checks[f]['corrected_feature']=corrected
        if not corrected:assert checks[f]['disagreements']==0
        values.append(rank);print('EXACT RANK',f,checks[f],flush=True)
    np.save(OUT/'fine_ranks.npy',np.column_stack(values))
    (OUT/'rank_checks.json').write_text(json.dumps(checks,indent=2))

def correct_ema():
    reader=json.loads((ROOT/'evidence/reader.json').read_text())
    out=np.lib.format.open_memmap(OUT/'causal_ema.npy',mode='w+',dtype=np.float32,shape=(reader['grids']['intraday_5m']['rows'],))
    out[:]=np.nan;total=0
    paths=sorted((ROOT/'cache/local_feature_panels/intraday_5m').glob('security_id=*'))
    for count,path in enumerate(paths):
        f=pd.read_parquet(path,columns=['decision_ts','session_date','close','emit','observation_id'])
        f=f[pd.to_datetime(f.session_date).between('2025-05-01','2026-04-30')].sort_values('decision_ts',kind='stable')
        p=f.close.astype(float)
        ema=p.groupby(f.session_date,sort=False).ewm(span=30,adjust=False,min_periods=2).mean().reset_index(level=0,drop=True)
        values=p/ema-1
        keep=f.emit & (f.observation_id>=0)&~f.observation_id.duplicated()
        out[f.loc[keep,'observation_id'].to_numpy(np.int64)]=values.loc[keep].to_numpy(np.float32)
        total+=int(keep.sum())
        if count%50==0:print('CAUSAL EMA',count,len(paths),flush=True)
    out.flush();assert total==len(out),(total,len(out))
    print('CAUSAL EMA COMPLETE',total,flush=True)

def refine():
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes'])
    prices=np.load(OUT/'opens.npy',mmap_mode='r');rank=np.load(OUT/'fine_ranks.npy',mmap_mode='r')
    minute=t-opens[day];entry_price=prices[day,sec,np.clip(minute+1,0,389)]
    horizons=[1,2,5,10,15,30,60,120,240,'eod']
    exits={h:closes[day]-5 if h=='eod' else t+1+h for h in horizons}
    intervals=[(5,20),(20,60),(5,60),(60,150),(150,270),(270,385),(5,385)]
    rows=[];counter=0
    for family,col,other,orientation,direction in [('low_ema_long',0,1,1,1),('vwap_ema_long',2,1,1,1),
            ('vwap_ema_short',2,1,-1,-1),('breakdown_accel_short',3,4,-1,-1),
            ('accel_reversal_short',4,5,1,-1),('p95_vol_short',6,7,-1,-1)]:
        for a in [.8,.9,.95,.98,.99]:
            for b in [.2,.1,.05,.02]:
                ix=np.flatnonzero((rank[:,col]>=a)&(rank[:,other]<b)) if orientation==1 else np.flatnonzero((rank[:,col]<1-a)&(rank[:,other]>=1-b))
                if len(ix)<500:continue
                for lo,hi in intervals:
                    base=ix[(minute[ix]>=lo)&(minute[ix]<hi)&np.isfinite(entry_price[ix])]
                    for h in horizons:
                        xp=prices[day[base],sec[base],np.clip(exits[h][base]-opens[day[base]],0,389)]
                        valid=np.isfinite(xp)&(exits[h][base]<=closes[day[base]]-5)&(exits[h][base]>t[base]+1)
                        signals=base[valid]
                        if len(signals)<250:continue
                        taken=fast_allocate(signals,t,exits[h],sec,day,10,0)
                        if len(taken)<100:continue
                        pnl=direction*(prices[day[taken],sec[taken],exits[h][taken]-opens[day[taken]]]/entry_price[taken]-1)*10000
                        counter+=1
                        out={'refine_id':f'R{counter:05d}','family':family,'a':a,'b':b,'lo':lo,'hi':hi,'horizon':str(h),
                            'direction':direction,'signals':len(signals),'trades':len(taken),'active_days':len(np.unique(day[taken])),
                            'gross_bps':float(pnl.mean()),'trades_day':len(taken)/251}
                        for cost in COSTS:out.update({f'{k}_c{cost}':v for k,v in metrics((pnl-2*cost)/10,day[taken]).items()})
                        rows.append(out)
            print('FINE TAIL',family,a,len(rows),flush=True)
    pd.DataFrame(rows).to_parquet(OUT/'refinement_results.parquet',index=False)
    print('REFINEMENT COMPLETE',len(rows),flush=True)

def specialists():
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    definitions=pd.read_parquet(OUT/'candidate_definitions.parquet').set_index('candidate_id')
    events=pd.read_parquet(OUT/'replay_events.parquet')
    rows=[];ticker_rows=[];saved=[]
    for cid,f in events.groupby('candidate_id',sort=False):
        rule=definitions.loc[cid]
        if 'ema_distance' in rule.feature_a+rule.feature_b:continue
        ix=f.observation_id.to_numpy(np.int64)
        ex=np.zeros(len(t),np.int64);ex[ix]=f.exit_minute.to_numpy(np.int64)
        gross=np.zeros(len(t));gross[ix]=f.gross_bps
        independent=fast_allocate(ix,t,ex,sec,day,len(securities),0)
        ds=pd.DataFrame({'sid':sec[independent],'day':day[independent],'pnl':gross[independent]})
        symbol=ds.groupby('sid').agg(n=('pnl','size'),days=('day','nunique'),gross=('pnl','mean'),sd=('pnl','std')).reset_index()
        symbol['candidate_id']=cid;symbol['security_id']=[securities[i] for i in symbol.sid]
        ticker_rows.append(symbol)
        daily_n=np.zeros((len(days),len(securities)));daily_sum=np.zeros_like(daily_n)
        np.add.at(daily_n,(day[independent],sec[independent]),1)
        np.add.at(daily_sum,(day[independent],sec[independent]),gross[independent])
        cn=np.vstack([np.zeros((1,len(securities))),daily_n.cumsum(axis=0)])
        cs=np.vstack([np.zeros((1,len(securities))),daily_sum.cumsum(axis=0)])
        modes=[('all',np.ones(len(ix),bool))]
        for top in [5,10,25]:
            eligible=symbol[(symbol.n>=30)&(symbol.days>=20)].sort_values('gross',ascending=False).head(top)
            modes.append((f'fixed_top{top}',np.isin(sec[ix],eligible.sid)))
        for window in [40,80]:
            past_n=cn[np.arange(len(days))]-cn[np.maximum(0,np.arange(len(days))-window)]
            past_s=cs[np.arange(len(days))]-cs[np.maximum(0,np.arange(len(days))-window)]
            mean=np.divide(past_s,past_n,out=np.zeros_like(past_s),where=past_n>0)
            for threshold in [0,4,10]:
                allowed=(past_n>=5)&(mean>=threshold)
                modes.append((f'rolling{window}_min5_edge{threshold}',allowed[day[ix],sec[ix]]))
        for name,mask in modes:
            signals=ix[mask]
            if len(signals)<100:continue
            for slots in [5,10]:
                chosen=fast_allocate(signals,t,ex,sec,day,slots,0)
                pnl=gross[chosen]
                if len(chosen)<50:continue
                out={'candidate_id':cid,'overlay':name,'slots':slots,'trades':len(chosen),'trades_day':len(chosen)/251,
                    'days':len(np.unique(day[chosen])),'symbols':len(np.unique(sec[chosen])),'gross_bps':float(pnl.mean())}
                for cost in COSTS:out.update({f'{k}_c{cost}':v for k,v in metrics((pnl-2*cost)/slots,day[chosen]).items()})
                rows.append(out)
                if out['bps_day_c1']>1.5:
                    saved.append(pd.DataFrame({'candidate_id':cid,'overlay':name,'slots':slots,'observation_id':chosen,'gross_bps':pnl}))
        print('SPECIALIST',cid,flush=True)
    pd.concat(ticker_rows).to_parquet(OUT/'ticker_diagnostics.parquet',index=False)
    pd.DataFrame(rows).to_parquet(OUT/'specialist_results.parquet',index=False)
    pd.concat(saved).to_parquet(OUT/'specialist_trades.parquet',index=False)

def audit_finalists():
    from quant_pipeline.alpha_discovery.features.base import FeatureBuilder
    from quant_pipeline.alpha_discovery.models import CompiledFeatureSpec,TimeScale
    obs=pd.read_parquet(ROOT/'cache/features/intraday_5m/observations.parquet')
    definitions=pd.read_parquet(OUT/'candidate_definitions.parquet').set_index('candidate_id')
    trades=pd.read_parquet(OUT/'replay_trades.parquet')
    registry=pd.read_parquet(ROOT/'feature_registry.parquet').set_index('feature_id')
    refs={}
    for meta in (ROOT/'cache/features/intraday_5m').glob('*.json'):
        m=json.loads(meta.read_text())
        for i,f in enumerate(m.get('columns',[])):refs[f]=(meta.with_suffix('.npy'),i)
    checks=[]
    for cid in ['C0401','C0412','C0033','C0065']:
        rule=definitions.loc[cid];subset=trades[(trades.candidate_id==cid)&(trades.slots==5)]
        for pos in [0,len(subset)//2,len(subset)-1]:
            oid=int(subset.iloc[pos].observation_id);o=obs.iloc[oid];sid=o.security_id
            f=pd.read_parquet(ROOT/f'cache/local_feature_panels/intraday_5m/security_id={sid}')
            # Truncate all future observations before recomputing the signal.
            f=f[(f.session_date==o.session_date)&(f.decision_ts<=o.decision_ts)].copy()
            f['security_id']=sid
            builder=FeatureBuilder(f)
            for feature in [rule.feature_a,rule.feature_b]:
                record=registry.loc[feature].to_dict();parameters=json.loads(record.pop('parameters'))
                label=record.pop('scale');scale=TimeScale('minutes',int(label[:-1]),label)
                spec=CompiledFeatureSpec(feature_id=feature,scale=scale,parameters=parameters,**record)
                v=builder.build(spec);idx=builder.frame.index[builder.frame.observation_id.eq(oid)][0]
                expected=float(v.loc[idx]);p,col=refs[feature];cached=float(np.load(p,mmap_mode='r')[oid,col])
                checks.append({'candidate_id':cid,'observation_id':oid,'feature':feature,'cached':cached,
                    'prefix_recomputed':expected,'matches':bool(np.isclose(cached,expected,rtol=1e-4,atol=1e-7,equal_nan=True))})
        print('PREFIX AUDIT',cid,flush=True)
    (OUT/'finalist_feature_audit.json').write_text(json.dumps(checks,indent=2))
    print('AUDIT',sum(c['matches'] for c in checks),len(checks),flush=True)

def portfolios():
    obs,t,day,days,sec,securities,closes=obs_arrays()
    events=pd.read_parquet(OUT/'replay_events.parquet')
    ticks=pd.read_parquet(OUT/'ticker_diagnostics.parquet')
    eligible=ticks[(ticks.candidate_id=='C0033')&(ticks.n>=30)&(ticks.days>=20)].sort_values('gross',ascending=False)
    top10=eligible.head(10).security_id.tolist()
    symbols=pd.read_parquet(Path(__file__).resolve().parents[1]/'reference/security_master.parquet')[['security_id','symbol']].drop_duplicates('security_id')
    topnames=symbols.set_index('security_id').loc[top10].symbol.tolist()
    base=events[events.candidate_id=='C0033'].copy();base['sid']=sec[base.observation_id];base['day']=day[base.observation_id]
    ex=np.zeros(len(t),np.int64);ex[base.observation_id]=base.exit_minute
    independent=fast_allocate(base.observation_id.to_numpy(),t,ex,sec,day,len(securities))
    pre=base[base.observation_id.isin(independent)&(base.day<126)]
    early=pre.groupby('sid').agg(n=('gross_bps','size'),days=('day','nunique'),gross=('gross_bps','mean'))
    first_top=early[(early.n>=10)&(early.days>=10)].sort_values('gross',ascending=False).head(10).index
    pools={
        'ticker10_short':base[base.sid.isin([list(securities).index(x) for x in top10])],
        'broad_breakdown_short':events[events.candidate_id=='C0401'],
        'acceleration_60m_short':events[events.candidate_id=='C0412'],
        'ticker10_early_selected':base[base.sid.isin(first_top)&(base.day>=126)],
    }
    pools['combined']=pd.concat([pools['ticker10_short'],pools['broad_breakdown_short'],pools['acceleration_60m_short']],ignore_index=True)
    result=[];trades=[]
    for name,pool in pools.items():
        # All these finalists are short; first signal wins. Same-symbol conflicts are excluded.
        pool=pool.sort_values(['observation_id','candidate_id']).drop_duplicates('observation_id')
        ix=pool.observation_id.to_numpy(np.int64);ex=np.zeros(len(t),np.int64);ex[ix]=pool.exit_minute
        gross=np.zeros(len(t));gross[ix]=pool.gross_bps
        for slots in [5,10]:
            for seed in [0,1,2,3,4]:
                taken=fast_allocate(ix,t,ex,sec,day,slots,seed);pnl=gross[taken]
                out={'portfolio':name,'slots':slots,'seed':seed,'trades':len(taken),'trades_day':len(taken)/251,
                    'active_days':len(np.unique(day[taken])),'symbols':len(np.unique(sec[taken])),
                    'gross_bps':float(pnl.mean()),'median_hold_minutes':float(np.median(ex[taken]-t[taken]-1))}
                for cost in COSTS:out.update({f'{k}_c{cost}':v for k,v in metrics((pnl-2*cost)/slots,day[taken]).items()})
                result.append(out)
                if seed==0:
                    f=pool.set_index('observation_id').loc[taken].reset_index()[['candidate_id','observation_id','exit_minute','gross_bps','entry_price','exit_price']]
                    f['portfolio']=name;f['slots']=slots;f['session_date']=days[day[taken]].to_numpy()
                    f['security_id']=securities[sec[taken]];f['entry_minute']=t[taken]+1
                    f=f.merge(symbols,on='security_id',validate='many_to_one');trades.append(f)
    frame=pd.DataFrame(result);frame.to_parquet(OUT/'portfolio_results.parquet',index=False)
    pd.concat(trades).to_parquet(OUT/'portfolio_trades.parquet',index=False)
    (OUT/'frozen_tickers.json').write_text(json.dumps({'full_discovery_selected':topnames,
        'first_126_sessions_selected':symbols.set_index('security_id').loc[securities[first_top]].symbol.tolist()},indent=2))
    print(frame[frame.seed==0][['portfolio','slots','trades','gross_bps','bps_day_c1','return_pct_c1','sharpe_c1','max_dd_pct_c1']].to_string(index=False),flush=True)

def finish():
    obs,t,day,days,sec,securities,closes=obs_arrays()
    rank=np.load(OUT/'fine_ranks.npy',mmap_mode='r');prices=np.load(OUT/'opens.npy',mmap_mode='r')
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);minute=t-opens[day]
    definitions=pd.read_parquet(OUT/'refinement_results.parquet').set_index('refine_id')
    pools={};rules={}
    for rid in ['R00530','R00965','R00567','R00621']:
        r=definitions.loc[rid];h=int(r.horizon);ex=t+1+h
        if r.family=='breakdown_accel_short':mask=(rank[:,3]<1-r.a)&(rank[:,4]>=1-r.b)
        else:mask=(rank[:,4]>=r.a)&(rank[:,5]<r.b)
        ix=np.flatnonzero(mask&(minute>=r.lo)&(minute<r.hi)&(ex<=closes[day]-5))
        ep=prices[day[ix],sec[ix],minute[ix]+1];xp=prices[day[ix],sec[ix],ex[ix]-opens[day[ix]]]
        good=np.isfinite(ep)&np.isfinite(xp);ix=ix[good];ep=ep[good];xp=xp[good]
        pools[rid]=pd.DataFrame({'observation_id':ix,'exit_minute':ex[ix],'entry_price':ep,'exit_price':xp,'gross_bps':(1-xp/ep)*10000,'rule':rid})
        rules[rid]=r.to_dict()
    pools['combined_refined']=pd.concat([pools['R00530'],pools['R00965']]).sort_values('rule').drop_duplicates('observation_id')
    results=[];trades=[]
    for name,p in pools.items():
        ix=p.observation_id.to_numpy();ex=np.zeros(len(t),np.int64);ex[ix]=p.exit_minute
        gross=np.zeros(len(t));gross[ix]=p.gross_bps
        for slots in [5,10,25]:
            for seed in range(5):
                chosen=fast_allocate(ix,t,ex,sec,day,slots,seed);pnl=gross[chosen]
                result={'rule':name,'slots':slots,'seed':seed,'trades':len(chosen),'trades_day':len(chosen)/251,'active_days':len(np.unique(day[chosen])),
                        'symbols':len(np.unique(sec[chosen])),'gross_bps':float(pnl.mean())}
                for c in COSTS:result.update({f'{k}_c{c}':v for k,v in metrics((pnl-2*c)/slots,day[chosen]).items()})
                results.append(result)
                if seed==0:
                    f=p.set_index('observation_id').loc[chosen].reset_index();f['portfolio']=name;f['slots']=slots
                    f['session_date']=days[day[chosen]].to_numpy();f['security_id']=securities[sec[chosen]];f['entry_minute']=t[chosen]+1
                    trades.append(f)
    results=pd.DataFrame(results);results.to_parquet(OUT/'final_results.parquet',index=False)
    trade=pd.concat(trades);trade.to_parquet(OUT/'final_trades.parquet',index=False)
    (OUT/'final_rules.json').write_text(json.dumps(rules,indent=2,default=str))
    diagnostics=[]
    for (name,slots),f in trade.groupby(['portfolio','slots']):
        pnl=f.gross_bps.to_numpy()-2;daily=f.assign(net=pnl/slots).groupby('session_date').net.sum()
        monthly=daily.groupby(pd.to_datetime(daily.index).strftime('%Y-%m')).sum()
        symbol=f.assign(net=pnl).groupby('security_id').net.sum().sort_values(ascending=False)
        positive_total=symbol.clip(lower=0).sum()
        diagnostics.append({'rule':name,'slots':int(slots),'positive_months':int((monthly>0).sum()),
            'monthly_bps':monthly.to_dict(),'win_rate':float((pnl>0).mean()),'median_net_bps':float(np.median(pnl)),
            'p05_net_bps':float(np.quantile(pnl,.05)),'p95_net_bps':float(np.quantile(pnl,.95)),
            'top5_positive_profit_share':float(symbol.head(5).sum()/positive_total),
            'bps_day_excluding_best5':float((daily.sum()-daily.nlargest(5).sum())/251),
            'first_half_gross':float(f[pd.to_datetime(f.session_date)<'2025-11-01'].gross_bps.mean()),
            'second_half_gross':float(f[pd.to_datetime(f.session_date)>='2025-11-01'].gross_bps.mean())})
        assert (f.exit_minute>f.entry_minute).all()
        ix=f.observation_id.to_numpy();assert (f.exit_minute.to_numpy()<=closes[day[ix]]-5).all()
        # Verify the recorded allocation never overlaps the same security.
        for _,s in f.sort_values('entry_minute').groupby('security_id'):
            assert (s.entry_minute.to_numpy()[1:]>=s.exit_minute.to_numpy()[:-1]).all()
    (OUT/'final_diagnostics.json').write_text(json.dumps(diagnostics,indent=2))
    print(results.groupby(['rule','slots'])[['bps_day_c1','return_pct_c1','sharpe_c1','max_dd_pct_c1','trades_day']].mean().round(3).to_string(),flush=True)

def report():
    final=pd.read_parquet(OUT/'final_results.parquet');old=pd.read_parquet(OUT/'portfolio_results.parquet')
    obs,t,day,days,sec,securities,closes=obs_arrays();prices=np.load(OUT/'opens.npy',mmap_mode='r')
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes'])
    trades=pd.read_parquet(OUT/'final_trades.parquet');delay=[]
    for name in ['R00530','R00965','combined_refined']:
        f=trades[(trades.portfolio==name)&(trades.slots==10)];ix=f.observation_id.to_numpy()
        for extra in [0,1,2]:
            ep=prices[day[ix],sec[ix],t[ix]+1+extra-opens[day[ix]]]
            valid=np.isfinite(ep)
            pnl=(1-f.exit_price.to_numpy()[valid]/ep[valid])*10000
            delay.append({'rule':name,'extra_entry_delay_minutes':extra,'trades':int(valid.sum()),
                **metrics((pnl-2)/10,day[ix][valid])})
    (OUT/'delay_sensitivity.json').write_text(json.dumps(delay,indent=2))
    chosen=[('Opening short, 5 slots',final[(final.rule=='R00530')&(final.slots==5)]),
            ('Combined short, 10 slots',final[(final.rule=='combined_refined')&(final.slots==10)]),
            ('30-minute short, 10 slots',final[(final.rule=='R00965')&(final.slots==10)]),
            ('Ticker-selected short, 5 slots',old[(old.portfolio=='ticker10_short')&(old.slots==5)])]
    lines=['# V3 intraday strategy discovery — 2026-09-28','',
      '**Result:** Freeze the combined opening-hour short strategy as the main diversified candidate; retain the 240-minute component for higher-cost execution. All results are discovery-only raw-bar execution models, not proven OOS performance.','',
      '## Cost comparison','',
      'Modeled compounded return over 251 discovery sessions, averaged over five deterministic entry tie orders. Costs are exactly the requested bps per side; net trade bps = gross minus twice the stated cost. No extra spread/slippage is silently imposed.','',
      '| Strategy | -1 | 0 | 1 | 2 | 3 | 4 | 5 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for label,f in chosen:lines.append('|'+label+'|'+'|'.join(f'{f[f"return_pct_c{c}"].mean():.2f}%' for c in COSTS)+'|')
    lines+=['','## Exact main rules','',
      '- Universe: the run\'s point-in-time eligible securities. Evaluate at its five-minute decision timestamps from 09:35 through 10:25 ET. Cross-sectional percentile ranks use average ties among valid observations at that timestamp.',
      '- Component A (`R00530`): short when 30-minute breakdown-distance rank is below 5% and return-acceleration-halves rank is at least 90%. Enter at the exact next-minute raw open. Hold 240 clock minutes; skip any entry whose exit would be later than five minutes before that session\'s exchange close.',
      '- Component B (`R00965`): short when return-acceleration-halves rank is at least 80% and return-acceleration-thirds rank is below 20%. Same entry timing; hold 30 minutes. Same close restriction.',
      '- Combined portfolio: 10 equal-notional slots, maximum 100% aggregate short notional, one position per security. First signal wins; A wins an identical-timestamp same-security conflict. Recycle a slot only after exit. No pyramiding. Deterministic date/security hash breaks simultaneous competing entries (five seed sensitivities retained).',
      '- Capital arithmetic: each slot uses 1/K of starting-day equity; idle cash returns zero. Daily slot returns compound between sessions. Drawdowns and Sharpe use daily realized account returns, not intraday marked-to-market equity. No overnight positions, including early closes.',
      '- Interpretation: A selects strong negative price displacement with a rebound in recent return acceleration, then fades it. B selects disagreement between two acceleration windows and fades the short-lived rebound. These are candidate mechanisms, not established causal explanations. Exact formulas remain the versioned V3 feature definitions.','',
      '## Frequency and risk at 1 bp per side','',
      '| Strategy | Trades/day | Gross bps/trade | Daily Sharpe | Daily max drawdown |','|---|---:|---:|---:|---:|']
    for label,f in chosen:lines.append(f'|{label}|{f.trades_day.mean():.2f}|{f.gross_bps.mean():.2f}|{f.sharpe_c1.mean():.2f}|{f.max_dd_pct_c1.mean():.2f}%|')
    lines+=['','The faster rule does not create continuous all-day turnover: its entries concentrate in the opening hour. After 60.5 million surface cells, all 188 intraday singles, 125 diverse pair follow-ups, 561 capital-screened rules, 70 one-minute replays, ticker overlays, and 1,702 percentile/time/horizon refinements, no robust every-five-minutes money printer was established.','',
      '## Consistency and fragility','',
      'For the combined 10-slot portfolio (seed 0): 8/12 positive months at 1 bp/side; about 51% winning trades; mean gross trade return 11.12 bps in the first half versus 17.22 in the second. Removing its five best days still leaves +5.21 account bps/day. The top five securities contribute 14.9% of positive security-level profit. March and April 2026 are negative. These diagnostics use the same discovery year and are not OOS validation.',
      'The 240-minute component has similar first/second-half gross means (21.78/21.39 bps), with neighboring 10%/20% displacement thresholds also positive. This provides stronger shape evidence than an isolated winning cell. The 30-minute component is weaker in the first half (4.18 versus 16.29 bps).',
      'The higher-profit ticker strategy uses AKAM, SMCI, TTD, SWKS, TEL, LUV, EFX, MRNA, CZR, NXPI, selected from the entire discovery year. It shorts the C0033 market-momentum/volatility state in the opening hour and exits five minutes before close. It trades only 90 sessions. Selecting tickers using the first 126 sessions and applying them later produced only about +0.54% on average at 1 bp/side, versus +50.61% for the full-year-selected list. Keep the full-year list as an aggressive discovery candidate; do not call its high return proven.','',
      '## Timing sensitivity','',
      '| Candidate (10 slots, seed 0) | Extra entry delay | Return at 1 bp/side | Trades |','|---|---:|---:|---:|']
    for d in delay:lines.append(f'|{d["rule"]}|{d["extra_entry_delay_minutes"]} min|{d["return_pct"]:.2f}%|{d["trades"]}|')
    lines+=['','Delay sensitivity keeps selected signals and exits fixed; it is a bounded fill-timing check, not a fresh portfolio selection.','',
      '## Critical excluded result','',
      'The earlier EMA-based headline strategy is invalid as evidence of an EMA edge. A 19,461-observation security audit found zero matches to a correctly aligned causal EMA reconstruction; one stored -42.70% value should be +0.82%. The implementation resets an already flat grouped-apply index, breaking alignment. Reconstructed ranks disagree with 8,170,747 stored r10 labels. Corrected EMA features produce no qualifying extreme-corner candidates in the tested tail family. Original caches and pipeline source were preserved; only research-local corrected arrays were created.',
      'Twenty-four prefix-only feature reconstructions across four unaffected finalist rules matched their stored feature values. Final trades were checked for same-security overlap and exits at least five minutes before close.','',
      '## Scope and limitations','',
      'Discovery: 2025-05-01 through 2026-04-30. May 2026 onward was not accessed. Completed evidence: 469,311/469,311 tasks. Global screen includes all 30 intraday target bases and r3/r5/r10; strategy P&L uses explicit raw price legs, not residual returns. Daily/overnight targets are excluded by the user\'s intraday directive. Subgroup deep replay is a selected search, not exhaustive enumeration of every possible ticker/time/threshold combination.',
      'Short availability and fills are assumed; the cost ladder is the requested hypothetical total friction model. No limit-order queue/fill probability or size-dependent capacity is established. These are scalable-notional simulations, not a dollar-capacity claim. No stop-loss was fitted; open-price tail losses and daily drawdowns must remain visible. Freeze rules and position selection before the later OOS test.',
      '', '## Artifacts','',f'All result tables, rule definitions, trade ledgers, diagnostics and audit evidence: `{OUT}`.',
      'Reproduction: `tools/intraday_strategy_search.py`. Canonical run artifacts were read-only; research outputs are isolated.']
    path=Path(__file__).resolve().parents[1]/'docs/research/V3_INTRADAY_STRATEGIES_2026-09-28.md'
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    freeze={'status':'discovery_candidate_frozen_not_oos_validated','primary':'combined_refined','cost_bps_per_side':COSTS,
        'discovery_end':'2026-04-30','intraday_only':True,'exit_buffer_minutes':5,'slots':10,
        'rules':json.loads((OUT/'final_rules.json').read_text()),'evidence_id':json.loads((OUT/'scope.json').read_text())['evidence_id']}
    (OUT/'candidate_freeze.json').write_text(json.dumps(freeze,indent=2))
    print('REPORT',path,flush=True);print('DELAYS',delay,flush=True)

if __name__=='__main__':
    globals()[sys.argv[1]]()
