"""Inspect economically defined selective slices using already pulled quotes."""
import json
import numpy as np,pandas as pd
from competition_scalp import OUT,metrics

def features(f):
    cp=np.load(OUT/'close.npy',mmap_mode='r');vol=np.load(OUT/'volume.npy',mmap_mode='r');rows=[]
    for r in f.itertuples():
        m=r.signal_minute;prices=cp[r.day,r.symbol_code];returns=np.diff(np.log(prices[m-31:m]))
        sigma=np.std(returns,ddof=1);shock=np.log(prices[m]/prices[m-1])/sigma
        trend=r.side*np.log(prices[m-1]/prices[m-16])/(sigma*np.sqrt(15))
        vv=vol[r.day,r.symbol_code,:m+1];ref=np.nansum(prices[:m+1]*vv)/np.nansum(vv)
        distance=-r.side*np.log(prices[m]/ref)/(sigma*np.sqrt(30))
        rows.append((abs(shock),sigma*10000,trend,distance,m))
    return pd.DataFrame(rows,columns=['shock','sigma_bps','aligned_trend','stretch','minute'],index=f.index)

def run():
    a=json.loads((OUT/'axes.json').read_text());b=pd.read_parquet(OUT/'bar_trades.parquet');rows=[]
    for rule,folder in [('reversion_1.5_5m__etfs','quote_probe'),('reversion_2_10m__AMD','quote_probe_reversion_2_10m__AMD')]:
        full=b[b.candidate_id==rule].reset_index(drop=True);ff=features(full)
        s=pd.read_parquet(OUT/folder/'signals.parquet');sf=features(s);sf['trade_id']=s.trade_id
        q=pd.read_parquet(OUT/folder/'details.parquet').merge(sf,on='trade_id',validate='many_to_one')
        cuts={key:float(ff.shock.quantile(qt)) for key,qt in [('tail80',.8),('tail90',.9),('tail95',.95)]}
        definitions={'all':lambda x:np.ones(len(x),bool),'morning':lambda x:x.minute<90,
            'aligned_trend':lambda x:x.aligned_trend>=.5,'aligned_trend_neighbor':lambda x:x.aligned_trend>=1,
            'stretch':lambda x:x.stretch>=1,'stretch_neighbor':lambda x:x.stretch>=1.5}
        for key,cut in cuts.items():definitions[key]=lambda x,cut=cut:x.shock>=cut
        definitions['tail80_morning']=lambda x:(x.shock>=cuts['tail80'])&(x.minute<90)
        definitions['tail90_morning']=lambda x:(x.shock>=cuts['tail90'])&(x.minute<90)
        for key,definition in definitions.items():
            annual=int(np.count_nonzero(definition(ff)));subset=q[definition(q)]
            for spread_cap in [None,1.,1.5,2.]:
                g=subset if spread_cap is None else subset[subset.spread_bps<=spread_cap]
                for (wait,bps),part in g.groupby(['wait_seconds','bps']):
                    for fee in [.5,1.]:
                        rr=part['return'].to_numpy()-part.entry_attainable.to_numpy()*fee/10000
                        st=metrics(rr,part.day.to_numpy(),a['days'],3)
                        rows.append({'rule':rule,'selection':key,'spread_cap':spread_cap,'annual_bar_opportunities_before_quote_filter':annual,
                            'wait_seconds':wait,'bps':bps,'fee_bps_round_trip':fee,'attempts':len(part),'filled_entries':int(part.entry_attainable.sum()),
                            'mean_filled_bps':float(rr[part.entry_attainable].mean()*10000) if part.entry_attainable.any() else np.nan,**st})
    result=pd.DataFrame(rows);result.to_parquet(OUT/'selective/quote_selection.parquet',index=False)
    view=result[(result.fee_bps_round_trip==.5)&(result.filled_entries>=60)&(result.wait_seconds==59)&(result.bps.isin([-1,0]))]
    print(view.sort_values(['positive_months','without_best5_days_pct'],ascending=False)[['rule','selection','spread_cap','annual_bar_opportunities_before_quote_filter','attempts','filled_entries','bps','mean_filled_bps','positive_months','without_best5_days_pct']].head(15).to_string(index=False))

if __name__=='__main__':run()
