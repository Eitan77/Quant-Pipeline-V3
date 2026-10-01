"""Causal confirmation and crossing overlays on discovery entry candidates."""
import json
import numpy as np
import pandas as pd
from intraday_strategy_search import ROOT,OUT,COSTS,obs_arrays,metrics
from intraday_entry_search import allocate,DEST
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins

def main():
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);minute=t-opens[day]
    price=np.load(OUT/'opens.npy',mmap_mode='r');ranks=np.load(OUT/'fine_ranks.npy',mmap_mode='r')
    reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    definitions=pd.read_parquet(OUT/'replay_definitions.parquet').set_index('candidate_id')
    all_results=pd.read_parquet(DEST/'results.parquet');chosen=[]
    # Preserve faster, zero-cost and rebate-only alternatives as well as high-friction winners.
    for cost in [-1,0,1,3,5]:
        f=all_results[all_results.active_days>=80].sort_values(f'bps_day_c{cost}',ascending=False)
        chosen.append(f.drop_duplicates(['candidate_id','offset_bps']).head(12))
        chosen.append(f[f.hold<=15].drop_duplicates(['candidate_id','offset_bps']).head(8))
    selected=pd.concat(chosen).drop_duplicates('trial').sort_values('candidate_id')
    one=selected.sort_values('bps_day_c1',ascending=False).drop_duplicates(['candidate_id','offset_bps','hold','lo','hi']).copy()
    one['slots']=1
    selected=pd.concat([selected,one],ignore_index=True)
    selected.to_parquet(DEST/'confirmation_parents.parquet',index=False)
    # Previous exact five-minute observation; no previous-day carry or assumed adjacency.
    index=np.full((len(days),len(securities),79),-1,np.int32)
    index[day,sec,np.minimum(minute//5,78)]=np.arange(len(t))
    previous=index[day,sec,np.maximum(minute//5-1,0)];previous[minute<10]=-1
    rows=[];saved=[];number=0
    for cid,parents in selected.groupby('candidate_id',sort=False):
        spec=definitions.loc[cid];direction=int(spec.direction)
        a=decode_packed_bins(reader.read_columns('bins',[spec.feature_a],0,reader.rows)[:,0],10)
        b=decode_packed_bins(reader.read_columns('bins',[spec.feature_b],0,reader.rows)[:,0],10) if spec.feature_b else None
        state=a if b is None else np.where((a>=0)&(b>=0),a*10+b,-1)
        active=state==spec.cell;prior_active=(previous>=0)&active[np.maximum(previous,0)]
        ix=np.flatnonzero(active&(minute>=5)&(t+12<=closes[day]-5))
        d=day[ix];s=sec[ix];m=minute[ix];anchor=price[d,s,m+1]
        recent=price[d,s,m]/price[d,s,np.maximum(m-5,0)]-1
        latest=price[d,s,m]/price[d,s,np.maximum(m-1,0)]-1
        prev5=previous[ix]
        conditions={'all':np.ones(len(ix),bool),'fresh_cross':~prior_active[ix],
            'persistent':prior_active[ix],'recent_with_trade':direction*recent>0,
            'recent_against_trade':direction*recent<0,
            'turn_into_trade':(direction*recent<0)&(direction*latest>0),
            'vol_top20':ranks[ix,7]>=.8,'vol_bottom50':ranks[ix,7]<.5,
            'accel_top10':ranks[ix,4]>=.9,'accel_bottom10':ranks[ix,4]<.1,
            'fresh_and_turn':~prior_active[ix]&(direction*recent<0)&(direction*latest>0),
            'fresh_highvol':~prior_active[ix]&(ranks[ix,7]>=.8)}
        for r in parents.itertuples():
            limit=anchor*(1-direction*r.offset_bps/10000)
            if r.offset_bps==0:filled=np.isfinite(anchor);delay=np.zeros(len(ix),int);ep=anchor
            else:
                path=price[d[:,None],s[:,None],m[:,None]+1+np.arange(1,6)]
                touch=(path<=limit[:,None]) if direction==1 else (path>=limit[:,None]);touch&=np.isfinite(path)
                filled=touch.any(1);delay=touch.argmax(1)+1;ep=limit
            ex=t[ix]+1+delay+r.hold;xp=price[d,s,np.clip(m+1+delay+r.hold,0,389)]
            valid=filled&np.isfinite(xp)&(ex<=closes[d]-5)
            pnl=direction*(xp/ep-1)*10000;release=np.where(valid,ex,t[ix]+6)
            time_mask=(m>=r.lo)&(m<r.hi)
            for name,mask in conditions.items():
                loc=np.flatnonzero(mask&time_mask)
                if valid[loc].sum()<100:continue
                # Stronger recent displacement is causal and deterministic, not selected using future returns.
                priority=np.abs(recent[loc]) if r.slots==1 else None
                chosen,attempts=allocate(t[ix[loc]]+1,release[loc],s[loc],valid[loc],int(r.slots),priority=priority)
                picked=loc[chosen]
                if len(picked)<75:continue
                number+=1;gross=pnl[picked];days_taken=d[picked]
                row={'confirmation_id':number,'parent_trial':r.trial,'candidate_id':cid,'condition':name,'offset_bps':r.offset_bps,
                    'hold':r.hold,'lo':r.lo,'hi':r.hi,'slots':r.slots,'trades':len(picked),'attempts':attempts,
                    'trades_day':len(picked)/251,'active_days':len(np.unique(days_taken)),'gross_bps':float(gross.mean())}
                for c in COSTS:row.update({f'{k}_c{c}':v for k,v in metrics((gross-2*c)/r.slots,days_taken).items()})
                first=days_taken<126;row['first_half_gross']=float(gross[first].mean()) if first.any() else None
                row['second_half_gross']=float(gross[~first].mean()) if (~first).any() else None
                daily=np.bincount(days_taken,weights=(gross-2)/r.slots,minlength=251)
                row['bps_day_without_best5_c1']=float((daily.sum()-np.sort(daily)[-5:].sum())/251)
                rows.append(row)
                if row['bps_day_c1']>3 or row['bps_day_c0']>7:
                    saved.append(pd.DataFrame({'confirmation_id':number,'observation_id':ix[picked],'gross_bps':gross,
                        'day':days_taken,'security_code':s[picked],'entry_minute':t[ix[picked]]+1+delay[picked],'exit_minute':ex[picked]}))
        print('CONFIRMATION',cid,number,flush=True)
    pd.DataFrame(rows).to_parquet(DEST/'confirmation_results.parquet',index=False)
    if saved:pd.concat(saved).to_parquet(DEST/'confirmation_trades.parquet',index=False)
    print(pd.DataFrame(rows).sort_values('bps_day_c1',ascending=False)[['confirmation_id','candidate_id','condition','offset_bps','hold','trades_day','gross_bps','bps_day_c1','sharpe_c1']].head(15).to_string(index=False),flush=True)

if __name__=='__main__':main()
