from intraday_strategy_search import *
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
    targets=[t for t in resident.targets if '__raw__' in t and any(t.startswith('target_'+str(h)+'m__') for h in [1,2,5,10,15,30,60])]
    pairs=pd.read_parquet(OUT/'stable_pair_shortlist.parquet')
    chunks=[]
    for singles, definitions in [(False,list(pairs[['pair_id','feature_a','feature_b']].itertuples(index=False,name=None)))]:
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
    result.to_parquet(OUT/'stable_conditional_cells.parquet',index=False)
    print('CONDITIONAL COMPLETE',len(result),flush=True)

conditional()
