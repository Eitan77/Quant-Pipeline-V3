from __future__ import annotations
import json,os
from pathlib import Path
import duckdb
from quant_pipeline.hashing import content_hash

def build_source_bridge(*,repo_root:Path,machine:dict,start:str="2024-04-01",end:str="2026-04-30")->Path:
    """Build a V3-owned catalog whose views read only the external candle lake."""
    repo_root=Path(repo_root); tag=f"{start}_{end}".replace("-",""); out=Path(machine["cache_root"])/"source"/tag/"catalog.duckdb"; out.parent.mkdir(parents=True,exist_ok=True)
    source_root=Path(machine["data_root"]).resolve(); raw_glob=(source_root/"raw/alpaca/market/stocks/bars_1m/**/*.parquet").as_posix().replace("'","''")
    refs={n:repo_root/"reference"/f"{n}.parquet" for n in ("security_master","sp500_pit_membership_daily","corporate_actions")}
    lineage={"raw_glob":raw_glob,"references":{k:{"path":str(v),"size":v.stat().st_size,"mtime_ns":v.stat().st_mtime_ns} for k,v in refs.items()},"start":start,"end":end,"schema":1}
    manifest=out.with_suffix(".manifest.json"); h=content_hash(lineage)
    if out.exists() and manifest.exists() and json.loads(manifest.read_text()).get("content_hash")==h:return out
    partial=out.with_suffix(".partial.duckdb"); partial.unlink(missing_ok=True); con=duckdb.connect(str(partial))
    try:
        con.execute("SET threads TO 5")
        for name,path in refs.items():
            p=str(path).replace("'","''"); con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{p}')")
        con.execute("""CREATE TABLE split_factors_daily AS WITH dates AS (SELECT DISTINCT session_date FROM sp500_pit_membership_daily), eligible AS (SELECT DISTINCT s.security_id,d.session_date FROM security_master s CROSS JOIN dates d) SELECT e.security_id,e.session_date,COALESCE(EXP(SUM(LN(a.split_factor)) FILTER (WHERE a.split_factor>0 AND a.session_date>e.session_date)),1.0) split_factor FROM eligible e LEFT JOIN corporate_actions a ON a.security_id=e.security_id GROUP BY e.security_id,e.session_date""")
        con.execute(f"""CREATE VIEW bars_1m_raw AS WITH source AS (
          SELECT * FROM read_parquet('{raw_glob}',union_by_name=true,hive_partitioning=true)
          WHERE lower(feed)='sip' AND lower(adjustment)='raw' AND lower(timeframe) IN ('1min','1m')
            AND CAST(date AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'
          QUALIFY row_number() OVER(PARTITION BY symbol,timestamp,timeframe,feed,adjustment ORDER BY COALESCE(TRY_CAST(ingested_at AS TIMESTAMP),TIMESTAMP '1900-01-01') DESC,COALESCE(source_ingestion_id,'') DESC)=1)
          SELECT s.security_id,b.symbol,TRY_CAST(b.timestamp AS TIMESTAMPTZ) bar_start_ts_utc,TRY_CAST(b.timestamp AS TIMESTAMPTZ)+INTERVAL 1 MINUTE bar_end_ts_utc,TRY_CAST(b.timestamp AS TIMESTAMPTZ)+INTERVAL 1 MINUTE availability_ts_utc,CAST(TRY_CAST(b.timestamp AS TIMESTAMPTZ) AT TIME ZONE 'America/New_York' AS DATE) session_date,b.open,b.high,b.low,b.close,b.volume,b.vwap,b.trade_count,lower(b.feed) feed,lower(b.adjustment) adjustment,b.source_ingestion_id ingest_batch_id FROM source b JOIN security_master s USING(symbol)""")
        con.execute("""CREATE VIEW bars_1m_research AS SELECT b.security_id,b.bar_start_ts_utc,b.session_date,b.open/f.split_factor research_open,b.high/f.split_factor research_high,b.low/f.split_factor research_low,b.close/f.split_factor research_close,f.split_factor,'split_consistent' price_basis FROM bars_1m_raw b JOIN split_factors_daily f USING(security_id,session_date)""")
    finally: con.close()
    os.replace(partial,out); tmp=manifest.with_suffix(".manifest.json.partial"); tmp.write_text(json.dumps({"content_hash":h,**lineage},indent=2,sort_keys=True),encoding="utf-8"); os.replace(tmp,manifest); return out
