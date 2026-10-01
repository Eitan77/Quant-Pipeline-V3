"""Independent-opportunity census of supported canonical states; no new mechanisms."""
import argparse,json,time
import numpy as np,pandas as pd,torch,duckdb
from competition_under2d import ROOT,EvidenceReader,decode_packed_bins

OUT=ROOT/'research/canonical_intraday_hypotheses_20260930'
KEY=['pair_id','resolution','cells','direction']
MINIMUM_SIGNAL_MINUTE=29
TAIL_WAVE=False

# Nominations originate in the expanded surfaces and opportunity census.
# These are different structures, not rescue filters on rejected scalp rules.
DEFINITIONS=[
 {'name':'negative_flow','a':'negative_return_sum_abs','b':'positive_return_sum','r':10,'cells':[90],'side':-1,'holds':[60,120,240],
  'reason':'Opposite flow tails show a coherent negative lower-right surface and weak parent effects; benchmark-adjusted support, 251 active sessions.'},
 {'name':'failed_recovery','a':'atr_band_z','b':'return_acceleration_halves','r':10,'cells':[9],'side':-1,'holds':[60,120,240],
  'reason':'Deep below moving average despite accelerating recent returns; negative neighboring cells and positive interaction lift; 251 sessions.'},
 {'name':'trend_vwap_disagreement','a':'trend_slope_t','b':'vwap_drift','r':3,'cells':[6],'side':1,'holds':[120,240],
  'reason':'High trend slope with low VWAP drift forms a coarse disagreement region; 250 sessions, supported 120/240-minute horizons.'},
 {'name':'agreement_range','a':'momentum_sign_agreement','b':'range_position','r':10,'cells':[57],'side':1,'holds':[60],
  'reason':'Agreement rank conditioned by high range position; strong raw return, smaller benchmark-adjusted effect, 225 sessions. Discrete-rank semantics require audit.'},
]

