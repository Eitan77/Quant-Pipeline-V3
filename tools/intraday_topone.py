import json
import numpy as np
import pandas as pd
from intraday_strategy_search import OUT,COSTS,obs_arrays,metrics
from intraday_entry_search import allocate,DEST

def main():
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);m=t-opens[day]
    prices=np.load(OUT/'opens.npy',mmap_mode='r');ranks=np.load(OUT/'fine_ranks.npy',mmap_mode='r')
    defs=pd.read_parquet(OUT/'refinement_results.parquet').set_index('refine_id')
    rows=[];trades=[];n=0
    for rid in ['R00530','R00965','R00567','R00621']:
        r=defs.loc[rid]
        mask=(ranks[:,3]<1-r.a)&(ranks[:,4]>=1-r.b) if r.family=='breakdown_accel_short' else (ranks[:,4]>=r.a)&(ranks[:,5]<r.b)
        ix=np.flatnonzero(mask&(m>=r.lo)&(m<r.hi)&(t+int(r.horizon)+7<=closes[day]-5))
        dd=day[ix];ss=sec[ix];mm=m[ix];anchor=prices[dd,ss,mm+1]
        recent=prices[dd,ss,mm]/prices[dd,ss,np.maximum(mm-5,0)]-1
        latest=prices[dd,ss,mm]/prices[dd,ss,np.maximum(mm-1,0)]-1
        priority={'strongest_acceleration':ranks[ix,4], 'largest_recent_move':np.abs(recent),
                  'largest_breakdown':1-ranks[ix,3],'highest_volatility':ranks[ix,7]}
        for offset in [0,2,5,10,20]:
            ep=anchor*(1+offset/10000)
            if offset==0:filled=np.isfinite(anchor);delay=np.zeros(len(ix),int)
            else:
                path=prices[dd[:,None],ss[:,None],mm[:,None]+1+np.arange(1,6)]
                touch=(path>=ep[:,None])&np.isfinite(path);filled=touch.any(1);delay=touch.argmax(1)+1
            ex=t[ix]+1+delay+int(r.horizon);xp=prices[dd,ss,np.clip(ex-opens[dd],0,389)]
            good=filled&np.isfinite(xp);gross=(1-xp/ep)*10000;release=np.where(good,ex,t[ix]+6)
            for confirm,keep in [('none',np.ones(len(ix),bool)),('downturn',latest<0),('rebound_then_downturn',(recent>0)&(latest<0))]:
                loc=np.flatnonzero(keep)
                for ranking,score in priority.items():
                    chosen,attempts=allocate(t[ix[loc]]+1,release[loc],ss[loc],good[loc],1,priority=np.nan_to_num(score[loc],nan=-1))
                    picked=loc[chosen]
                    if len(picked)<50:continue
                    n+=1;pnl=gross[picked];d=dd[picked]
                    row={'id':n,'rule':rid,'offset':offset,'confirmation':confirm,'ranking':ranking,'trades':len(picked),
                         'trades_day':len(picked)/251,'active_days':len(np.unique(d)),'gross_bps':float(pnl.mean()),'attempts':attempts}
                    for c in COSTS:row.update({f'{k}_c{c}':v for k,v in metrics(pnl-2*c,d).items()})
                    row['first_half_gross']=float(pnl[d<126].mean()) if (d<126).any() else None
                    row['second_half_gross']=float(pnl[d>=126].mean()) if (d>=126).any() else None
                    rows.append(row)
                    trades.append(pd.DataFrame({'id':n,'observation_id':ix[picked],'gross_bps':pnl,'day':d,'security_code':ss[picked],
                       'entry_minute':t[ix[picked]]+1+delay[picked],'exit_minute':ex[picked]}))
        print('TOP ONE',rid,n,flush=True)
    pd.DataFrame(rows).to_parquet(DEST/'topone_results.parquet',index=False)
    pd.concat(trades).to_parquet(DEST/'topone_trades.parquet',index=False)
    print(pd.DataFrame(rows).sort_values('bps_day_c1',ascending=False)[['id','rule','offset','confirmation','ranking','trades_day','return_pct_c1','sharpe_c1','max_dd_pct_c1']].head(10).to_string(index=False),flush=True)

if __name__=='__main__':main()
