"""Fresh intraday discovery: input gates first, structural maps before strategies."""
import argparse,json,time,hashlib,warnings
from pathlib import Path
import duckdb,numpy as np,pandas as pd,torch
from quant_pipeline.alpha_discovery.features.base import FeatureBuilder
from quant_pipeline.alpha_discovery.models import CompiledFeatureSpec,TimeScale
from competition_under2d import ROOT,EvidenceReader,regions
warnings.filterwarnings('ignore',category=pd.errors.PerformanceWarning)
warnings.filterwarnings('ignore',message='Mean of empty slice')
warnings.filterwarnings('ignore',message='invalid value encountered in scalar divide')

OUT=ROOT/'research/intraday_causal_restart_20260930'
OUT.mkdir(exist_ok=True)
GRID='intraday_5m'
HOLDS=[2,5,10,15,30,60]
TARGET_BASES=['raw']

def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2,default=str),encoding='utf-8')

def registry():
    reader=EvidenceReader(ROOT,'evidence/reader.json',GRID)
    f=pd.read_parquet(ROOT/'feature_registry.parquet')
    return reader,f[f.feature_id.isin(reader.grid['bins'])].drop_duplicates('feature_id').set_index('feature_id')

def spec(row):
    data=row.to_dict();data['feature_id']=row.name
    label=data['scale'];kind='context' if label=='context' else ('paired' if '_' in label else 'minutes')
    data['scale']=TimeScale(kind,None if label=='context' else int(label.split('_')[-1][:-1]),label)
    data['parameters']=json.loads(data['parameters']);return CompiledFeatureSpec(**data)

def audit():
    reader,reg=registry();sm=pd.read_parquet('reference/security_master.parquet')
    ids=sm[sm.symbol.isin(['SPY','QQQ','NVDA','PFE'])].security_id.tolist()
    with duckdb.connect() as c:
        c.execute('SET threads=4');c.execute("SET memory_limit='4GB'")
        c.register('securities',pd.DataFrame({'security_id':ids}))
        f=c.execute('''SELECT p.* FROM read_parquet(?) p JOIN securities s USING(security_id)
          WHERE session_date IN (DATE '2025-05-01',DATE '2025-11-03',DATE '2026-04-29')''',
          [str(ROOT/'cache/calculation_panels/intraday_5m.parquet')]).fetchdf()
    f['decision_ts']=pd.to_datetime(f.decision_ts,utc=True).dt.as_unit('ns')
    excluded=reg[(reg.family.isin(['same_time','calendar']))|(reg.concept_id.isin(['ema_distance','fast_minus_slow_cross_sectional_rank']))]
    specs=[spec(row) for _,row in reg.drop(index=excluded.index).iterrows()]
    def build(frame):
        b=FeatureBuilder(frame.reset_index(drop=True));v=b.build_many(specs).astype('float32')
        return b.frame.join(v).set_index(['security_id','decision_ts']).sort_index()
    print('INPUT_AUDIT',len(f),'minute rows',len(specs),'features',flush=True)
    base=build(f);shuffled=build(f.sample(frac=1,random_state=20260930).reset_index(drop=True))
    clock=f.decision_ts.dt.tz_convert('America/New_York')
    # Truncate once in chronological time; preserve all earlier sessions.
    cutoff=pd.Timestamp('2026-04-29 12:00',tz='America/New_York')
    past=build(f[f.decision_ts<=cutoff].copy())
    emitted=base[base.emit & (base.index.get_level_values('decision_ts').tz_convert('America/New_York').hour>=11)]
    ids=emitted.observation_id.to_numpy(int);rows=[];blocks={}
    for meta in (ROOT/'cache/features'/GRID).glob('*.json'):
        payload=json.loads(meta.read_text())
        if 'columns' in payload:
            for col,fid in enumerate(payload['columns']):blocks[fid]=(meta.with_suffix('.npy'),col)
    for item in specs:
        name=item.feature_id;x=base[name];y=shuffled[name];z=past[name]
        shuffle_ok=np.allclose(x,y,equal_nan=True,rtol=1e-6,atol=1e-7)
        future_ok=np.allclose(base.loc[past.index,name],z,equal_nan=True,rtol=1e-6,atol=1e-7)
        arr,col=blocks[name];actual=np.load(arr,mmap_mode='r')[ids,col];calc=emitted[name].to_numpy()
        finite=np.isfinite(actual)&np.isfinite(calc);count=int(finite.sum())
        parity=count>=100 and np.allclose(actual,calc,equal_nan=True,rtol=2e-5,atol=2e-6)
        rows.append({'feature_id':name,'family':item.family,'shuffle_ok':shuffle_ok,'future_truncation_ok':future_ok,'cached_value_parity':parity,'finite_comparisons':count,'max_absolute_error':float(np.nanmax(abs(actual-calc))) if count else None,'approved':shuffle_ok and future_ok and parity})
    rows.extend({'feature_id':fid,'family':row.family,'approved':False,'reason':'Known EMA corruption or needs separate full-universe/multi-session audit'} for fid,row in excluded.iterrows())
    checks=pd.DataFrame(rows);checks.to_parquet(OUT/'feature_input_audit.parquet',index=False)
    print('AUDIT',int(checks.approved.sum()),'approved /',len(checks),'active features',flush=True)
    print('FAILURE_COUNTS',checks.loc[~checks.approved].groupby('family').size().to_dict(),flush=True)
    save('scope.json',{'discovery':['2025-05-01','2026-04-30'],'holdouts_accessed':False,'previous_strategy_rankings_used':False,
      'objective':'Profitable frequent consistent intraday strategies; causal signals and real limit attainability.',
      'feature_gate':'Bounded source reconstruction, shuffled-row invariance, future truncation and cached-value parity; finalists require expanded checks.',
      'features_approved':int(checks.approved.sum()),'horizons_minutes':HOLDS,'fees':0,'prescribed_bps_per_side':[-1,0,1,2,3,4,5],
      'same_day_exit':True,'quote_policy':'Bar touches localize downloads only; no OHLC fills or missing liabilities removed.'})