def surfaces():
    features=pd.read_parquet(ROOT/'feature_registry.parquet').drop_duplicates('feature_id')
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    features=features[features.feature_id.isin(reader.grid['bins'])]
    definitions=[]
    for d in DEFINITIONS:
        d=d.copy()
        d['feature_a']=features[features.concept_id==d['a']].feature_id.iloc[0]
        d['feature_b']=features[features.concept_id==d['b']].feature_id.iloc[0]
        definitions.append(d)
    (OUT/'EVIDENCE_NOMINATIONS.json').write_text(json.dumps({'discovery':['2025-05-01','2026-04-30'],'holdouts_accessed':False,'definitions':definitions,
      'ranking':'Descending completed trailing-30-minute dollar turnover; stable identity tie. Ten scheduled capital slots, one position per security, reservation through exit plus one minute.',
      'reference':'Latest completed minute close at decision and scheduled exit; known stale reference retained and audited. Canonical targets instead use the open one minute after decision; those descriptive returns are not this limit policy performance.',
      'fees':0,'bps':[-1,0,1,2,3,4,5],'neighbor_policy':'Inspect full r3/r5/r10 surfaces and parent marginals; do not add a fitted filter to a losing nomination.'},indent=2))
    files=[str(p) for stage in ['dual_coarse_results','dual_fine_results','dual_exact_results'] for p in (ROOT/stage/'intraday_5m').rglob('*.parquet')]
    wanted=pd.DataFrame(definitions)[['feature_a','feature_b']]
    with duckdb.connect() as c:
        c.execute('SET threads=4');c.execute("SET memory_limit='4GB'")
        c.register('wanted',wanted)
        result=c.read_parquet(files,union_by_name=True).create_view('surfaces')
        result=c.execute('''SELECT s.pair_id,s.feature_a,s.feature_b,s.target_id,s.resolution,s.surface_counts,s.surface_sums,s.surface_sumsq
            FROM surfaces s JOIN wanted w USING(feature_a,feature_b)''').fetchdf()
    result.to_parquet(OUT/'nominated_full_surfaces.parquet',index=False)
    rows=[]
    for d in definitions:
        q=result[(result.feature_a==d['feature_a'])&(result.feature_b==d['feature_b'])&(result.resolution==d['r'])]
        for row in q.itertuples():
            r=d['r'];ix=np.array(d['cells']);n=np.array(row.surface_counts).reshape(r,r);s=np.array(row.surface_sums).reshape(r,r)*1e4
            total=n.sum();base=s.sum()/max(total,1);nn=n.ravel()[ix].sum();ss=s.ravel()[ix].sum()
            a=np.unique(ix//r);b=np.unique(ix%r)
            pa=s[a,:].sum()/max(n[a,:].sum(),1);pb=s[:,b].sum()/max(n[:,b].sum(),1)
            rows.append({'name':d['name'],'target_id':row.target_id,'resolution':r,'active_n':int(nn),'active_bps':d['side']*ss/max(nn,1),
              'parent_a_bps':d['side']*pa,'parent_b_bps':d['side']*pb,'interaction_lift_bps':d['side']*(ss/max(nn,1)-pa-pb+base)})
    pd.DataFrame(rows).to_parquet(OUT/'nominated_horizon_basis_profile.parquet',index=False)
    print('SURFACES_COMPLETE',len(result),'full surfaces; nominations',len(definitions),flush=True)

def ledger():
    from competition_fresh_capacity import allocate
    from competition_scalp import metrics
    minute=ROOT/'research/intraday_causal_restart_20260930/minute_mechanisms'
    axes=json.loads((minute/'axes.json').read_text());days=axes['days'];sids=pd.Index(axes['security_ids'])
    cube={name:np.load(minute/f'{name}.npy',mmap_mode='r') for name in ['close','high','low','volume']}
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    obs=pd.read_parquet(ROOT/reader.grid['observations'],columns=['observation_id','security_id','session_date','decision_ts']).sort_values('observation_id').reset_index(drop=True)
    clock=pd.to_datetime(obs.decision_ts,utc=True).dt.as_unit('ns');stamp=clock.astype('int64').to_numpy()
    d=pd.Index(days).get_indexer(pd.to_datetime(obs.session_date).dt.strftime('%Y-%m-%d'));s=sids.get_indexer(obs.security_id)
    opens=np.array(axes['open_epoch_ns']);ends=np.array(axes['session_minutes'])
    m=((stamp-opens[d])//60_000_000_000-1).astype(int)
    order=np.lexsort((stamp,d,s));prev=np.empty(len(obs),dtype='int64');prev[order]=np.roll(order,1)
    linked=(s==s[prev])&(d==d[prev])&(stamp-stamp[prev]==300_000_000_000)
    spec=json.loads((OUT/'EVIDENCE_NOMINATIONS.json').read_text());pools=[];rules=[];summary=[];paths=[];opportunities=[]
    for definition in spec['definitions']:
        fa,fb=definition['feature_a'],definition['feature_b'];r=definition['r']
        aa=decode_packed_bins(reader.read_columns('bins',[fa],0,reader.rows)[:,0],r)
        bb=decode_packed_bins(reader.read_columns('bins',[fb],0,reader.rows)[:,0],r)
        mask=np.isin(aa*r+bb,definition['cells'])&(aa>=0)&(bb>=0)
        episode=mask&~(mask[prev]&linked)
        ids=np.flatnonzero(episode&(s>=0)&(m>=MINIMUM_SIGNAL_MINUTE)&(m<ends[d]-1))
        dd,ss,mm=d[ids],s[ids],m[ids]
        window=mm[:,None]+np.arange(-29,1)[None,:]
        vol=cube['volume'][dd[:,None],ss[:,None],window]
        price=(cube['close'][dd[:,None],ss[:,None],window]+cube['high'][dd[:,None],ss[:,None],window]+cube['low'][dd[:,None],ss[:,None],window])/3
        # Thirty completed minutes, positive current price, and complete ranking inputs.
        valid=np.isfinite(vol).all(1)&np.isfinite(price).all(1)&(cube['close'][dd,ss,mm]>0)
        if TAIL_WAVE:
            prior=mm[:,None]+np.arange(-60,1)[None,:]
            valid&=np.isfinite(cube['close'][dd[:,None],ss[:,None],prior]).all(1)
        ids=ids[valid];dd,ss,mm=dd[valid],ss[valid],mm[valid]
        score=(vol[valid]*price[valid]).sum(1)
        for hold in definition['holds']:
            legal=(mm+hold+1<=ends[dd]-1)
            chosen=ids[legal];g=obs.iloc[chosen].copy()
            g['day']=dd[legal];g['symbol_code']=ss[legal];g['signal_minute']=mm[legal];g['score']=score[legal]
            g['entry_ts']=pd.to_datetime(g.decision_ts,utc=True).dt.as_unit('ns');g['exit_ts']=g.entry_ts+pd.Timedelta(minutes=hold)
            g['entry_price']=cube['close'][g.day,g.symbol_code,g.signal_minute]
            g['rank_score']=g.score;g['direction']=definition['side'];g['hold_minutes']=hold
            cid=f"canonical_{definition['name']}_{hold}m";g['candidate_id']=cid
            opportunities.append({'candidate_id':cid,'active_observations':int(mask.sum()),'uncensored_episodes':int(episode.sum()),'complete_input_episodes':len(ids),'legal_episodes':len(g),'active_sessions':g.session_date.nunique()})
            g=allocate(g,10,True).copy();gd=g.day.to_numpy(int);gs=g.symbol_code.to_numpy(int);gm=g.signal_minute.to_numpy(int)
            g['exit_price']=cube['close'][gd,gs,gm+hold];g['exit_stale_fallback']=~g.exit_price.gt(0)
            for j in np.flatnonzero(g.exit_stale_fallback.to_numpy()):
                known=cube['close'][gd[j],gs[j],:gm[j]+hold+1];available=np.flatnonzero(np.isfinite(known)&(known>0))
                assert len(available),'Unpriced holding liability'
                g.iloc[j,g.columns.get_loc('exit_price')]=known[available[-1]]
            assert g.entry_price.gt(0).all() and g.exit_price.gt(0).all()
            g['symbol']=np.array(axes['symbols'])[gs];g['order_id']=np.arange(len(g))
            pools.append(g);rules.append({**definition,'candidate_id':cid,'hold_minutes':hold,'slots':10,'ranking':spec['ranking']})
            side=definition['side'];ep=g.entry_price.to_numpy();xp=g.exit_price.to_numpy()
            for bps in spec['bps']:
                ret=side*(xp*(1-side*bps/1e4)/(ep*(1+side*bps/1e4))-1)
                sym=pd.Series(ret).groupby(gs).sum().sort_values(ascending=False);trim=~np.isin(gs,sym.head(5).index)
                dayret=pd.Series(ret).groupby(gd).sum();exday=~np.isin(gd,dayret.nlargest(5).index)
                summary.append({'candidate_id':cid,'bps':bps,'symbols':len(sym),'mean_ex_top5_symbols_bps':float(ret[trim].mean()*1e4),'mean_ex_top5_days_bps':float(ret[exday].mean()*1e4),
                  'stale_exit_references':int(g.exit_stale_fallback.sum()),**metrics(ret,gd,days,10)})
            future=gm[:,None]+np.arange(1,hold+1)[None,:]
            hi=cube['high'][gd[:,None],gs[:,None],future];lo=cube['low'][gd[:,None],gs[:,None],future]
            favorable=side*((hi if side==1 else lo)/ep[:,None]-1);adverse=side*((lo if side==1 else hi)/ep[:,None]-1)
            paths.append({'candidate_id':cid,'trades':len(g),'mean_mfe_bps':float(np.nanmax(favorable,axis=1).mean()*1e4),'mean_mae_bps':float(np.nanmin(adverse,axis=1).mean()*1e4),
              'mean_terminal_bps':float((side*(xp/ep-1)).mean()*1e4),'mean_peak_minutes':float((np.nanargmax(favorable,axis=1)+1).astype(float).mean()),
              'entry_bar_touched_zero_fraction':float((cube['low'][gd,gs,gm+1]<=ep if side==1 else cube['high'][gd,gs,gm+1]>=ep).mean())})
            print('LEDGER',cid,len(g),'nominations',flush=True)
    pd.concat(pools,ignore_index=True).to_parquet(OUT/'canonical_policy_pool.parquet',index=False)
    pd.DataFrame(rules).to_parquet(OUT/'rules.parquet',index=False)
    pd.DataFrame(summary).to_parquet(OUT/'bar_sensitivity.parquet',index=False)
    pd.DataFrame(paths).to_parquet(OUT/'path_profiles.parquet',index=False)
    pd.DataFrame(opportunities).to_parquet(OUT/'policy_opportunities.parquet',index=False)
    (OUT/'scope.json').write_text(json.dumps({**spec,'entry_history_requirement':'Thirty completed minutes with finite price and volume; current positive reference price. Same rule for all nominations.',
      'minimum_completed_minutes':MINIMUM_SIGNAL_MINUTE+1,'same_day_exit':True,'bar_prices_are_assumed_not_attained':True,'policies':len(rules),'quote_replay_started':False},indent=2))
    f=pd.DataFrame(summary)
    print(f[f.bps==0][['candidate_id','trades','mean_trade_bps','return_pct','positive_months','positive_week_fraction','mean_ex_top5_symbols_bps','mean_ex_top5_days_bps']].to_string(index=False),flush=True)

def audit():
    from intraday_causal_restart import registry,spec
    from quant_pipeline.alpha_discovery.features.base import FeatureBuilder
    from quant_pipeline.alpha_discovery.cache.rank_store import build_rank_bins
    reader,reg=registry()
    policies=(['canonical_tail_context_spread_240m','canonical_tail_context_sellflow_240m'] if TAIL_WAVE else ['canonical_failed_recovery_60m','canonical_negative_flow_120m'])
    pool=pd.read_parquet(OUT/'canonical_policy_pool.parquet');tests=[]
    for cid in policies:tests.append(pool[pool.candidate_id==cid].sample(100,random_state=20260930))
    tests=pd.concat(tests,ignore_index=True);tests['session_date']=pd.to_datetime(tests.session_date)
    keys=tests[['security_id','session_date']].drop_duplicates()
    with duckdb.connect() as c:
        c.execute('SET threads=4');c.execute("SET memory_limit='4GB'");c.register('wanted',keys)
        frame=c.execute('SELECT p.* FROM read_parquet(?) p JOIN wanted w USING(security_id,session_date)',[str(ROOT/'cache/calculation_panels/intraday_5m.parquet')]).fetchdf()
    frame['decision_ts']=pd.to_datetime(frame.decision_ts,utc=True).dt.as_unit('ns')
    frame['session_date']=pd.to_datetime(frame.session_date)
    definitions=json.loads((OUT/'EVIDENCE_NOMINATIONS.json').read_text())['definitions'][:2]
    fids=sorted({d[k] for d in definitions for k in ['feature_a','feature_b']});specs=[spec(reg.loc[fid]) for fid in fids]
    def build(f):
        b=FeatureBuilder(f.reset_index(drop=True));v=b.build_many(specs).astype('float32')
        return b.frame.join(v).set_index(['security_id','decision_ts']).sort_index()
    base=build(frame);shuffled=build(frame.sample(frac=1,random_state=20260930))
    cut=tests.groupby(['security_id','session_date']).entry_ts.max().rename('cutoff').reset_index()
    past=frame.merge(cut,on=['security_id','session_date'],validate='many_to_one')
    past=build(past[past.decision_ts<=past.cutoff].drop(columns='cutoff'))
    blocks={}
    for path in (ROOT/'cache/features/intraday_5m').glob('*.json'):
        data=json.loads(path.read_text())
        for j,fid in enumerate(data.get('columns',[])):blocks[fid]=(path.with_suffix('.npy'),j)
    target_index=pd.MultiIndex.from_arrays([tests.security_id,tests.entry_ts],names=['security_id','decision_ts'])
    obs=pd.read_parquet(ROOT/reader.grid['observations'],columns=['observation_id','decision_ts'])
    snapshot=obs[obs.decision_ts.isin(tests.entry_ts.unique())].sort_values('decision_ts').reset_index(drop=True)
    codes=pd.factorize(snapshot.decision_ts)[0];snap_ids=snapshot.observation_id.to_numpy(int)
    checks=[]
    for fid in fids:
        path,col=blocks[fid];raw=np.load(path,mmap_mode='r')[:,col]
        calc=base.loc[target_index,fid].to_numpy();stored=raw[tests.observation_id.to_numpy(int)]
        source_ok=np.allclose(calc,stored,rtol=2e-5,atol=2e-6,equal_nan=True)
        shuffle_ok=np.allclose(base[fid],shuffled[fid],rtol=1e-6,atol=1e-7,equal_nan=True)
        future_ok=np.allclose(base.loc[past.index,fid],past[fid],rtol=1e-6,atol=1e-7,equal_nan=True)
        recomputed,_=build_rank_bins(np.array(raw[snap_ids])[:,None],codes,10)
        packed=reader.read_columns('bins',[fid],0,reader.rows)[:,0]
        actual=decode_packed_bins(packed[snap_ids],10)
        mismatch=int((recomputed[:,0]!=actual).sum())
        checks.append({'feature_id':fid,'trade_checks':len(tests),'source_parity':source_ok,'shuffled_row_invariance':shuffle_ok,'future_truncation_invariance':future_ok,
          'cross_sectional_snapshot_rows':len(snapshot),'bin_mismatches':mismatch,'max_source_error':float(np.nanmax(abs(calc-stored)))})
    reference=base.loc[target_index,'execution_close'].to_numpy();price_error=float(np.max(abs(reference-tests.entry_price.to_numpy())))
    result={'policies':policies,'checks':checks,'raw_entry_price_error':price_error,'holdouts_accessed':False}
    result['passed']=bool(price_error<1e-9 and all(x['source_parity'] and x['shuffled_row_invariance'] and x['future_truncation_invariance'] and x['bin_mismatches']==0 for x in checks))
    (OUT/'finalist_input_audit.json').write_text(json.dumps(result,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)))
    print(json.dumps(result,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),flush=True)
    assert result['passed'],'Input or causal bin audit failed; no quote replay'

def census():
    torch.set_num_threads(4);assert torch.cuda.is_available()
    f=pd.read_parquet(OUT/'annotated_structures.parquet').drop_duplicates(KEY+['target_id'])
    supported=f[(f.fold_sign_min>=.8)&(f.populated_folds_min==f.expected_folds)&(f.active_bps>=1)]
    states=supported.drop_duplicates(KEY).reset_index(drop=True)
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    obs=pd.read_parquet(ROOT/reader.grid['observations'],columns=['observation_id','security_id','session_date','decision_ts'])
    obs=obs.sort_values('observation_id').reset_index(drop=True)
    assert np.array_equal(obs.observation_id.to_numpy(),np.arange(reader.rows))
    assert pd.to_datetime(obs.session_date).between('2025-05-01','2026-04-30').all()
    stamp=pd.to_datetime(obs.decision_ts,utc=True).dt.as_unit('ns').astype('int64').to_numpy()
    sid=pd.factorize(obs.security_id)[0];day,dates=pd.factorize(pd.to_datetime(obs.session_date),sort=True)
    group=pd.factorize(pd.MultiIndex.from_arrays([sid,day]))[0];ngroups=int(group.max())+1
    order=np.lexsort((stamp,day,sid));prev=np.empty(len(obs),dtype='int64');prev[order]=np.roll(order,1)
    linked=(group==group[prev])&(stamp-stamp[prev]==300_000_000_000)
    clock=pd.to_datetime(obs.decision_ts,utc=True).dt.tz_convert('America/New_York')
    minute=(clock.dt.hour*60+clock.dt.minute-570).to_numpy()
    gpu_day=torch.as_tensor(day,device='cuda',dtype=torch.int64)
    gpu_group=torch.as_tensor(group,device='cuda',dtype=torch.int64)
    gpu_prev=torch.as_tensor(prev,device='cuda');gpu_link=torch.as_tensor(linked,device='cuda')
    features=sorted(set(states.feature_a)|set(states.feature_b));bins={};start=time.time()
    for fid in features:
        a=reader.read_columns('bins',[fid],0,reader.rows)[:,0]
        bins[fid]=torch.as_tensor(a.copy(),device='cuda',dtype=torch.uint8)
    lookups={r:torch.as_tensor(np.array([decode_packed_bins(np.arange(256,dtype='uint8'),r)],dtype='int16')[0],device='cuda',dtype=torch.int64) for r in [3,5,10]}
    rows=[];decoded={}
    for i,row in enumerate(states.itertuples()):
        r=int(row.resolution)
        def get(fid):
            k=(fid,r)
            if k not in decoded:decoded[k]=lookups[r][bins[fid].long()].to(torch.int16)
            return decoded[k]
        aa,bb=get(row.feature_a),get(row.feature_b)
        allowed=torch.zeros(r*r+1,device='cuda',dtype=torch.bool)
        allowed[torch.tensor(json.loads(row.cells),device='cuda')]=True
        code=(aa*r+bb).long();valid=(aa>=0)&(bb>=0)
        mask=allowed[code.clamp(0,r*r)]&valid
        episode=mask&~(mask[gpu_prev]&gpu_link)
        daily=torch.bincount(gpu_day[episode],minlength=len(dates)).cpu().numpy()
        groups=torch.bincount(gpu_group[mask],minlength=ngroups)
        selected=torch.nonzero(episode).flatten().cpu().numpy()
        monthly=pd.Series(daily,index=pd.DatetimeIndex(dates)).groupby(pd.DatetimeIndex(dates).to_period('M')).sum()
        active=int(mask.sum());episodes=int(daily.sum())
        rows.append({'active_observations':active,'episodes':episodes,'episodes_per_session':episodes/len(dates),
          'active_sessions':int((daily>0).sum()),'security_sessions':int((groups>0).sum()),
          'observations_per_episode':active/max(episodes,1),'minimum_month_episodes':int(monthly.min()),
          'minimum_month_active_sessions':int(pd.Series(daily>0,index=pd.DatetimeIndex(dates)).groupby(pd.DatetimeIndex(dates).to_period('M')).sum().min()),
          'top5_dates_episode_share':float(np.sort(daily)[-5:].sum()/max(episodes,1)),
          'opening_hour_episode_fraction':float((minute[selected]<60).mean()) if episodes else 0,
          'monthly_episodes':json.dumps(dict(zip(monthly.index.astype(str),monthly.astype(int))))})
        if (i+1)%100==0:print('CENSUS',i+1,'/',len(states),round(time.time()-start),'seconds',flush=True)
    result=pd.concat([states[KEY+['feature_a','feature_b']],pd.DataFrame(rows)],axis=1)
    result.to_parquet(OUT/'opportunity_census.parquet',index=False)
    f.merge(result,on=KEY+['feature_a','feature_b'],how='inner',validate='many_to_one').to_parquet(OUT/'structures_with_opportunities.parquet',index=False)
    (OUT/'opportunity_scope.json').write_text(json.dumps({'states':len(states),'observations':len(obs),'discovery':['2025-05-01','2026-04-30'],
      'episode':'First active observation after inactive state, missing observation, new security or new session; contiguous five-minute active observations count once.',
      'target_availability_used_to_count_opportunities':False,'holdouts_accessed':False,'seconds':time.time()-start},indent=2))
    print('CENSUS_COMPLETE',len(states),round(time.time()-start),'seconds',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['census','surfaces','ledger','audit']);p.add_argument('--tail-wave',action='store_true');a=p.parse_args()
    if a.tail_wave:
        assert a.stage!='census'
        TAIL_WAVE=True;MINIMUM_SIGNAL_MINUTE=60
        OUT=ROOT/'research/canonical_intraday_tail_context_20260930';OUT.mkdir(exist_ok=True)
        DEFINITIONS=[
          {'name':'tail_context_spread','a':'positive_jump_fraction','b':'roll_spread_proxy','r':5,'cells':[19],'side':-1,'holds':[60,120,240],
           'reason':'Coarse r5 positive-jump context with high spread proxy: 21.26bp raw and 11.56bp benchmark-adjusted short at 240 minutes, broad symbol participation, 251 sessions. Distinct from quiet-jump and one-minute shock reversal states.'},
          {'name':'tail_context_sellflow','a':'negative_return_sum_abs','b':'positive_jump_fraction','r':5,'cells':[23],'side':-1,'holds':[60,120,240],
           'reason':'High aggregate selling conditioned on positive-jump context: 21.19bp raw and 11.69bp benchmark-adjusted short at 240 minutes, broad r3 persistence, 251 sessions. Nominated from existing census before its quote outcomes.'}]
    globals()[a.stage]()
