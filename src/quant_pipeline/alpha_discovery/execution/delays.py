from __future__ import annotations
import numpy as np
import pandas as pd


def measured_entry_delays(windows, connection, table, cutoff, delays, batch_size=2000):
    """Raw-price delayed entries, fixed original exit; bounded source-query reads.

    Delay is additional latency after the original scheduled entry. Missing or
    post-exit entries remain missing; no hold-period targets are substituted.
    """
    required={"security_id","entry_ts","exit_ts","exit_price","position"}
    if required-set(windows): raise ValueError("Missing execution windows")
    if not table.replace('_','').isalnum(): raise ValueError("Unsafe source table")
    cutoff=pd.Timestamp(cutoff).date()
    if (pd.to_datetime(windows.exit_ts,utc=True).dt.tz_convert('America/New_York').dt.date>cutoff).any():
        raise ValueError("Execution windows exceed authorized cutoff")
    for delay in delays:
        if not isinstance(delay,(int,float)) or delay<0: raise ValueError("Delay must be nonnegative minutes")
    base=windows[["security_id","entry_ts","exit_ts","exit_price","position"]].copy()
    base["row_id"]=np.arange(len(base),dtype=np.int64)
    delay_frame=pd.DataFrame({"delay_minutes":np.asarray(delays,dtype=float)})
    connection.register("delay_windows",base); connection.register("delay_values",delay_frame)
    rows=connection.execute(f"""SELECT w.row_id,d.delay_minutes,
               arg_min(b.open,b.bar_start_ts_utc) AS entry_price
        FROM delay_windows w CROSS JOIN delay_values d
        JOIN {table} b ON b.security_id=w.security_id
          AND b.bar_start_ts_utc>=w.entry_ts+d.delay_minutes*INTERVAL '1 minute'
          AND b.bar_start_ts_utc<w.entry_ts+(d.delay_minutes+1)*INTERVAL '1 minute'
          AND b.bar_start_ts_utc<w.exit_ts
        WHERE b.session_date<=DATE '{cutoff}' AND b.open>0
        GROUP BY w.row_id,d.delay_minutes""").fetchdf() if len(base) else pd.DataFrame(columns=["row_id","delay_minutes","entry_price"])
    connection.unregister("delay_windows"); connection.unregister("delay_values")
    result={}; counts=[]; positions=base.position.to_numpy(float); exits=base.exit_price.to_numpy(float)
    for delay in delays:
        values=np.full(len(base),np.nan); selected=rows[rows.delay_minutes.eq(float(delay))]
        ids=selected.row_id.to_numpy(int)
        values[ids]=positions[ids]*(exits[ids]/selected.entry_price.to_numpy(float)-1)
        result[delay]=values
        counts.append({"additional_entry_delay_minutes":delay,"requested":len(values),"filled":int(np.isfinite(values).sum()),
                       "rejected":int((~np.isfinite(values)).sum()),"exit_policy":"original_exit"})
    return result,pd.DataFrame(counts)
