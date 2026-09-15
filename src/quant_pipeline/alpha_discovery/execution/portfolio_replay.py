"""Fixed-base cash-capped long-only event replay with a reconciled trade ledger."""
from __future__ import annotations
import heapq
import numpy as np
import pandas as pd


def replay_portfolio(windows: pd.DataFrame, *, max_positions=20, cost_bps=5., slippage_bps=2.):
    required={"security_id","entry_ts","exit_ts","entry_price","exit_price","position"}
    if required-set(windows): raise ValueError(f"Missing fields: {required-set(windows)}")
    if max_positions<1 or cost_bps<0 or slippage_bps<0: raise ValueError("Invalid execution configuration")
    frame=windows.copy(); frame["source_row"]=np.arange(len(frame))
    for c in ('entry_ts','exit_ts'): frame[c]=pd.to_datetime(frame[c],utc=True)
    if frame[['entry_ts','exit_ts']].isna().any().any(): raise ValueError("Missing timestamps")
    frame=frame.sort_values(['entry_ts','security_id','source_row'],kind='stable')
    active={}; heap=[]; ledger=[]; rejected=[]; committed=0.; sequence=0
    allocation=1./max_positions; fee=cost_bps/10000; slip=slippage_bps/10000
    for row in frame.itertuples():
        while heap and heap[0][0]<=row.entry_ts:
            _,_,security,notional=heapq.heappop(heap); committed-=notional; active.pop(security,None)
        reason=None
        if row.position<=0: reason='inactive' if row.position==0 else 'direct_short_not_executable'
        elif row.exit_ts<=row.entry_ts: reason='invalid_interval'
        elif not np.isfinite([row.entry_price,row.exit_price]).all() or min(row.entry_price,row.exit_price)<=0: reason='invalid_price'
        elif row.security_id in active: reason='already_open'
        elif committed+allocation>1+1e-12: reason='capital_cap'
        if reason:
            rejected.append({'source_row':row.source_row,'reason':reason}); continue
        entry=row.entry_price*(1+slip); exit=row.exit_price*(1-slip)
        # Reserve entry fee within original-base allocation. Profits never increase the cap.
        principal=allocation/(1+fee); shares=principal/entry
        pnl=shares*exit*(1-fee)-allocation
        ledger.append({'source_row':row.source_row,'security_id':row.security_id,'entry_ts':row.entry_ts,'exit_ts':row.exit_ts,
                       'entry_price':entry,'exit_price':exit,'allocation':allocation,'shares':shares,'net_pnl':pnl})
        sequence+=1; heapq.heappush(heap,(row.exit_ts,sequence,row.security_id,allocation)); active[row.security_id]=True; committed+=allocation
    trades=pd.DataFrame(ledger,columns=['source_row','security_id','entry_ts','exit_ts','entry_price','exit_price','allocation','shares','net_pnl'])
    reject=pd.DataFrame(rejected,columns=['source_row','reason'])
    if trades.empty: return trades,reject,{'net_additive_return':0.,'completed_trades':0,'execution_status':'NO_TRADES'}
    realized=trades.groupby('exit_ts',sort=True).net_pnl.sum().cumsum(); equity=1+realized
    peak=equity.cummax().clip(lower=1.); dd=equity/peak-1
    months=trades.assign(month=pd.to_datetime(trades.exit_ts,utc=True).dt.strftime('%Y-%m')).groupby('month').net_pnl.sum()
    return trades,reject,{'net_additive_return':float(trades.net_pnl.sum()),'completed_trades':len(trades),
        'rejected_events':len(reject),'realized_only_max_drawdown':float(-dd.min()),
        'monthly_realized_pnl':months.to_dict(),'execution_status':'BAR_DIAGNOSTIC',
        'requires_quote_and_mark_to_market_validation':True,'fixed_capital':1.,'max_positions':max_positions,
        'cost_bps_per_side':cost_bps,'slippage_bps_per_side':slippage_bps}
