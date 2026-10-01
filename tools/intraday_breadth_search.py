"""Family-balanced broad screen; no expansion of the previous winning family."""
import json
import numpy as np
import pandas as pd
from intraday_strategy_search import ROOT,OUT,COSTS,obs_arrays
from intraday_entry_search import allocate
from intraday_exit_search import statistics
from quant_pipeline.production.evidence_store import EvidenceReader
from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins

DEST=OUT/'breadth_extension';DEST.mkdir(exist_ok=True)

def main():
    f=pd.read_parquet(OUT/'conditional_cells.parquet')
    f=f[(f.feature_b=='')&~f.feature_a.str.contains('ema_distance')].copy()
    f['horizon']=f.target_id.str.extract(r'target_(\d+)m')[0].fillna('390').astype(int)
    f['horizon_group']=np.where(f.horizon<=15,'fast',np.where(f.horizon<=60,'medium','long'))
    f['score']=(f.raw_bps.abs()-2)*np.minimum(f.n/251,40)
    f=f[f.n>=500]
    selected=f.sort_values('score',ascending=False).groupby(['feature_a','time_group','horizon_group','direction'],sort=False).head(1)
    selected=selected.reset_index(drop=True);selected['rule_id']=np.arange(len(selected))
    selected.to_parquet(DEST/'rules.parquet',index=False)
    registry=pd.read_parquet(ROOT/'feature_registry.parquet').set_index('feature_id')
    obs,t,day,days,sec,securities,closes=obs_arrays();del obs
    axes=json.loads((OUT/'price_axes.json').read_text());opens=np.array(axes['open_minutes']);minute=t-opens[day]
    prices=np.load(OUT/'opens.npy',mmap_mode='r');reader=EvidenceReader(ROOT,'evidence/reader.json','intraday_5m')
    groups=reader.read_groups('time_bucket',0,reader.rows)
    results=[];ledgers=[];coverage=[]
    for count,(feature,rules) in enumerate(selected.groupby('feature_a',sort=False)):
        codes=decode_packed_bins(reader.read_columns('bins',[feature],0,reader.rows)[:,0],10)
        family=registry.loc[feature,'family'];valid_rules=0
        for r in rules.itertuples():
            ix=np.flatnonzero((codes==r.cell)&(groups==r.time_group)&(minute>=5))
            planned=closes[day[ix]]-5 if r.horizon==390 else t[ix]+1+r.horizon
            legal=(planned<=closes[day[ix]]-5)&(planned>t[ix]+1)
            ix=ix[legal];planned=planned[legal]
            if len(ix)<100:continue
            d=day[ix];s=sec[ix];m=minute[ix]
            ep=prices[d,s,np.minimum(m+1,389)]
            good=np.isfinite(ep);ix=ix[good];planned=planned[good];d=d[good];s=s[good];m=m[good];ep=ep[good]
            # Missing scheduled exit: first subsequent minute open, at most 3 minutes, respecting close buffer.
            xp=np.full(len(ix),np.nan);actual=planned.copy()
            for extra in range(4):
                sample=prices[d,s,np.clip(planned+extra-opens[d],0,389)]
                use=~np.isfinite(xp)&np.isfinite(sample)&(planned+extra<=closes[d]-5)
                xp[use]=sample[use];actual[use]=planned[use]+extra
            recent=prices[d,s,m]/prices[d,s,np.maximum(m-5,0)]-1
            for slots in [1,10]:
                taken,attempts=allocate(t[ix]+1,actual,s,np.ones(len(ix),bool),slots,
                    priority=np.nan_to_num(np.abs(recent),nan=-1) if slots==1 else None)
                missing=int((~np.isfinite(xp[taken])).sum())
                if len(taken)<75:continue
                pnl=r.direction*(xp[taken]/ep[taken]-1)*10000
                # Screening rows with missing exits remain explicitly incomplete, never zero-filled.
                row={'rule_id':r.rule_id,'feature':feature,'family':family,'side':r.direction,'cell':r.cell,
                     'time_group':r.time_group,'horizon':r.horizon,'slots':slots,'trades':len(taken),
                     'trades_day':len(taken)/251,'active_days':len(np.unique(d[taken])),'missing_exits':missing}
                if not missing:
                    valid_rules+=1;row['gross_bps']=float(pnl.mean())
                    if slots==1:row.update(statistics(pnl,d[taken]))
                    else:
                        from intraday_strategy_search import metrics
                        for c in COSTS:
                            metrics_c=metrics((pnl-2*c)/slots,d[taken])
                            row.update({f'return_c{c}':metrics_c['return_pct'],f'bps_day_c{c}':metrics_c['bps_day'],
                              f'sharpe_c{c}':metrics_c['sharpe'],f'dd_c{c}':metrics_c['max_dd_pct']})
                    first=d[taken]<126;row['first_half_gross']=float(pnl[first].mean()) if first.any() else None
                    row['second_half_gross']=float(pnl[~first].mean()) if (~first).any() else None
                    if row['return_c1']>20 or row['return_c0']>40:
                        ledgers.append(pd.DataFrame({'rule_id':r.rule_id,'slots':slots,'observation_id':ix[taken],
                            'day':d[taken],'security_code':s[taken],'entry_minute':t[ix[taken]]+1,'exit_minute':actual[taken],
                            'gross_bps':pnl,'side':r.direction}))
                results.append(row)
        coverage.append({'feature':feature,'family':family,'selected_rules':len(rules),'complete_replays':valid_rules})
        if count%15==0:print('BREADTH',count+1,selected.feature_a.nunique(),'replays',len(results),flush=True)
    pd.DataFrame(results).to_parquet(DEST/'results.parquet',index=False)
    pd.DataFrame(coverage).to_parquet(DEST/'coverage.parquet',index=False)
    if ledgers:pd.concat(ledgers).to_parquet(DEST/'leader_trades.parquet',index=False)
    print(pd.DataFrame(results).sort_values('return_c1',ascending=False)[['rule_id','feature','side','time_group','horizon','slots','trades_day','return_c1','sharpe_c1','dd_c1']].head(15).to_string(index=False),flush=True)

if __name__=='__main__':main()
