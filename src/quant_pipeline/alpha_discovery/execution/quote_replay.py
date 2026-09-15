from __future__ import annotations
import numpy as np
import pandas as pd


def require_quote_data(columns: set[str]) -> None:
    required = {"bid", "ask", "bid_size", "ask_size", "quote_ts"}
    missing = required - columns
    if missing: raise ValueError(f"Quote replay unavailable; missing columns: {sorted(missing)}")


def executable_quote_prices(requests, quotes, max_wait_ms=1000, participation=.05):
    """Marketable fills at the first valid quote after order arrival; no passive inference."""
    require_quote_data(set(quotes))
    if not 0<participation<=1 or max_wait_ms<0: raise ValueError("Invalid execution limits")
    output=[]
    grouped={key:g.sort_values('quote_ts') for key,g in quotes.groupby('security_id',sort=False)}
    for row in requests.itertuples():
        if row.side not in ('buy','sell') or row.quantity<=0: raise ValueError("Invalid order")
        g=grouped.get(row.security_id); found=None
        if g is not None:
            times=pd.to_datetime(g.quote_ts,utc=True); start=pd.Timestamp(row.request_ts)
            selected=g[(times>=start)&(times<=start+pd.Timedelta(milliseconds=max_wait_ms))]
            selected=selected[(selected.bid>0)&(selected.ask>=selected.bid)&(selected.bid_size>0)&(selected.ask_size>0)]
            if len(selected): found=selected.iloc[0]
        if found is None: output.append({'price':np.nan,'filled_quantity':0.,'status':'missing_quote'}); continue
        side='ask' if row.side=='buy' else 'bid'; capacity=float(found[side+'_size'])*participation
        filled=min(float(row.quantity),capacity)
        output.append({'price':float(found[side]),'filled_quantity':filled,'status':'filled' if filled==row.quantity else 'partial', 'quote_ts':found.quote_ts})
    return pd.DataFrame(output,index=requests.index)
