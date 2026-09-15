from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from pathlib import Path
import pyarrow as pa,pyarrow.parquet as pq
@dataclass(frozen=True,slots=True)
class TrialRecord:
    trial_id:str;trial_family_id:str;run_id:str;trial_type:str;status:str;feature_a_id:str|None=None;feature_b_id:str|None=None;target_id:str|None=None;resolution:int|None=None;variant_definition:str|None=None;artifact_hash:str|None=None;reason:str|None=None;created_at_utc:str=""
class TrialLedger:
    def __init__(self):self.rows={}
    def put(self,row):
        if not row.created_at_utc:row=TrialRecord(**{**asdict(row),"created_at_utc":datetime.now(timezone.utc).isoformat()})
        if row.trial_id in self.rows and self.rows[row.trial_id]!=row:raise ValueError(f"Conflicting trial record: {row.trial_id}")
        self.rows[row.trial_id]=row
    def reconcile(self,expected):
        known=set(self.rows); missing=set(expected)-known
        if missing:raise ValueError(f"Unexplained trial gap: {len(missing)}")
        return {s:sum(x.status==s for x in self.rows.values()) for s in ("executed","reused","structurally_excluded","unavailable","failed")}
    def write(self,path:Path):
        tmp=path.with_suffix(".parquet.partial");pq.write_table(pa.Table.from_pylist([asdict(x) for x in self.rows.values()]),tmp,compression="zstd");tmp.replace(path)

