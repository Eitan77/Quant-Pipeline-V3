from __future__ import annotations
from pathlib import Path
import duckdb, pyarrow as pa
from quant_pipeline.governance import PeriodGuard

class ReadOnlyDuckDBProvider:
    def __init__(self,catalog:Path,guard:PeriodGuard): self.catalog=Path(catalog); self.guard=guard
    def load_decision_rows(self,start,end,limit:int|None=None)->pa.Table:
        start,end=self.guard.authorize_discovery_range(start,end)
        lim=f" LIMIT {int(limit)}" if limit else ""
        sql=f"""SELECT row_number() over(order by try_cast(timestamp as TIMESTAMPTZ),symbol)-1 security_id,
          symbol, cast(date as date) session_date, try_cast(timestamp as TIMESTAMPTZ)+INTERVAL 1 MINUTE decision_ts_utc,
          'intraday_1m' grid_id, true universe_eligible
          FROM bars_1m WHERE cast(date as date) BETWEEN ? AND ? AND lower(feed)='sip' AND lower(adjustment)='raw'
          ORDER BY decision_ts_utc,symbol{lim}"""
        con=duckdb.connect(str(self.catalog),read_only=True)
        try: out=con.execute(sql,[start,end]).fetch_arrow_table()
        finally: con.close()
        self.guard.assert_rows_discovery_only(out["session_date"].to_pylist())
        return out

