"""Evidence-led full-year discovery. Broad summaries, then focused hypotheses."""
import json,time,gc
from pathlib import Path
import duckdb,numpy as np,pandas as pd
from competition_under2d import ROOT,regions

OUT=ROOT/'research/competition_full_year_under2d_20260930'
GRIDS=['preclose_1555','daily_close','intraday_5m']

def setup():
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'scope.json').write_text(json.dumps({'discovery_start':'2025-05-01','discovery_end':'2026-04-30',
        'max_hold_seconds_exclusive':172800,'out_of_sample_accessed':False,'previous_research_rankings_used':False,
        'process':'Full surfaces: edge, participation, lift, coherent regions, specialists. Follow structural evidence; build focused rules and execution tests.',
        'bps_per_side':[-1,0,1,2,3,4,5]},indent=2))
    old=ROOT/'research/competition_under2d_20260930'
    (old/'SUPERSEDED.txt').write_text('Superseded: the user requires the entire year for discovery. The artificial training/later split is not the research protocol. See competition_full_year_under2d_20260930.')

def broad(grid,target_filter=None):
    con=duckdb.connect();con.execute("SET memory_limit='5GB'");con.execute('SET threads=4')
    files=[str(p) for stage in ['dual_coarse_results','dual_fine_results','dual_exact_results'] for p in (ROOT/stage/grid).rglob('*.parquet')]
    con.read_parquet(files,union_by_name=True).create_view('surfaces')
    if target_filter is None:target_filter="target_id LIKE '%__raw__%'"+(" AND target_id LIKE 'target_1d__%'" if grid=='daily_close' else '')
    reg=pd.read_parquet(ROOT/'feature_registry.parquet').drop_duplicates('feature_id').set_index('feature_id')
    rows=[];surfaces=0;cells=0;t0=time.time()
    reader=con.execute(f'''SELECT pair_id,feature_a,feature_b,target_id,resolution,selected_cell,
       surface_counts,surface_sums FROM surfaces WHERE {target_filter} ORDER BY resolution''').fetch_record_batch(2000)
    for batch in reader:
        f=batch.to_pandas()
        for r,g in f.groupby('resolution',sort=False):
            r=int(r);n=np.stack(g.surface_counts).astype(float);s=np.stack(g.surface_sums)*1e4
            surfaces+=len(g);cells+=n.size
            mu=np.divide(s,n,out=np.zeros_like(s),where=n>0)
            nn=n.reshape(-1,r,r);ss=s.reshape(-1,r,r)
            base=s.sum(axis=1)/np.maximum(n.sum(axis=1),1)
            marg_a=np.divide(ss.sum(axis=2),nn.sum(axis=2),out=np.zeros((len(g),r)),where=nn.sum(axis=2)>0)
            marg_b=np.divide(ss.sum(axis=1),nn.sum(axis=1),out=np.zeros((len(g),r)),where=nn.sum(axis=1)>0)
            lift=mu-(marg_a[:,:,None]+marg_b[:,None,:]-base[:,None,None]).reshape(mu.shape)
            masks,names,w=regions(r,False)
            rn=n@w;rs=s@w;rm=np.divide(rs,rn,out=np.zeros_like(rs),where=rn>0)
            freq=rn/np.maximum(n.sum(axis=1)[:,None],1);direction=np.sign(rm)
            # Coherent unions: each materially populated component shares the region's sign.
            signs=((mu>=0)&(n>0)).astype(float)@w
            populated=(n>0).astype(float)@w
            coherent=np.where(direction>0,signs>=populated-0.01,signs<0.01)
            supported=(rn>=(1000 if grid=='intraday_5m' else 100))&coherent
            contribution=np.abs(rs)/np.maximum(n.sum(axis=1)[:,None],1)
            lift_region=(lift*n)@w/np.maximum(rn,1)
            # Distinct lenses retained separately, never represented as one quality score.
            metrics={'large_edge':np.abs(rm),'participation':contribution,
                     'interaction':np.abs(lift_region),'frequent_edge':np.where(freq>=0.02,np.abs(rm),-np.inf)}
            for ti,(target,tg) in enumerate(g.groupby('target_id',sort=False)):
                ind=g.index.get_indexer(tg.index)
                for sign in [-1,1]:
                    for lens,metric in metrics.items():
                        z=np.where(supported[ind]&(direction[ind]==sign),metric[ind],-np.inf)
                        k=min(6,np.isfinite(z).sum())
                        if not k:continue
                        take=np.argpartition(z.ravel(),-k)[-k:]
                        for flat in take:
                            pi,ri=np.unravel_index(flat,z.shape);pi=ind[pi];row=g.iloc[pi]
                            selected=list(masks[ri]);active=np.array(selected)
                            edge=float(rm[pi,ri]*sign)
                            rows.append({'grid':grid,'pair_id':row.pair_id,'feature_a':row.feature_a,'feature_b':row.feature_b,
                                'family':reg.loc[row.feature_a,'family']+' / '+reg.loc[row.feature_b,'family'],
                                'concepts':reg.loc[row.feature_a,'concept_id']+' / '+reg.loc[row.feature_b,'concept_id'],
                                'target_id':target,'resolution':r,'cells':json.dumps(selected),'region':names[ri],'direction':sign,'lens':lens,
                                'active_n':int(rn[pi,ri]),'frequency':float(freq[pi,ri]),'active_bps':edge,
                                'weighted_contribution_bps':float(contribution[pi,ri]),'interaction_lift_bps':float(lift_region[pi,ri]*sign),
                                'parent_a_bps':float(ss[pi,np.unique(active//r),:].sum()/max(nn[pi,np.unique(active//r),:].sum(),1)*sign),
                                'parent_b_bps':float(ss[pi,:,np.unique(active%r)].sum()/max(nn[pi,:,np.unique(active%r)].sum(),1)*sign),
                                'scanner_selected_cell':int(row.selected_cell),'surface_n':n[pi].astype(int).tolist(),'surface_bps':mu[pi].tolist()})
        if len(rows)>12000:rows=compact(pd.DataFrame(rows)).to_dict('records')
    f=compact(pd.DataFrame(rows));f.to_parquet(OUT/f'broad_{grid}.parquet',index=False)
    (OUT/f'coverage_{grid}.json').write_text(json.dumps({'canonical_surfaces':surfaces,'canonical_cells':cells,'seconds':time.time()-t0},indent=2))
    print('BROAD',grid,surfaces,cells,len(f),'seconds',round(time.time()-t0),flush=True)

def compact(f):
    keep=[]
    for lens,metric in [('large_edge','active_bps'),('participation','weighted_contribution_bps'),('interaction','interaction_lift_bps'),('frequent_edge','active_bps')]:
        g=f[f.lens==lens].sort_values(metric,ascending=False).copy()
        g['edge_round']=g.active_bps.round(6)
        g=g.drop_duplicates(['target_id','direction','resolution','active_n','edge_round'])
        # Preserve economic family diversity and every target, sign and resolution.
        g=g.groupby(['target_id','direction','resolution','family'],sort=False).head(4)
        keep.append(g.groupby(['target_id','direction','resolution'],sort=False).head(24))
    return pd.concat(keep).drop_duplicates(['pair_id','target_id','resolution','cells','direction','lens'])

def annotate(valid_components_only=False):
    f=pd.concat([pd.read_parquet(OUT/f'broad_{g}.parquet') for g in GRIDS],ignore_index=True)
    c=duckdb.connect();c.execute("SET memory_limit='6GB'");c.execute('SET threads=4')
    pairs=f[['pair_id','target_id','resolution']].drop_duplicates();c.register('requested',pairs)
    t=c.execute('SELECT t.* FROM read_parquet(?) t JOIN requested r USING(pair_id,target_id,resolution)',[str(ROOT/'cell_temporal_summary.parquet')]).fetchdf()
    s=c.execute('SELECT t.* FROM read_parquet(?) t JOIN requested r USING(pair_id,target_id,resolution)',[str(ROOT/'cell_specialist_summary.parquet')]).fetchdf()
    t=t.set_index(['pair_id','target_id','resolution']);s=s.set_index(['pair_id','target_id','resolution'])
    annotation=[]
    for row in f.itertuples():
        key=(row.pair_id,row.target_id,row.resolution);ix=np.array(json.loads(row.cells));weights=np.array(row.surface_n)[ix]
        if valid_components_only:
            ix=ix[weights>0];weights=weights[weights>0]
        tr=t.loc[key];sr=s.loc[key];positive=tr.fold_positive_fraction if row.direction==1 else tr.fold_negative_fraction
        annotation.append({'fold_sign_fraction_min':float(np.min(np.array(positive)[ix])),
            'fold_sign_fraction_weighted':float(np.average(np.nan_to_num(np.array(positive)[ix],nan=0.),weights=np.maximum(weights,1))),
            'populated_folds_min':int(np.min(np.array(tr.populated_fold_count)[ix])),
            'expected_folds_max':int(np.max(np.array(tr.expected_fold_count)[ix])),
            'worst_component_fold_bps':float(np.min((np.array(tr.worst_fold_bps) if row.direction==1 else -np.array(tr.best_fold_bps))[ix])),
            'minimum_component_fold_n':int(np.min(np.array(tr.minimum_fold_n)[ix])),
            'eligible_symbols_min':int(np.min(np.array(sr.eligible_symbol_count)[ix])),
            'symbol_sign_fraction':float(np.average((np.array(sr.positive_symbol_fraction) if row.direction==1 else np.array(sr.negative_symbol_fraction))[ix],weights=np.maximum(weights,1))),
            'top5_share_max':float(np.max(np.array(sr.top5_symbol_contribution_share)[ix])),
            'best_local_bps':float(np.max((np.array(sr.best_positive_local_bps) if row.direction==1 else -np.array(sr.best_negative_local_bps))[ix])),
            'cancellation_max':float(np.max(np.array(sr.cancellation_score)[ix]))})
    out=pd.concat([f.reset_index(drop=True),pd.DataFrame(annotation)],axis=1);out.to_parquet(OUT/'evidence_map.parquet',index=False)
    print('MAP',len(out),flush=True)
    for grid in GRIDS:
        good=out[(out.grid==grid)&(out.fold_sign_fraction_min>=0.8)&(out.active_bps>5)].drop_duplicates(['pair_id','target_id','resolution','cells','direction'])
        print(grid,good.sort_values('weighted_contribution_bps',ascending=False)[['pair_id','feature_a','feature_b','target_id','resolution','region','direction','active_n','frequency','active_bps','interaction_lift_bps','fold_sign_fraction_min','symbol_sign_fraction']].head(10).to_string(index=False),flush=True)

if __name__=='__main__':
    setup()
    for grid in GRIDS:broad(grid)
    annotate()
