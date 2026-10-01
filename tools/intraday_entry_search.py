"""Bounded discovery extension: all-day states and pending-order capital accounting."""
import json
import numpy as np
import pandas as pd
import torch
from intraday_strategy_search import ROOT,OUT,COSTS,obs_arrays,metrics
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins

DEST=OUT/'entry_extension';DEST.mkdir(exist_ok=True)

def allocate(submit,release,sid,filled,slots,seed=0,priority=None):
    tie=((sid.astype(np.uint64)+1)*2654435761+np.uint64(seed)*2246822519)%4294967291
    order=np.lexsort((tie,submit)) if priority is None else np.lexsort((tie,-priority,submit))
    clock=submit[order]
    free=np.full(slots,-1,np.int64);active=np.full(int(sid.max(initial=0))+1,-1,np.int64)
    take=[];attempts=0;j=0
    while j<len(order):
        slot=int(free.argmin())
        if clock[j]<free[slot]:
            j=int(np.searchsorted(clock,free[slot]))
            if j>=len(order):break
        i=order[j];j+=1
        if active[sid[i]]>submit[i]:continue
        attempts+=1;free[slot]=release[i];active[sid[i]]=release[i]
        if filled[i]:take.append(i)
    return np.asarray(take,np.int64),attempts

def main():
    torch.set_num_threads(4)
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes'])
    minute=t-opens[day]
    prices=torch.tensor(np.load(OUT/'opens.npy'),device='cuda',dtype=torch.float64)
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    defs=pd.read_parquet(OUT/'replay_definitions.parquet')
    defs=defs[~(defs.feature_a.str.contains('ema_distance')|defs.feature_b.str.contains('ema_distance'))]
    defs=defs.drop_duplicates(['feature_a','feature_b','cell','direction'])
    rows=[];best_trades=[];trial=0
    for count,r in enumerate(defs.itertuples()):
        a=decode_packed_bins(reader.read_columns('bins',[r.feature_a],0,reader.rows)[:,0],10)
        b=decode_packed_bins(reader.read_columns('bins',[r.feature_b],0,reader.rows)[:,0],10) if r.feature_b else None
        state=a if b is None else np.where((a>=0)&(b>=0),a*10+b,-1)
        ix=np.flatnonzero((state==r.cell)&(minute>=5)&(t+12<=closes[day]-5))
        if len(ix)<500:continue
        di=torch.tensor(day[ix],device='cuda');si=torch.tensor(sec[ix],device='cuda');mi=torch.tensor(minute[ix]+1,device='cuda')
        anchor=prices[di,si,mi]
        for offset in [0,2,5,10,20]:
            # Passive proxy: submit after observing the anchor open. Reserve capital even for expired orders.
            limit=anchor*(1-r.direction*offset/10000)
            if offset==0:
                filled=torch.isfinite(anchor);delay=torch.zeros(len(ix),device='cuda',dtype=torch.long);ep=anchor
            else:
                path=prices[di[:,None],si[:,None],mi[:,None]+torch.arange(1,6,device='cuda')]
                touch=(path<=limit[:,None]) if r.direction==1 else (path>=limit[:,None])
                touch&=torch.isfinite(path);filled=touch.any(1);delay=touch.long().argmax(1)+1;ep=limit
            for hold in [2,5,10,15,30,60,120,240]:
                exit_idx=mi+delay+hold
                xp=prices[di,si,exit_idx.clamp(0,389)]
                valid=filled&torch.isfinite(xp)&(exit_idx<=torch.tensor(closes[day[ix]]-opens[day[ix]]-5,device='cuda'))
                gross=(r.direction*(xp/ep-1)*10000).cpu().numpy()
                vf=valid.cpu().numpy();d=delay.cpu().numpy()
                release=np.where(vf,t[ix]+1+d+hold,t[ix]+6)
                for lo,hi in [(5,60),(60,150),(150,270),(270,385),(5,385)]:
                    select=(minute[ix]>=lo)&(minute[ix]<hi)
                    loc=np.flatnonzero(select)
                    if vf[loc].sum()<200:continue
                    for slots in [5,10]:
                        taken,attempts=allocate(t[ix[loc]]+1,release[loc],sec[ix[loc]],vf[loc],slots)
                        picked=loc[taken]
                        if len(picked)<100:continue
                        trial+=1;pnl=gross[picked];dd=day[ix[picked]]
                        row={'trial':trial,'candidate_id':r.candidate_id,'offset_bps':offset,'hold':hold,'lo':lo,'hi':hi,
                            'slots':slots,'attempts':attempts,'trades':len(picked),'fill_fraction':len(picked)/attempts,
                            'trades_day':len(picked)/251,'active_days':len(np.unique(dd)),'gross_bps':float(pnl.mean())}
                        for c in COSTS:row.update({f'{k}_c{c}':v for k,v in metrics((pnl-2*c)/slots,dd).items()})
                        rows.append(row)
                        if row['bps_day_c1']>10 or (hold<=15 and row['bps_day_c1']>3):
                            best_trades.append(pd.DataFrame({'trial':trial,'observation_id':ix[picked],
                                'entry_minute':t[ix[picked]]+1+d[picked],'exit_minute':release[picked],
                                'gross_bps':pnl,'day':dd,'security_code':sec[ix[picked]]}))
        print('ENTRY STATES',count+1,len(defs),'TRIALS',trial,flush=True)
        pd.DataFrame(rows).to_parquet(DEST/'results.parquet',index=False)
    defs.to_parquet(DEST/'states.parquet',index=False)
    if best_trades:pd.concat(best_trades).to_parquet(DEST/'leaders_trades.parquet',index=False)
    (DEST/'method.json').write_text(json.dumps({'cost_per_side':COSTS,'discovery_end':'2026-04-30',
        'limit_proxy':'anchor observed at decision+1; 5-minute expiry; sampled future raw opens crossing limit; fill at limit; no queue model; pending orders reserve slots',
        'trial_count':trial,'completed':True},indent=2))
    print(pd.DataFrame(rows).sort_values('bps_day_c1',ascending=False).head(12).to_string(index=False),flush=True)

if __name__=='__main__':main()