def map_space():
    torch.set_num_threads(4);assert torch.cuda.is_available()
    audit=pd.read_parquet(OUT/'feature_input_audit.parquet');allowed=audit.loc[audit.approved,'feature_id'].tolist();_,reg=registry()
    files=[str(p) for stage in ['dual_coarse_results','dual_fine_results','dual_exact_results'] for p in (ROOT/stage/GRID).rglob('*.parquet')]
    c=duckdb.connect();c.execute('SET threads=4');c.execute("SET memory_limit='4GB'")
    c.read_parquet(files,union_by_name=True).create_view('surfaces');c.register('allowed',pd.DataFrame({'feature_id':allowed}))
    labels=['eod' if h=='eod' else f'{h}m' for h in HOLDS]
    targets=[f'target_{label}__{basis}__{GRID}' for label in labels for basis in TARGET_BASES]
    c.register('wanted',pd.DataFrame({'target_id':targets}))
    stream=c.execute('''SELECT s.pair_id,s.feature_a,s.feature_b,s.target_id,s.resolution,s.selected_cell,s.surface_counts,s.surface_sums
      FROM surfaces s JOIN allowed a ON s.feature_a=a.feature_id JOIN allowed b ON s.feature_b=b.feature_id JOIN wanted w USING(target_id)''').fetch_record_batch(2000)
    rows=[];count=0;cells=0;start=time.time();weights={}
    for batch in stream:
        frame=batch.to_pandas()
        for resolution,g in frame.groupby('resolution',sort=False):
            r=int(resolution);g=g.reset_index(drop=True)
            n=torch.as_tensor(np.stack(g.surface_counts),dtype=torch.float64,device='cuda');s=torch.as_tensor(np.stack(g.surface_sums),dtype=torch.float64,device='cuda')*1e4
            count+=len(g);cells+=n.numel();mu=s/n.clamp(min=1);total=n.sum(1);base=s.sum(1)/total.clamp(min=1)
            nn=n.reshape(-1,r,r);ss=s.reshape(-1,r,r)
            ma=ss.sum(2)/nn.sum(2).clamp(min=1);mb=ss.sum(1)/nn.sum(1).clamp(min=1)
            lift=mu-(ma[:,:,None]+mb[:,None,:]-base[:,None,None]).reshape(mu.shape)
            if r not in weights:
                masks,names,w=regions(r,False);weights[r]=(masks,names,torch.as_tensor(w,dtype=torch.float64,device='cuda'))
            masks,names,w=weights[r];rn=n@w;rs=s@w;rm=rs/rn.clamp(min=1);freq=rn/total[:,None].clamp(min=1)
            pop=(n>0).double()@w;pos=((mu>0)&(n>0)).double()@w;neg=((mu<0)&(n>0)).double()@w
            lr=(lift*n)@w/rn.clamp(min=1);contribution=rs.abs()/total[:,None].clamp(min=1)
            common=(rn>=5000)&(freq>=.002)
            for target,tg in g.groupby('target_id',sort=False):
                loc=tg.index.to_numpy();indices=torch.as_tensor(loc,device='cuda')
                for sign in [-1,1]:
                    coherent=(pos==pop) if sign==1 else (neg==pop)
                    good=common&coherent&(rm*sign>0)
                    for lens,metric in [('participation',contribution),('edge',rm*sign),('interaction',lr*sign)]:
                        score=torch.where(good[indices],metric[indices],-torch.inf)
                        values,take=torch.topk(score.flatten(),min(5,score.numel()));take=take[torch.isfinite(values)].cpu().numpy()
                        for flat in take:
                            p,j=np.unravel_index(flat,score.shape);p=int(loc[p]);item=g.iloc[p];active=np.array(masks[j]);ni=n[p].cpu().numpy();mi=mu[p].cpu().numpy()
                            rows.append({'pair_id':item.pair_id,'feature_a':item.feature_a,'feature_b':item.feature_b,'target_id':target,'resolution':r,'cells':json.dumps(masks[j]),'region':names[j],'direction':sign,'lens':lens,
                              'family':reg.loc[item.feature_a,'family']+' / '+reg.loc[item.feature_b,'family'],'active_n':int(rn[p,j]),'frequency':float(freq[p,j]),'active_bps':float(rm[p,j])*sign,'interaction_lift_bps':float(lr[p,j])*sign,'weighted_contribution_bps':float(contribution[p,j]),
                              'parent_a_bps':float(ss[p,np.unique(active//r),:].sum()/nn[p,np.unique(active//r),:].sum().clamp(min=1))*sign,
                              'parent_b_bps':float(ss[p,:,np.unique(active%r)].sum()/nn[p,:,np.unique(active%r)].sum().clamp(min=1))*sign,
                              'surface_n':ni.astype(int).tolist(),'surface_bps':mi.tolist()})
        if count%20000<2000:print('STRUCTURAL_MAP',count,'surfaces',round(time.time()-start),'seconds',flush=True)
    f=pd.DataFrame(rows);keep=[]
    for lens,metric in [('participation','weighted_contribution_bps'),('edge','active_bps'),('interaction','interaction_lift_bps')]:
        g=f[f.lens==lens].sort_values(metric,ascending=False).drop_duplicates(['pair_id','target_id','resolution','cells','direction'])
        keep.append(g.groupby(['target_id','resolution','direction','family'],sort=False).head(2).groupby(['target_id','resolution','direction'],sort=False).head(15))
    f=pd.concat(keep).drop_duplicates(['pair_id','target_id','resolution','cells','direction','lens']);f.to_parquet(OUT/'structural_map.parquet',index=False)
    save('coverage.json',{'surfaces':count,'cells':cells,'approved_features':len(allowed),'gpu':'cuda','seconds':time.time()-start,'kept_structural_views':len(f),'holdouts_accessed':False,'target_ids':targets,'nomination_basis':'Canonical V3 surfaces, not externally proposed mechanisms','beta_residual_excluded_pending_target_input_audit':True})
    print('MAP_COMPLETE',count,cells,len(f),flush=True)

def annotate():
    f=pd.read_parquet(OUT/'structural_map.parquet');requested=f[['pair_id','target_id','resolution']].drop_duplicates()
    with duckdb.connect() as c:
        c.execute('SET threads=4');c.execute("SET memory_limit='4GB'");c.register('wanted',requested)
        t=c.execute('SELECT x.* FROM read_parquet(?) x JOIN wanted w USING(pair_id,target_id,resolution)',[str(ROOT/'cell_temporal_summary.parquet')]).fetchdf().set_index(['pair_id','target_id','resolution'])
        s=c.execute('SELECT x.* FROM read_parquet(?) x JOIN wanted w USING(pair_id,target_id,resolution)',[str(ROOT/'cell_specialist_summary.parquet')]).fetchdf().set_index(['pair_id','target_id','resolution'])
    rows=[]
    for row in f.itertuples():
        ix=np.array(json.loads(row.cells));n=np.array(row.surface_n)[ix];ix=ix[n>0];n=n[n>0]
        key=(row.pair_id,row.target_id,row.resolution);a=t.loc[key];b=s.loc[key]
        sign=np.array(a.fold_positive_fraction if row.direction==1 else a.fold_negative_fraction)[ix]
        breadth=np.array(b.positive_symbol_fraction if row.direction==1 else b.negative_symbol_fraction)[ix]
        rows.append({'fold_sign_min':float(np.nanmin(sign)),'fold_sign_weighted':float(np.average(np.nan_to_num(sign),weights=n)),
          'populated_folds_min':int(np.array(a.populated_fold_count)[ix].min()),'expected_folds':int(np.array(a.expected_fold_count)[ix].max()),
          'minimum_component_fold_n':int(np.array(a.minimum_fold_n)[ix].min()),'symbol_sign_fraction':float(np.average(np.nan_to_num(breadth),weights=n)),
          'symbols_min':int(np.array(b.eligible_symbol_count)[ix].min()),'top5_share_max':float(np.nanmax(np.array(b.top5_symbol_contribution_share)[ix]))})
    out=pd.concat([f.reset_index(drop=True),pd.DataFrame(rows)],axis=1);out.to_parquet(OUT/'annotated_structures.parquet',index=False)
    z=out[(out.fold_sign_min>=.8)&(out.populated_folds_min==out.expected_folds)&(out.active_bps>=1)].drop_duplicates(['pair_id','target_id','resolution','cells','direction'])
    print('TEMPORALLY_SUPPORTED',len(z),flush=True)
    print(z.sort_values('active_bps',ascending=False)[['feature_a','feature_b','target_id','resolution','region','direction','active_n','frequency','active_bps','fold_sign_min','symbol_sign_fraction','top5_share_max']].head(18).to_string(index=False),flush=True)
    print('HIGH_PARTICIPATION',flush=True)
    print(z.sort_values('weighted_contribution_bps',ascending=False)[['feature_a','feature_b','target_id','resolution','region','direction','active_n','frequency','active_bps','fold_sign_min','symbol_sign_fraction','top5_share_max']].head(12).to_string(index=False),flush=True)

def probe_rules():
    """Signal-only episodes, known calendar, fixed slots; no future target gating."""
    import exchange_calendars as xc
    from competition_fresh_capacity import allocate
    reader,reg=registry();names=[]
    definitions=[
      ('breadth_jump','breakout_distance','positive_jump_fraction',10,[54],1,[15,30,60]),
      ('breadth_jump_region','breakout_distance','positive_jump_fraction',10,[44,45,54,55],1,[30]),
      ('breadth_jump_coarse','breakout_distance','positive_jump_fraction',5,[12],1,[30]),
      ('liquid_jump_fade','corwin_schultz_spread_proxy','positive_jump_fraction',5,[5],-1,[15,30,60]),
      ('liquid_jump_fade_region','corwin_schultz_spread_proxy','positive_jump_fraction',5,[0,5,10],-1,[30]),
      ('breakdown_rebound','breakdown_distance','market_downside_vol',5,[16],1,[30,60]),
      ('frequent_jump_fade','jump_fraction','positive_jump_fraction',5,[12],-1,[30,60])]
    from competition_under2d import decode_packed_bins
    cache={};episodes=[];opportunities=[];rules=[]
    cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    closemap=dict(zip(cal.index.date,pd.to_datetime(cal['close'],utc=True)-pd.Timedelta(minutes=1)))
    with duckdb.connect() as c:
        c.execute('SET threads=4');c.execute("SET memory_limit='5GB'")
        for label,aconcept,bconcept,res,cells,side,holds in definitions:
            fa=reg[reg.concept_id==aconcept].index[0];fb=reg[reg.concept_id==bconcept].index[0]
            def bins(fid):
                key=(fid,res)
                if key not in cache:cache[key]=decode_packed_bins(reader.read_columns('bins',[fid],0,reader.rows)[:,0],res)
                return cache[key]
            aa,bb=bins(fa),bins(fb);mask=np.isin(aa*res+bb,cells)&(aa>=0)&(bb>=0)
            selected=pd.DataFrame({'observation_id':np.flatnonzero(mask)});c.register('selected',selected)
            f=c.execute('''SELECT o.observation_id,o.security_id,o.session_date,o.decision_ts FROM read_parquet(?) o
               JOIN selected USING(observation_id)''',[str(ROOT/reader.grid['observations'])]).fetchdf()
            f=f.sort_values(['security_id','session_date','decision_ts']);prior=f.groupby(['security_id','session_date']).decision_ts.shift()
            f=f[(f.decision_ts-prior)!=pd.Timedelta(minutes=5)].copy()
            rawepisodes=len(f);f['entry_ts']=pd.to_datetime(f.decision_ts,utc=True).dt.as_unit('ns')
            for hold in holds:
                g=f.copy();g['exit_ts']=g.entry_ts+pd.Timedelta(minutes=hold)
                g=g[g.exit_ts<=pd.to_datetime(g.session_date.dt.date.map(closemap),utc=True)].copy()
                g['candidate_id']=f'{label}_{hold}m';g['direction']=side;g['hold_minutes']=hold;g['rank_score']=0
                k=allocate(g,10,False);episodes.append(k)
                hour=g.entry_ts.dt.tz_convert('America/New_York').dt.hour
                opportunities.append({'candidate_id':g.candidate_id.iloc[0],'active_observations':len(selected),'uncensored_episodes':rawepisodes,'legal_episodes':len(g),'nomination_trades':len(k),'dates':g.session_date.nunique(),'decision_windows':g.entry_ts.nunique(),'opening_hour_fraction':float((hour<11).mean()),'symbols':g.security_id.nunique()})
                rules.append({'candidate_id':g.candidate_id.iloc[0],'feature_a':fa,'feature_b':fb,'resolution':res,'cells':cells,'direction':side,'hold_minutes':hold,'slots':10,'ranking':'stable identity/date hash','signal_only_selection':True,'no_future_target_or_action_gates':True,'lane_reservation':'scheduled exit plus 60 seconds; missed entries retain their reservation'})
            print('OPPORTUNITY',label,len(selected),'observations',rawepisodes,'episodes',flush=True)
        pool=pd.concat(episodes,ignore_index=True);points=pd.concat([pool[['security_id',col]].rename(columns={col:'stamp'}) for col in ['entry_ts','exit_ts']]).drop_duplicates()
        requested=pd.concat([points.assign(availability_ts_utc=points.stamp-pd.Timedelta(minutes=k)) for k in range(5)],ignore_index=True)
        c.register('needed',requested)
        prices=c.execute('''SELECT n.security_id,n.stamp,b.symbol,b.execution_close reference_price,b.availability_ts_utc reference_availability
          FROM read_parquet(?) b JOIN needed n USING(security_id,availability_ts_utc)
          QUALIFY row_number() OVER(PARTITION BY n.security_id,n.stamp ORDER BY b.availability_ts_utc DESC)=1''',[str(ROOT/'cache/calculation_panels/intraday_5m.parquet')]).fetchdf()
    pool=pool.merge(prices.rename(columns={'stamp':'entry_ts','reference_price':'entry_price','reference_availability':'entry_reference_availability'}),on=['security_id','entry_ts'],how='left',validate='many_to_one')
    pool=pool.merge(prices.drop(columns='symbol').rename(columns={'stamp':'exit_ts','reference_price':'exit_price','reference_availability':'exit_reference_availability'}),on=['security_id','exit_ts'],how='left',validate='many_to_one')
    pool.to_parquet(OUT/'initial_policy_pricing.parquet',index=False)
    # A holding always has a causal earlier trade reference. An absent recent
    # bar cannot remove it: use its last completed same-session trade for the
    # exit limit, retain the age, and require quotes to price its eventual fill.
    missing=pool[~pool.exit_price.gt(0)][['security_id','session_date','exit_ts']].drop_duplicates()
    if len(missing):
        with duckdb.connect() as c:
            c.execute('SET threads=4');c.register('missing',missing)
            fallback=c.execute('''SELECT n.security_id,n.exit_ts,arg_max(b.execution_close,b.availability_ts_utc) fallback_price,
                 max(b.availability_ts_utc) fallback_availability
              FROM read_parquet(?) b JOIN missing n USING(security_id,session_date)
              WHERE b.availability_ts_utc<=n.exit_ts GROUP BY 1,2''',[str(ROOT/'cache/calculation_panels/intraday_5m.parquet')]).fetchdf()
        pool=pool.merge(fallback,on=['security_id','exit_ts'],how='left',validate='many_to_one')
        pool['exit_stale_fallback']=~pool.exit_price.gt(0)
        pool['exit_price']=pool.exit_price.fillna(pool.fallback_price)
        pool['exit_reference_availability']=pool.exit_reference_availability.fillna(pool.fallback_availability)
    else:pool['exit_stale_fallback']=False
    save('initial_reference_integrity.json',{'nominations':len(pool),'stale_exit_fallbacks':int(pool.exit_stale_fallback.sum()),'bar_projection_only':True,'no_liabilities_removed':True,'holdouts_accessed':False})
    assert pool.entry_price.gt(0).all(),'No known entry reference'
    assert pool.exit_price.gt(0).all(),'Missing closing liability: no claim'
    assert (pool.entry_reference_availability<=pool.entry_ts).all()
    pool['session_date']=pd.to_datetime(pool.session_date);pool['order_id']=np.arange(len(pool));pool.to_parquet(OUT/'initial_policy_pool.parquet',index=False)
    pd.DataFrame(opportunities).to_parquet(OUT/'opportunities.parquet',index=False);save('initial_rules.json',rules)
    rows=[];days=cal.index.strftime('%Y-%m-%d').tolist()
    from competition_scalp import metrics
    for cid,g in pool.groupby('candidate_id'):
        day=pd.Index(days).get_indexer(g.entry_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d'))
        for bps in [-1,0,1,2,3,4,5]:
            e=g.entry_price.to_numpy()*(1+g.direction.to_numpy()*bps/1e4);x=g.exit_price.to_numpy()*(1-g.direction.to_numpy()*bps/1e4)
            ret=g.direction.to_numpy()*(x/e-1);sym=pd.Series(ret).groupby(g.security_id.to_numpy()).sum().sort_values(ascending=False)
            trim=~g.security_id.isin(sym.head(5).index)
            rows.append({'candidate_id':cid,'bps':bps,'mean_ex_top5_bps':float(ret[trim].mean()*1e4),'symbols':len(sym),'top5_profit_share':float(sym.head(5).sum()/sym.sum()),**metrics(ret,day,days,10)})
    results=pd.DataFrame(rows);results.to_parquet(OUT/'initial_bar_sensitivity.parquet',index=False)
    print(results[results.bps==0][['candidate_id','trades','symbols','mean_trade_bps','return_pct','positive_months','positive_week_fraction','max_dd_pct','mean_ex_top5_bps']].to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['audit','map_space','annotate','probe_rules'])
    p.add_argument('--expanded-canonical',action='store_true');a=p.parse_args()
    if a.expanded_canonical:
        assert a.stage in ['map_space','annotate'],'Expanded scope is descriptive evidence only'
        import shutil
        prior=OUT
        OUT=ROOT/'research/canonical_intraday_hypotheses_20260930';OUT.mkdir(exist_ok=True)
        shutil.copyfile(prior/'feature_input_audit.parquet',OUT/'feature_input_audit.parquet')
        HOLDS=[1,2,5,10,15,30,60,120,240,'eod'];TARGET_BASES=['raw','benchmark_adjusted']
    globals()[a.stage]()
