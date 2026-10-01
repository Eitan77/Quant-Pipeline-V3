"""Discovery-only exits observed on minute opens, executed on a subsequent open."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from intraday_strategy_search import ROOT,OUT,COSTS,obs_arrays
from intraday_entry_search import allocate
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins

DEST=OUT/'exit_extension';DEST.mkdir(exist_ok=True)

def statistics(gross,day):
    out={}
    for c in COSTS:
        ret=(gross-2*c)/10000
        daily=np.expm1(np.bincount(day,weights=np.log1p(ret),minlength=251))
        equity=np.cumprod(1+daily);peak=np.maximum.accumulate(np.r_[1,equity])[1:]
        out.update({f'return_c{c}':float((equity[-1]-1)*100),f'bps_day_c{c}':float(daily.mean()*10000),
                    f'sharpe_c{c}':float(daily.mean()/daily.std(ddof=1)*np.sqrt(252)),
                    f'dd_c{c}':float((1-equity/peak).max()*100)})
    return out

def main():
    torch.set_num_threads(4)
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);minute=t-opens[day]
    rank=np.load(OUT/'fine_ranks.npy',mmap_mode='r');prices=np.load(OUT/'opens.npy',mmap_mode='r')
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    definitions=pd.read_parquet(OUT/'replay_definitions.parquet').set_index('candidate_id')
    states={
        'breakdown5_open':((rank[:,3]<.05)&(rank[:,4]>=.9)&(minute<60),-1),
        'breakdown10_open':((rank[:,3]<.1)&(rank[:,4]>=.9)&(minute<60),-1),
        'breakdown5_allday':((rank[:,3]<.05)&(rank[:,4]>=.9),-1),
        'acceleration_open':((rank[:,4]>=.8)&(rank[:,5]<.2)&(minute<60),-1)}
    for cid in ['C0210','C0355','C0246','C0410','C0412']:
        r=definitions.loc[cid]
        a=decode_packed_bins(reader.read_columns('bins',[r.feature_a],0,reader.rows)[:,0],10)
        b=decode_packed_bins(reader.read_columns('bins',[r.feature_b],0,reader.rows)[:,0],10)
        mask=(a>=0)&(b>=0)&(a*10+b==r.cell)
        if cid=='C0210':mask&=rank[:,4]>=.9
        if cid in ['C0355','C0246']:mask&=rank[:,7]>=.8
        if cid in ['C0410','C0412']:mask&=minute<60
        states[cid]=(mask,int(r.direction))
    rows=[];ledgers=[];trial=0
    for name,(mask,side) in states.items():
        ix=np.flatnonzero(mask&(minute>=5)&(t+8<=closes[day]-5))
        d=day[ix];s=sec[ix];m=minute[ix]+1;ep=prices[d,s,m]
        good=np.isfinite(ep);ix=ix[good];d=d[good];s=s[good];m=m[good];ep=ep[good]
        cap=np.minimum(241,closes[d]-5-(t[ix]+1)).astype(int)
        offsets=np.arange(243)
        raw=prices[d[:,None],s[:,None],np.minimum(m[:,None]+offsets,389)]
        raw[offsets[None,:]>cap[:,None]]=np.nan
        gpu=torch.tensor(raw,device='cuda',dtype=torch.float64)
        returns=(gpu/torch.tensor(ep,device='cuda')[:,None]-1)*side*10000
        take={};stop={}
        for threshold in [2,5,10,20,40,80,160]:
            hit=(returns>=threshold);hit[:,0]=False
            take[threshold]=torch.where(hit.any(1),hit.long().argmax(1)+1,999).cpu().numpy()
        take[0]=np.full(len(ix),999)
        for threshold in [10,25,50,100,200]:
            hit=(returns<=-threshold);hit[:,0]=False
            stop[threshold]=torch.where(hit.any(1),hit.long().argmax(1)+1,999).cpu().numpy()
        stop[0]=np.full(len(ix),999)
        del gpu,returns
        # First executable subsequent raw open; a trigger itself never receives its own observed price.
        next_valid=np.where(np.isfinite(raw),offsets[None,:],999)
        next_valid=np.minimum.accumulate(next_valid[:,::-1],axis=1)[:,::-1]
        previous=prices[d,s,np.maximum(m-6,0)];recent=prices[d,s,m-1]/previous-1
        priorities={'acceleration':np.nan_to_num(rank[ix,4],nan=-1),'recent_move':np.nan_to_num(np.abs(recent),nan=-1)}
        for hold in [5,15,30,60,120,240]:
            for tp,tp_hit in take.items():
                for sl,sl_hit in stop.items():
                    scheduled=np.minimum(np.minimum(tp_hit,sl_hit),np.minimum(hold,cap))
                    actual=next_valid[np.arange(len(ix)),scheduled]
                    valid=actual<999
                    exit_price=raw[np.arange(len(ix)),np.minimum(actual,242)]
                    pnl=side*(exit_price/ep-1)*10000
                    release=t[ix]+1+np.where(valid,actual,cap)
                    for ranking,priority in priorities.items():
                        selected,attempts=allocate(t[ix]+1,release,s,np.ones(len(ix),bool),1,priority=priority)
                        # Any unavailable selected exit invalidates this variant; never silently drop its P&L.
                        missing=int((~valid[selected]).sum())
                        if missing or len(selected)<100:continue
                        g=pnl[selected];ds=d[selected];trial+=1
                        row={'trial':trial,'state':name,'side':side,'ranking':ranking,'hold':hold,'tp_bps':tp,'sl_bps':sl,
                            'trades':len(selected),'trades_day':len(selected)/251,'active_days':len(np.unique(ds)),
                            'gross_bps':float(g.mean()),'median_hold':float(np.median(actual[selected])),**statistics(g,ds)}
                        row['first_half_gross']=float(g[ds<126].mean()) if (ds<126).any() else None
                        row['second_half_gross']=float(g[ds>=126].mean()) if (ds>=126).any() else None
                        daily=np.bincount(ds,weights=g-2,minlength=251)
                        row['bps_day_ex_best5_c1']=float((daily.sum()-np.sort(daily)[-5:].sum())/251)
                        rows.append(row)
                        if row['return_c1']>45 or (row['trades_day']>=5 and row['return_c0']>45):
                            ledgers.append(pd.DataFrame({'trial':trial,'observation_id':ix[selected],'day':ds,'security_code':s[selected],
                                'entry_minute':t[ix[selected]]+1,'exit_minute':release[selected],'gross_bps':g,'side':side}))
        pd.DataFrame(rows).to_parquet(DEST/'results.parquet',index=False)
        print('EXIT STATE',name,'TRIALS',trial,flush=True)
    if ledgers:pd.concat(ledgers).to_parquet(DEST/'leader_trades.parquet',index=False)
    (DEST/'method.json').write_text(json.dumps({'completed':True,'trials':trial,'cost_per_side':COSTS,
       'execution':'signal at five-minute decision, next-minute-open entry; target/stop observed at minute open then filled at first available subsequent open; maximum hold or session close minus five minutes; single position with current equity compounded per trade',
       'no_oos_access':True,'missing_selected_exit':'variant excluded, not individual losing/missing trades'},indent=2))
    print(pd.DataFrame(rows).sort_values('return_c1',ascending=False)[['trial','state','ranking','hold','tp_bps','sl_bps','trades_day','return_c1','sharpe_c1','dd_c1']].head(12).to_string(index=False),flush=True)

if __name__=='__main__':main()
