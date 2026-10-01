"""Distinct simple range-breakout and moving-mean reversion baselines."""
import json
import numpy as np,pandas as pd,torch
from competition_scalp import OUT,LEVELS,metrics
from competition_scalp_selective import allocate

DEST=OUT/'new_baselines';DEST.mkdir(exist_ok=True)

def run():
    torch.set_num_threads(4);a=json.loads((OUT/'axes.json').read_text());symbols=a['symbols'];days=a['days']
    cp=np.load(OUT/'close.npy',mmap_mode='r');hi=np.load(OUT/'high.npy',mmap_mode='r');lo=np.load(OUT/'low.npy',mmap_mode='r')
    p=torch.as_tensor(np.array(cp),device='cuda',dtype=torch.float64);log=p.log()
    mean=torch.full_like(p,torch.nan);sd=torch.full_like(p,torch.nan)
    past=log[:,:,:-1].unfold(2,30,1);mean[:,:,30:]=past.mean(-1);sd[:,:,30:]=past.std(-1,unbiased=True)
    z=(log-mean)/sd;ph=torch.full_like(p,torch.nan);pl=torch.full_like(p,torch.nan)
    ph[:,:,30:]=torch.as_tensor(np.array(hi),device='cuda')[:,:,:-1].unfold(2,30,1).amax(-1)
    pl[:,:,30:]=torch.as_tensor(np.array(lo),device='cuda')[:,:,:-1].unfold(2,30,1).amin(-1)
    setups=[('range_breakout',torch.where(p>ph,1.,torch.where(p<pl,-1.,0.)),[5,15])]
    for cut in [2.,2.5]:setups.append((f'mean_reversion_{cut:g}',torch.where(z<=-cut,1.,torch.where(z>=cut,-1.,0.)),[15,30]))
    rows=[];ledgers=[];rules=[]
    for name,signal,holds in setups:
        signal[:,:,:30]=0;signal[:,:,358:]=0;valid=(signal!=0)&torch.isfinite(p)&torch.isfinite(mean)&torch.isfinite(sd)&(sd>0)
        d,s,m=torch.where(valid);side=signal[d,s,m].cpu().numpy().astype(int)
        score=z[d,s,m].abs().cpu().numpy();anchor=mean[d,s,m].exp().cpu().numpy();d,s,m=[x.cpu().numpy() for x in [d,s,m]]
        for hold in holds:
            good=np.isfinite(cp[d,s,m+hold])&(cp[d,s,m]>0);d1,s1,m1,dirn,score1,anchor1=[x[good] for x in [d,s,m,side,score,anchor]]
            for scope,mask in [('etfs',np.isin(s1,[symbols.index('SPY'),symbols.index('QQQ')])),('stocks',~np.isin(s1,[symbols.index('SPY'),symbols.index('QQQ')]))]:
                for ranking in ['hash','signal']:
                    ix=np.flatnonzero(mask);ix=ix[allocate(d1[ix],s1[ix],m1[ix],hold,score1[ix] if ranking=='signal' else np.zeros(len(ix)),3)]
                    if len(ix)<500:continue
                    cid=f'{name}_{hold}m_{scope}_{ranking}';dd,ss,mm,di=d1[ix],s1[ix],m1[ix],dirn[ix]
                    ep0=cp[dd,ss,mm];deadline=cp[dd,ss,mm+hold]
                    rules.append({'candidate_id':cid,'active_observations':int(mask.sum()),'allocated_trades':len(ix),'slots':3,'hold_minutes':hold})
                    for bps in LEVELS:
                        ep=ep0*(1+di*bps/10000)
                        if name.startswith('mean_reversion'):
                            xp=anchor1[ix]*(1-di*bps/10000);exitp=deadline.copy();exit_minute=mm+hold;hit=np.zeros(len(ix),bool)
                            # Ignore same-entry-bar ordering ambiguity; test target only from the following minute.
                            for dt in range(2,hold+1):
                                touched=np.where(di==1,hi[dd,ss,mm+dt]>=xp,lo[dd,ss,mm+dt]<=xp)&~hit
                                exitp[touched]=xp[touched];exit_minute[touched]=mm[touched]+dt;hit|=touched
                            mode=np.where(hit,'target_touch_proxy','deadline_force_proxy')
                        else:
                            exitp=deadline*(1-di*bps/10000);exit_minute=mm+hold;mode=np.full(len(ix),'timed_exit_proxy')
                        rr=di*(exitp-ep)/ep
                        rows.append({'candidate_id':cid,'bps':bps,'ranking':ranking,'scope':scope,'slots':3,**metrics(rr,dd,days,3)})
                        ledgers.append(pd.DataFrame({'candidate_id':cid,'bps':bps,'day':dd,'symbol_code':ss,'signal_minute':mm,'side':di,
                            'entry_reference':ep0,'target_reference':anchor1[ix],'deadline_reference':deadline,'entry_price':ep,'exit_price':exitp,
                            'exit_minute':exit_minute,'hold_minutes':hold,'score':score1[ix],'exit_mode':mode,'return':rr}))
        print('BASELINE',name,'active observations',len(d),flush=True)
    pd.DataFrame(rules).to_parquet(DEST/'rules.parquet',index=False);pd.concat(ledgers).to_parquet(DEST/'bar_trades.parquet',index=False)
    f=pd.DataFrame(rows);f.to_parquet(DEST/'bar_sensitivity.parquet',index=False)
    print(f[f.bps.isin([0,1])][['candidate_id','bps','trades','mean_trade_bps','return_pct','positive_months','max_dd_pct','without_best5_days_pct']].to_string(index=False))
    (DEST/'scope.json').write_text(json.dumps({'discovery':'Full May 2025 to April 2026','out_of_sample_accessed':False,
        'mean_reversion':'Price beyond 2 or 2.5 prior-30m log-price standard deviations; fixed entry-time moving-mean target; time force at 15/30m.',
        'momentum':'Close breaks preceding 30 completed one-minute highs/lows; 5/15m time exit.',
        'ranking':'normalized displacement known at signal vs outcome-independent hash, fixed three capital slots.',
        'entry_reference':'completed signal bar close','entry_latency':'Bar screen only; quote latency required before executable claims.',
        'target_touch':'OHLC path proxy only, not a fill; same-entry-bar target touches ignored; reserve capital through maximum hold.'},indent=2))

if __name__=='__main__':run()
