"""Selective shock tails and causal ranking under fixed capital limits."""
import json
import numpy as np,pandas as pd,torch
from competition_scalp import OUT,LEVELS,metrics

DEST=OUT/'selective';DEST.mkdir(exist_ok=True)

def allocate(d,s,m,hold,score,slots):
    tie=(s.astype(np.uint64)+1)*np.uint64(2654435761)+(d.astype(np.uint64)+1)*np.uint64(2246822519)
    order=np.lexsort((tie,-score,m,d));free=np.full(slots,-1);active=np.full(int(s.max())+1,-1);last=-1;kept=[]
    for j in order:
        if d[j]!=last:free[:]=-1;active[:]=-1;last=d[j]
        entry=m[j]+1;exit=entry+hold+1
        if active[s[j]]>entry:continue
        slot=free.argmin()
        if free[slot]>entry:continue
        kept.append(j);free[slot]=exit;active[s[j]]=exit
    return np.array(kept,dtype=int)

def run():
    torch.set_num_threads(4);a=json.loads((OUT/'axes.json').read_text());symbols=a['symbols']
    cp=np.load(OUT/'close.npy',mmap_mode='r');p=torch.as_tensor(np.array(cp),device='cuda',dtype=torch.float64)
    ret=torch.full_like(p,torch.nan);ret[:,:,1:]=torch.log(p[:,:,1:]/p[:,:,:-1])
    sigma=torch.full_like(p,torch.nan);sigma[:,:,30:]=ret[:,:,:-1].unfold(2,30,1).std(dim=-1,unbiased=True)
    signed=ret/sigma;z=signed.abs();trend=torch.full_like(p,torch.nan)
    trend[:,:,16:]=torch.log(p[:,:,15:-1]/p[:,:,:-16])/(sigma[:,:,16:]*np.sqrt(15))
    valid=(z>=1.5)&torch.isfinite(z);valid[:,:,:30]=False;valid[:,:,378:]=False
    d,s,m=torch.where(valid);side=-torch.sign(signed[d,s,m]);strength=z[d,s,m];tr=trend[d,s,m]
    market_z=z[:,symbols.index('SPY'),:][d,m]
    d,s,m,side,strength,tr,market_z=[x.cpu().numpy() for x in [d,s,m,side,strength,tr,market_z]]
    side=side.astype(int);rows=[];ledgers=[];rules=[]
    for universe,universe_mask in [('etfs',np.isin(s,[symbols.index('SPY'),symbols.index('QQQ')])),('stocks',~np.isin(s,[symbols.index('SPY'),symbols.index('QQQ')]))]:
        thresholds={q:float(np.quantile(strength[universe_mask],q)) for q in [.8,.9,.95]}
        # Full-year discovery chooses these fixed thresholds; later OOS remains sealed.
        policies=[('broad_hash',universe_mask,np.zeros(len(d))),('broad_rank',universe_mask,strength)]
        for q,cut in thresholds.items():policies.append((f'tail{round(q*100)}',universe_mask&(strength>=cut),strength))
        policies.extend([('tail90_morning',universe_mask&(strength>=thresholds[.9])&(m<90),strength),
            ('tail90_with_trend',universe_mask&(strength>=thresholds[.9])&(side*tr>=.5),strength),
            ('tail90_with_trend_neighbor',universe_mask&(strength>=thresholds[.9])&(side*tr>=1),strength)])
        if universe=='stocks':policies.append(('tail90_quiet_market',universe_mask&(strength>=thresholds[.9])&(market_z<1),strength))
        for hold in [5,10]:
            for policy,mask,score in policies:
                indices=np.flatnonzero(mask);ee=cp[d[indices],s[indices],m[indices]];xx=cp[d[indices],s[indices],m[indices]+hold]
                finite=np.isfinite(ee)&np.isfinite(xx)&(ee>0)&(xx>0);indices=indices[finite]
                for slots in ([1,3] if policy in ['broad_hash','broad_rank','tail90'] else [3]):
                    ix=indices[allocate(d[indices],s[indices],m[indices],hold,score[indices],slots)]
                    if not len(ix):continue
                    cid=f'{universe}_{policy}_{hold}m_slots{slots}'
                    f=pd.DataFrame({'candidate_id':cid,'day':d[ix],'symbol_code':s[ix],'signal_minute':m[ix],
                        'side':side[ix],'entry_price':cp[d[ix],s[ix],m[ix]],'exit_price':cp[d[ix],s[ix],m[ix]+hold],
                        'hold_minutes':hold,'score':strength[ix],'prior_trend':tr[ix],'market_z':market_z[ix]})
                    ledgers.append(f)
                    rules.append({'candidate_id':cid,'universe':universe,'policy':policy,'hold_minutes':hold,'slots':slots,
                        'tail80_sigma':thresholds[.8],'tail90_sigma':thresholds[.9],'tail95_sigma':thresholds[.95],
                        'eligible_observations':len(indices),'allocated_trades':len(f),'capacity_or_overlap_rejections':len(indices)-len(f)})
                    for bps in LEVELS:
                        ep=f.entry_price.to_numpy()*(1+f.side.to_numpy()*bps/10000);xp=f.exit_price.to_numpy()*(1-f.side.to_numpy()*bps/10000)
                        rr=f.side.to_numpy()*(xp-ep)/ep
                        rows.append({'candidate_id':cid,'bps':bps,'slots':slots,**metrics(rr,f.day.to_numpy(),a['days'],slots)})
        print('SELECTIVE',universe,'tail sigma thresholds',thresholds,flush=True)
    pd.concat(ledgers).to_parquet(DEST/'trades.parquet',index=False);pd.DataFrame(rules).to_parquet(DEST/'rules.parquet',index=False)
    result=pd.DataFrame(rows);result.to_parquet(DEST/'bar_sensitivity.parquet',index=False)
    for bps in [0,1]:
        view=result[(result.bps==bps)&(result.trades>=500)].sort_values(['positive_months','without_best5_days_pct'],ascending=False)
        print('BPS',bps,view[['candidate_id','trades','mean_trade_bps','return_pct','positive_months','positive_week_fraction','without_best5_days_pct']].head(12).to_string(index=False),flush=True)
    (DEST/'scope.json').write_text(json.dumps({'discovery':'2025-05-01 through 2026-04-30','out_of_sample_accessed':False,
        'ranking':'descending normalized shock known at decision; stable identity ties; no realized-return ranking',
        'threshold_training':'Full discovery year; fixed tail80/90/95 thresholds, never rolling future outcomes.',
        'filters':'morning, reversal aligned with pre-shock 15m trend, quiet market for stocks',
        'references':'completed signal bar close; completed bar close at planned exit',
        'slots':[1,3],'limits_bps_per_side':LEVELS},indent=2))

if __name__=='__main__':run()
