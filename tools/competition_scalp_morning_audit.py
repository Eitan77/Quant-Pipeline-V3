"""Full selected-ledger risk, neighbor, concentration and uncertainty checks."""
import json
import numpy as np,pandas as pd
from competition_scalp import OUT,metrics

QOUT=OUT/'quote_morning_reversion_1.5_5m__etfs'

def run():
    a=json.loads((OUT/'axes.json').read_text());days=a['days'];cp=np.load(OUT/'close.npy',mmap_mode='r')
    q=pd.read_parquet(QOUT/'details.parquet');s=pd.read_parquet(QOUT/'signals.parquet');records=[];neighbors=[]
    full=pd.read_parquet(OUT/'bar_trades.parquet');full=full[full.candidate_id=='reversion_1.5_5m__etfs']
    for end in [75,90,105,120]:
        g=full[full.signal_minute<end];rr=g.side.to_numpy()*(cp[g.day,g.symbol_code,g.signal_minute+5]-cp[g.day,g.symbol_code,g.signal_minute])/cp[g.day,g.symbol_code,g.signal_minute]
        neighbors.append({'morning_end_minute':end,**metrics(rr,g.day.to_numpy(),days,3)})
    pd.DataFrame(neighbors).to_parquet(QOUT/'time_boundary_neighbors.parquet',index=False)
    for bps in [-1,0,1]:
        base=q[(q.wait_seconds==15)&(q.bps==bps)].merge(s[['trade_id','symbol_code','signal_minute','entry_price']],on='trade_id',validate='one_to_one')
        for direction in [0,1,-1]:
            f=base if direction==0 else base[base.side==direction]
            for fee in [.5,1.]:
                rr=f['return'].to_numpy()-f.entry_attainable.to_numpy()*fee/10000
                st=metrics(rr,f.day.to_numpy(),days,3)
                daily=np.bincount(f.day,weights=rr/3,minlength=len(days));blocks=np.pad(daily,(0,(-len(daily))%5)).reshape(-1,5).sum(axis=1)
                rng=np.random.default_rng(20260930);boot=blocks[rng.integers(len(blocks),size=(2000,len(blocks)))].sum(axis=1)*100
                realized=np.zeros((len(days),390));marks=np.zeros_like(realized)
                for row,ret in zip(f.itertuples(),rr):
                    if not row.entry_attainable:continue
                    entry=row.entry_price*(1+row.side*bps/10000);start=row.signal_minute+1;stop=start+5
                    marks[row.day,start:stop]+=row.side*(cp[row.day,row.symbol_code,start:stop]-entry)/entry/3
                    realized[row.day,stop:]+=ret/3
                equity=(np.r_[0,np.cumsum(daily)[:-1]][:,None]+realized+marks).ravel()
                dd=np.maximum.accumulate(np.r_[0.,equity])[1:]-equity
                positive_months=pd.Series(daily,index=pd.to_datetime(days)).groupby(lambda x:x.strftime('%Y-%m')).sum()
                st.update({'bps':bps,'direction':direction,'fee_bps_round_trip':fee,'filled_entries':int(f.entry_attainable.sum()),
                    'limit_exits':int(f.exit_attainable.sum()),'forced_exits':int(f.status.eq('forced_exit').sum()),
                    'missing_entry_windows':int(f.status.eq('missing_entry_window').sum()),'missing_exits':int(f.status.eq('missing_exit').sum()),
                    'mean_filled_bps':float(rr[f.entry_attainable].mean()*10000) if f.entry_attainable.any() else np.nan,
                    'without_best_month_pct':float((daily.sum()-positive_months.max())*100),
                    'minute_close_proxy_max_dd_pct':float(dd.max()*100),
                    'conditional_5session_bootstrap_95pct_low':float(np.percentile(boot,2.5)),
                    'conditional_5session_bootstrap_95pct_high':float(np.percentile(boot,97.5))})
                records.append(st)
    result=pd.DataFrame(records);result.to_parquet(QOUT/'full_selected_audit.parquet',index=False)
    print(result[['bps','direction','fee_bps_round_trip','filled_entries','mean_filled_bps','return_pct','positive_months','positive_week_fraction','without_best5_days_pct','minute_close_proxy_max_dd_pct','conditional_5session_bootstrap_95pct_low']].to_string(index=False))
    # A sampled quote test is not annualized; this file covers only the fully quoted selected ledger.
    (QOUT/'audit_scope.json').write_text(json.dumps({'coverage':'Entire selected morning ledger, all 12 discovery months.',
        'out_of_sample_accessed':False,'gross_exposure_limit':'three equal fixed-base slots, two ETF symbols, no leverage',
        'minute_drawdown':'Raw one-minute-close marks while holding, realized quote outcomes thereafter; not tick drawdown.',
        'uncertainty':'5-session block resampling, conditional on the discovered rule; does not adjust for selection.',
        'entry_selection':'Signal conditions known at decision; spread/queue observed before activation with extra 1s latency.',
        'execution':'Executable-side NBBO attainability with positive sizes; missed entry zero, failed limit exit forced.',
        'capacity':'Displayed-size scaling and live fills remain unvalidated.'},indent=2))

if __name__=='__main__':run()
