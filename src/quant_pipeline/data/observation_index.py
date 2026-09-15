from __future__ import annotations
import numpy as np, pyarrow as pa
from quant_pipeline.errors import CausalityViolation

def build_observation_index(rows: pa.Table) -> pa.Table:
    required={"security_id","symbol","session_date","decision_ts_utc","grid_id","universe_eligible"}
    missing=required-set(rows.column_names)
    if missing: raise ValueError(f"Observation rows missing {sorted(missing)}")
    df=rows.to_pandas().sort_values(["decision_ts_utc","security_id"],kind="stable").reset_index(drop=True)
    df["obs_id"]=np.arange(len(df),dtype=np.int64)
    df["session_id"]=df["session_date"].rank(method="dense").astype("int32")-1
    df["security_session_seq"]=df.groupby(["security_id","session_id","grid_id"],sort=False).cumcount().astype("int32")
    if "entry_reference_ts_utc" not in df: df["entry_reference_ts_utc"]=df["decision_ts_utc"]
    if (df["entry_reference_ts_utc"] < df["decision_ts_utc"]).any(): raise CausalityViolation("Entry reference precedes decision")
    cols=["obs_id","security_id","symbol","session_id","security_session_seq","session_date","decision_ts_utc","grid_id","entry_reference_ts_utc","universe_eligible"]
    return pa.Table.from_pandas(df[cols],preserve_index=False)

