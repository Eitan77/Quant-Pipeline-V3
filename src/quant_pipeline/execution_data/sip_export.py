from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq
def write_sip_signal_export(*,candidate,rows,output_path:Path):
    required={"candidate_id","security_id","symbol","signal_ts_utc","direction","reference_exit_ts_utc","state_definition","resolution"}
    for row in rows:
        if required-row.keys(): raise ValueError(f"SIP export row missing {sorted(required-row.keys())}")
        if row["candidate_id"]!=candidate.candidate_id: raise ValueError("Mixed candidate IDs")
    tmp=output_path.with_suffix(".parquet.partial"); pq.write_table(pa.Table.from_pylist(rows),tmp,compression="zstd"); tmp.replace(output_path); return output_path

