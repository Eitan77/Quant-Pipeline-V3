"""Fresh canonical search; train-only nominations, timestamp-bounded replay."""
import argparse, gc, json, time
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import torch
from hashlib import sha256
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.production.segmented_cuda import ResidentEvidenceGrid
from quant_pipeline.production.segmented_scan import SegmentedMoments
from quant_pipeline.production.coverage import _members

ROOT=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923')
OUT=ROOT/'research/competition_under2d_20260930'
BPS=[-1,0,1,2,3,4,5]
TRAIN_END='2025-10-31'
ENTRY_LAG_MINUTES=1
FULL_YEAR=False
EXIT_LAST_MINUTE=False
GRIDS=['preclose_1555','daily_close','intraday_5m']

def regions(r,single=False):
    cells=r if single else r*r
    masks=[];names=[]
    for i in range(cells):
        masks.append([i]);names.append('cell_'+str(i))
    if single:
        for width in [2, max(2,r//2)]:
            for a in range(r-width+1):
                masks.append(list(range(a,a+width)));names.append(f'band_{a}_{a+width}')
    else:
        for a in range(r-1):
            for b in range(r-1):
                masks.append([a*r+b,a*r+b+1,(a+1)*r+b,(a+1)*r+b+1]);names.append(f'block_{a}_{b}')
        h=r//2
        for aa in [range(h),range(r-h,r)]:
            for bb in [range(h),range(r-h,r)]:
                masks.append([a*r+b for a in aa for b in bb]);names.append(f'corner_{aa.start}_{bb.start}')
    # Eliminate equivalent regions before counting trials.
    unique={tuple(m):name for m,name in zip(masks,names)}
    masks=list(unique);names=list(unique.values())
    w=np.zeros((cells,len(masks)))
    for i,m in enumerate(masks):w[list(m),i]=1
    return masks,names,w

def init():
    OUT.mkdir(parents=True,exist_ok=True)
    done=json.loads((ROOT/'EVIDENCE_COMPLETE.json').read_text())
    assert done['status']=='complete' and not done['final_holdout_accessed'] and not done['replication_accessed']
    spec={'objective':'maximum defensible finite-capital profit','max_hold_seconds_exclusive':172800,
          'train':['2025-05-01',TRAIN_END],'internal_later':['2025-11-01','2026-04-30'],
          'sealed_access':False,'bps_per_side':BPS,'prior_research_results_used':False,
          'selection':'Train-only full canonical singles/duals; all r3/r5/r10 cells, adjacent blocks and corners. Fixed 10 equal capital slots. No return-dependent tie breaking.',
          'limits':'Same seven offsets; quotes only at touched one-minute bars. Missing exits are retained as liabilities.',
          'validation_limit':'Later discovery is an internal check; historical prior researcher exposure prevents an untouched holdout claim.'}
    (OUT/'protocol.json').write_text(json.dumps(spec,indent=2))

def train(grid,limit=None):
    torch.set_num_threads(4)
    reader=EvidenceReader(ROOT,'evidence/reader.json',grid)
    obs=pd.read_parquet(ROOT/reader.grid['observations'],columns=['observation_id','session_date','decision_ts'])
    dates=pd.to_datetime(obs.session_date)
    assert dates.min()>=pd.Timestamp('2025-05-01') and dates.max()<=pd.Timestamp('2026-04-30')
    month=(dates.dt.year-2025)*12+dates.dt.month-5
    istrain=(dates<=pd.Timestamp(TRAIN_END)).to_numpy().copy()
    resident=ResidentEvidenceGrid(reader,torch.device('cuda:0'),reserve_bytes=800_000_000)
    targets=[t for t in resident.targets if '__raw__' in t and (grid!='daily_close' or t.startswith('target_1d__'))]
    cols=[resident.target_index[t] for t in targets]
    # Actual timestamp eligibility for cross-session targets; purge exits after train end.
    if grid!='intraday_5m':
        con=duckdb.connect();con.execute("SET threads=4")
        windows=con.execute('SELECT observation_id,entry_ts,exit_ts FROM read_parquet(?) WHERE target_id=? ORDER BY observation_id',[str(ROOT/'cache/targets'/f'{grid}.parquet'),targets[0]]).fetchdf()
        windows=obs[['observation_id']].merge(windows,on='observation_id',how='left',validate='one_to_one')
        duration=windows.exit_ts-windows.entry_ts
        istrain &= (duration.gt(pd.Timedelta(0)) & duration.lt(pd.Timedelta(days=2)) & windows.exit_ts.lt(pd.Timestamp('2025-11-01',tz='America/New_York'))).to_numpy()
    else:
        # Exclude the final training session to purge every intraday target.
        istrain &= (dates<pd.Timestamp(TRAIN_END)).to_numpy()
    ix=torch.as_tensor(np.flatnonzero(istrain),device='cuda:0')
    resident.bins=resident.bins[ix].contiguous();resident.y=resident.y[ix][:,cols].contiguous()
    timecodes=resident.groups[resident.family_index['time_bucket']].cpu().numpy() if grid=='intraday_5m' else np.zeros(reader.rows,dtype=int)
    buckets=5 if grid=='intraday_5m' else 1
    codes=(timecodes[istrain]*6+month.to_numpy()[istrain]).astype(np.int64)
    resident.groups=torch.as_tensor(codes[None,:],device='cuda:0');resident.family_index={'train':0}
    resident.rows=len(ix);resident.targets=targets;resident.target_index={t:i for i,t in enumerate(targets)}
    del ix;gc.collect();torch.cuda.empty_cache()
    pairids,defs=_members(ROOT,grid,reader.grid,'dual')
    singles=[(f,(f,)) for f in resident.features]
    pairs=[(p,defs[p]) for p in pairids]
    if limit:pairs=pairs[:limit]
    registry=pd.read_parquet(ROOT/'feature_registry.parquet').set_index('feature_id')
    retained=[];trial_count=0;t0=time.time()
    for single,definitions in [(True,singles),(False,pairs)]:
        for start in range(0,len(definitions),64):
            subset=definitions[start:start+64];live=[]
            for r in [3,5,10]:
                mom=SegmentedMoments(pairs=len(subset),targets=len(targets),groups=buckets*6,resolution=r,singles=single,device='cuda:0',max_state_bytes=400_000_000,track_sumsq=False)
                live.append(({'grouping_id':'train','group_start':0,'group_stop':buckets*6,'resolution':r},mom))
            resident.accumulate(live,[v for _,v in subset],targets,lambda:False)
            for task,mom in live:
                r=task['resolution'];masks,names,w=regions(r,single)
                n=mom.n.cpu().numpy().reshape(len(targets),len(subset),buckets,6,-1)
                s=mom.s.cpu().numpy().reshape(n.shape)*1e4
                nn=n@w;ss=s@w;total=nn.sum(axis=3);sums=ss.sum(axis=3)
                means=np.divide(sums,total,out=np.zeros_like(sums),where=total>0)
                signed=np.sign(means);monthly=np.divide(ss,nn,out=np.zeros_like(ss),where=nn>0)
                pos=((monthly*signed[...,None,:]>0)&(nn>0)).sum(axis=3)
                populated=(nn>0).sum(axis=3)
                min_n=200 if grid=='intraday_5m' else 60
                valid=(total>=min_n)&(pos>=4)&(populated==6)
                # Participation capped by the fixed ten slots. No single scalar replaces evidence fields.
                score=(np.abs(means)-10)*np.minimum(total/126,10)
                score[~valid]=-np.inf
                trial_count+=int(total.size)*2
                for ti,target in enumerate(targets):
                    for b in range(buckets):
                        for direction in [-1,1]:
                            for metric in [score[ti,:,b],np.where(valid[ti,:,b],np.abs(means[ti,:,b]),-np.inf)]:
                                z=np.where(signed[ti,:,b]==direction,metric,-np.inf).ravel()
                                k=min(8,np.isfinite(z).sum())
                                if not k:continue
                                top=np.argpartition(z,-k)[-k:]
                                for flat in top:
                                    pi,ri=np.unravel_index(flat,(len(subset),len(masks)))
                                    cells=list(masks[ri]);n0=n[ti,pi,b].sum(axis=0);s0=s[ti,pi,b].sum(axis=0)
                                    baseline=s0.sum()/max(n0.sum(),1)
                                    if single:lift=0.;parent_a=means[ti,pi,b,ri];parent_b=0.
                                    else:
                                        ng=n0.reshape(r,r);sg=s0.reshape(r,r)
                                        ar=np.unique(np.array(cells)//r);br=np.unique(np.array(cells)%r)
                                        parent_a=sg[ar].sum()/max(ng[ar].sum(),1)
                                        parent_b=sg[:,br].sum()/max(ng[:,br].sum(),1)
                                        lift=means[ti,pi,b,ri]-parent_a-parent_b+baseline
                                    a=subset[pi][1][0];bb='' if single else subset[pi][1][1]
                                    retained.append({'grid':grid,'state_kind':'single' if single else 'dual','pair_id':subset[pi][0],
                                        'feature_a':a,'feature_b':bb,'family':registry.loc[a,'family']+' / '+(registry.loc[bb,'family'] if bb else ''),
                                        'target_id':target,'resolution':r,'cells':json.dumps(cells),'region':names[ri],'time_group':b,'direction':direction,
                                        'train_n':int(total[ti,pi,b,ri]),'train_bps':float(means[ti,pi,b,ri]*direction),
                                        'interaction_lift_bps':float(lift*direction),'parent_a_bps':float(parent_a*direction),'parent_b_bps':float(parent_b*direction),
                                        'train_frequency':float(total[ti,pi,b,ri]/max(n0.sum(),1)),
                                        'train_positive_months':int(pos[ti,pi,b,ri]),'train_month_n':nn[ti,pi,b,:,ri].astype(int).tolist(),
                                        'train_month_bps':(monthly[ti,pi,b,:,ri]*direction).tolist(),'profit_proxy':float(score[ti,pi,b,ri])})
            del live,mom
            if start%256==0:
                print(grid,'single' if single else 'dual',start+len(subset),len(definitions),'elapsed',round(time.time()-t0),flush=True)
            # Keep compact diverse leaders after each batch; no raw cell dump.
            f=pd.DataFrame(retained).drop_duplicates(['pair_id','target_id','resolution','cells','time_group','direction'])
            keep=[]
            for metric in ['profit_proxy','train_bps','interaction_lift_bps']:
                ranked=f.sort_values(metric,ascending=False).groupby(['target_id','time_group','direction','family'],sort=False).head(3)
                keep.append(ranked.groupby(['target_id','time_group','direction'],sort=False).head(12))
            retained=pd.concat(keep).drop_duplicates(['pair_id','target_id','resolution','cells','time_group','direction']).to_dict('records')
            f=pd.DataFrame(retained);f.to_parquet(OUT/f'train_{grid}.parquet',index=False)
    (OUT/f'coverage_{grid}.json').write_text(json.dumps({'pairs':len(pairs),'singles':len(singles),'training_rows':resident.rows,'targets':targets,'hypotheses_counted':trial_count,'seconds':time.time()-t0},indent=2))
    print('TRAIN COMPLETE',grid,len(retained),'trials',trial_count,flush=True)

def nominate(grid):
    f=pd.read_parquet(OUT/f'train_{grid}.parquet');parts=[]
    for metric in ['profit_proxy','train_bps','interaction_lift_bps']:
        rank=f.sort_values(metric,ascending=False)
        rank=rank.drop_duplicates(['target_id','time_group','direction','family'])
        parts.append(rank.groupby(['target_id','time_group','direction'],sort=False).head(2))
    picks=pd.concat(parts).drop_duplicates(['pair_id','target_id','resolution','cells','time_group','direction']).copy()
    picks=picks[picks.train_bps>10].sort_values('profit_proxy',ascending=False).reset_index(drop=True)
    picks['candidate_id']=[grid+'_'+str(i) for i in range(len(picks))]
    # Freeze before consuming later target outcomes.
    path=OUT/f'nominations_{grid}.parquet';picks.to_parquet(path,index=False)
    (OUT/f'nominations_{grid}.json').write_text(json.dumps({'sha256':sha256(path.read_bytes()).hexdigest(),'count':len(picks),'selection_uses_later_results':False},indent=2))
    return picks

def allocate_frame(f,slots=10,seed=0):
    if f.empty:return f
    work=f.copy()
    # Stable PIT security identity supplies the tie break, without outcome selection.
    work['tie']=pd.util.hash_pandas_object(work.security_id.astype(str)+work.session_date.astype(str)+str(seed),index=False).to_numpy()
    work=work.sort_values(['entry_ts','tie','observation_id'],kind='stable')
    free=np.full(slots,-1,dtype=np.int64);active={};kept=[]
    en=work.entry_ts.to_numpy(dtype='datetime64[ns]').astype('int64')
    ex=work.exit_ts.to_numpy(dtype='datetime64[ns]').astype('int64')+60_000_000_000
    for j,(sid,e,x) in enumerate(zip(work.security_id,en,ex)):
        if active.get(sid,-1)>e:continue
        slot=free.argmin()
        if free[slot]>e:continue
        kept.append(j);free[slot]=x;active[sid]=x
    return work.iloc[kept].drop(columns='tie')

def portfolio_stats(f,bps,slots=10):
    if f.empty:return {'trades':0,'mean_trade_bps':0.,'additive_pct':0.,'max_dd_pct':0.,'positive_months':0,'days':0,'symbols':0}
    d=f.direction.to_numpy();entry=f.entry_price.to_numpy()*(1+d*bps/10000)
    exitp=f.exit_price.to_numpy()*(1-d*bps/10000)
    ret=d*(exitp-entry)/entry
    date=pd.to_datetime(f.exit_ts,utc=True).dt.tz_convert('America/New_York').dt.normalize().dt.tz_localize(None)
    daily=pd.Series(ret/slots,index=date).groupby(level=0).sum().sort_index()
    equity=daily.cumsum();dd=np.maximum.accumulate(np.r_[0.,equity.to_numpy()])[1:]-equity.to_numpy()
    monthly=daily.groupby(daily.index.strftime('%Y-%m')).sum()
    sym=pd.Series(ret,index=f.security_id).groupby(level=0).sum().sort_values(ascending=False)
    trimmed=f[~f.security_id.isin(sym.head(5).index)]
    ex_top=d[~f.security_id.isin(sym.head(5).index)]*(trimmed.exit_price.to_numpy()*(1-trimmed.direction.to_numpy()*bps/10000)-trimmed.entry_price.to_numpy()*(1+trimmed.direction.to_numpy()*bps/10000))/(trimmed.entry_price.to_numpy()*(1+trimmed.direction.to_numpy()*bps/10000))
    return {'trades':len(f),'mean_trade_bps':float(ret.mean()*1e4),'additive_pct':float(daily.sum()*100),
        'max_dd_pct':float(dd.max()*100),'positive_months':int((monthly>0).sum()),'days':len(daily),'symbols':len(sym),
        'top5_profit_share':float(sym.head(5).sum()/sym.sum()) if sym.sum()!=0 else None,
        'ex_top5_mean_bps':float(ex_top.mean()*1e4) if len(ex_top) else None,'max_hold_hours':float((f.exit_ts-f.entry_ts).dt.total_seconds().max()/3600),
        'monthly_pct':monthly.mul(100).to_dict()}

def replay_grid(grid):
    picks=nominate(grid);reader=EvidenceReader(ROOT,'evidence/reader.json',grid)
    obs=pd.read_parquet(ROOT/reader.grid['observations'],columns=['observation_id','security_id','session_date','decision_ts'])
    times=obs.decision_ts.to_numpy(dtype='datetime64[ns]').astype('int64')
    secs=pd.factorize(obs.security_id,sort=True)[0];days=pd.factorize(obs.session_date,sort=True)[0]
    tg=reader.read_groups('time_bucket',0,reader.rows) if grid=='intraday_5m' else np.zeros(reader.rows,dtype=int)
    events=[];evidence=[];cache={}
    for row in picks.itertuples():
        def decode(name):
            key=(name,row.resolution)
            if key not in cache:
                cache[key]=decode_packed_bins(reader.read_columns('bins',[name],0,reader.rows)[:,0],row.resolution)
                if len(cache)>8:cache.pop(next(iter(cache)))
            return cache[key]
        a=decode(row.feature_a)
        if row.feature_b:
            b=decode(row.feature_b);code=np.where((a>=0)&(b>=0),a*row.resolution+b,-1)
        else:code=a
        y=reader.read_columns('targets',[row.target_id],0,reader.rows)[:,0]
        mask=np.isin(code,json.loads(row.cells))&((tg==row.time_group) if row.time_group>=0 else True)&np.isfinite(y)
        ix=np.flatnonzero(mask);active_n=len(ix)
        # One episode starts after a missing selected decision; repeated observations aren't trades.
        if grid=='intraday_5m' and len(ix):
            ix=ix[np.lexsort((times[ix],days[ix],secs[ix]))]
            starts=np.r_[True,(secs[ix[1:]]!=secs[ix[:-1]])|(days[ix[1:]]!=days[ix[:-1]])|(times[ix[1:]]-times[ix[:-1]]!=300_000_000_000)]
            ix=ix[starts]
        events.append(pd.DataFrame({'candidate_id':row.candidate_id,'observation_id':ix,'target_id':row.target_id,'direction':row.direction}))
        evidence.append({'candidate_id':row.candidate_id,'active_observations':active_n,'episodes':len(ix)})
    event=pd.concat(events,ignore_index=True);del cache,obs;gc.collect()
    con=duckdb.connect();con.execute("SET memory_limit='8GB'");con.execute('SET threads=4')
    tmp=OUT/'tmp'/grid;tmp.mkdir(parents=True,exist_ok=True)
    con.execute(f"SET temp_directory='{tmp.as_posix()}/ledger'")
    con.register('events',event)
    exit_expression='t.exit_ts-INTERVAL 1 MINUTE' if EXIT_LAST_MINUTE and grid=='daily_close' else 't.exit_ts'
    frame=con.execute(f'''SELECT e.candidate_id,e.direction,t.observation_id,t.security_id,t.session_date,t.decision_ts,
      t.entry_ts+INTERVAL {ENTRY_LAG_MINUTES} MINUTE entry_ts,t.entry_price original_entry_price,{exit_expression} exit_ts,t.exit_price,t.target_id
      FROM read_parquet(?) t JOIN events e USING(observation_id,target_id)
      WHERE NOT t.crosses_split AND NOT t.crosses_cash_dividend AND t.target IS NOT NULL
      AND t.exit_ts>t.entry_ts+INTERVAL {ENTRY_LAG_MINUTES} MINUTE
      AND t.exit_ts-t.entry_ts<INTERVAL 2 DAY''',[str(ROOT/'cache/targets'/f'{grid}.parquet')]).fetchdf()
    if grid=='daily_close' and globals().get('SESSION_CLOSES') is not None:
        dates=frame.exit_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
        scheduled=dates.map(SESSION_CLOSES)
        if scheduled.isna().any():raise RuntimeError('Missing scheduled session close.')
        frame['exit_ts']=pd.to_datetime(scheduled,utc=True)-pd.Timedelta(minutes=1)
    if grid=='preclose_1555' and globals().get('EXIT_LAG_MINUTES',0):
        frame['exit_ts']+=pd.Timedelta(minutes=EXIT_LAG_MINUTES)
        frame=frame[(frame.exit_ts-frame.entry_ts)<pd.Timedelta(days=2)]
    if globals().get('SAVE_ELIGIBLE_EVENTS',False):frame.to_parquet(OUT/f'eligible_events_{grid}.parquet',index=False)
    ledgers=[];ev=pd.DataFrame(evidence).set_index('candidate_id')
    for cid,g in frame.groupby('candidate_id',sort=False):
        k=allocate_frame(g);ev.loc[cid,'independent_finite_slot_trades']=len(k);ledgers.append(k)
    kept=pd.concat(ledgers,ignore_index=True)
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    endpoints=pd.concat([kept[['security_id','entry_ts']].rename(columns={'entry_ts':'stamp'}),kept[['security_id','exit_ts']].rename(columns={'exit_ts':'stamp'})]).drop_duplicates()
    with duckdb.connect(source,read_only=True) as raw:
        raw.execute("SET memory_limit='6GB'");raw.execute('SET threads=4')
        raw.execute(f"SET temp_directory='{tmp.as_posix()}/raw'");raw.register('endpoints',endpoints)
        quotes_bars=raw.execute('''SELECT b.security_id,b.bar_start_ts_utc stamp,b.symbol,b.open,b.high,b.low,b.close
          FROM bars_1m_raw b JOIN endpoints e ON b.security_id=e.security_id AND b.bar_start_ts_utc=e.stamp''').fetchdf()
        if globals().get('COMPLETED_CLOSE_REFERENCES',False):
            ref_endpoints=pd.concat([endpoints.assign(bar_start_ts_utc=endpoints.stamp-pd.Timedelta(minutes=k)) for k in range(1,6)],ignore_index=True)
            raw.register('ref_endpoints',ref_endpoints)
            references=raw.execute('''SELECT e.security_id,e.stamp,b.close reference_price
              FROM bars_1m_raw b JOIN ref_endpoints e USING(security_id,bar_start_ts_utc)
              WHERE b.availability_ts_utc<=e.stamp
              QUALIFY row_number() OVER(PARTITION BY e.security_id,e.stamp ORDER BY b.bar_start_ts_utc DESC)=1''').fetchdf()
    quotes_bars.to_parquet(OUT/f'endpoint_bars_{grid}.parquet',index=False)
    priced=kept.merge(quotes_bars[['security_id','stamp','open','symbol']].rename(columns={'stamp':'entry_ts','open':'entry_price'}),on=['security_id','entry_ts'],how='left',validate='many_to_one')
    if EXIT_LAST_MINUTE and grid=='daily_close':
        priced=priced.drop(columns='exit_price').merge(quotes_bars[['security_id','stamp','open']].rename(columns={'stamp':'exit_ts','open':'exit_price'}),on=['security_id','exit_ts'],how='left',validate='many_to_one')
    if globals().get('COMPLETED_CLOSE_REFERENCES',False):
        priced=priced.drop(columns=['entry_price','exit_price']).merge(references.rename(columns={'stamp':'entry_ts','reference_price':'entry_price'}),on=['security_id','entry_ts'],how='left',validate='many_to_one')
        priced=priced.merge(references.rename(columns={'stamp':'exit_ts','reference_price':'exit_price'}),on=['security_id','exit_ts'],how='left',validate='many_to_one')
    assert len(priced)==len(kept),'Duplicate raw endpoint prices'
    ev['missing_entry_prices']=priced[priced.entry_price.isna()].groupby('candidate_id').size().reindex(ev.index,fill_value=0)
    if globals().get('COMPLETED_CLOSE_REFERENCES',False):
        liabilities=priced[priced.entry_price.gt(0)&~priced.exit_price.gt(0)]
        liabilities.to_parquet(OUT/f'unpriced_liabilities_{grid}.parquet',index=False)
        if len(liabilities):raise RuntimeError(f'{len(liabilities)} entries have missing exit reference prices; no performance claim.')
    priced=priced[priced.entry_price.gt(0)].copy()
    priced.to_parquet(OUT/f'trades_{grid}.parquet',index=False);ev.reset_index().to_parquet(OUT/f'opportunities_{grid}.parquet',index=False)
    rows=[]
    for cid,g in priced.groupby('candidate_id'):
        for period,part in ([('discovery',g)] if FULL_YEAR else [('train',g[g.exit_ts<pd.Timestamp('2025-11-01',tz='America/New_York')]),('later',g[g.entry_ts>=pd.Timestamp('2025-11-01',tz='America/New_York')]),('all',g)]):
            for bps in BPS:rows.append({'candidate_id':cid,'period':period,'bps':bps,**portfolio_stats(part,bps)})
    result=pd.DataFrame(rows);result['monthly_pct']=result.monthly_pct.map(lambda x:json.dumps(x));result.to_parquet(OUT/f'replay_{grid}.parquet',index=False)
    print('REPLAY COMPLETE',grid,len(picks),len(priced),flush=True)
    print(result[(result.period=='train')&(result.bps==5)].sort_values('additive_pct',ascending=False).head(6)[['candidate_id','trades','mean_trade_bps','additive_pct','max_dd_pct']].to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['train','replay']);p.add_argument('--grid',choices=GRIDS);p.add_argument('--limit',type=int)
    args=p.parse_args();init()
    for grid in [args.grid] if args.grid else GRIDS:
        if args.stage=='train':train(grid,args.limit)
        else:replay_grid(grid)
