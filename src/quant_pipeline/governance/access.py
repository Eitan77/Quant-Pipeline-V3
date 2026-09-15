from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from quant_pipeline.errors import SealedDataViolation

@dataclass(frozen=True)
class PeriodGuard:
    discovery_start:pd.Timestamp; discovery_end:pd.Timestamp
    replication_start:pd.Timestamp; replication_end:pd.Timestamp; final_holdout_start:pd.Timestamp
    @classmethod
    def from_config(cls,c):
        p=c["periods"]
        return cls(pd.Timestamp(p["discovery"]["start"]),pd.Timestamp(p["discovery"]["end"]),pd.Timestamp(p["replication"]["start"]),pd.Timestamp(p["replication"]["end"]),pd.Timestamp(p["final_holdout"]["start"]))
    def authorize_discovery_range(self,start,end):
        a,b=pd.Timestamp(start),pd.Timestamp(end)
        if a < self.discovery_start or b > self.discovery_end: raise SealedDataViolation(f"Discovery query {a.date()}..{b.date()} crosses sealed boundary")
        return a.date(),b.date()
    def assert_rows_discovery_only(self,dates):
        x=pd.to_datetime(dates)
        if len(x) and ((x<self.discovery_start)|(x>self.discovery_end)).any(): raise SealedDataViolation("Materialized rows contain non-discovery dates")

