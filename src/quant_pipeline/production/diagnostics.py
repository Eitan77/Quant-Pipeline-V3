"""On-demand state diagnostics from verified arrays and exact target ledger."""
from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from quant_pipeline.alpha_discovery.execution.candidate_backtest import decode_packed_bins
from .coverage import _members
from .evidence_identity import atomic_json, digest, file_digest
from .evidence_store import EvidenceReader


EVENT_SCHEMA=pa.schema([("observation_id",pa.int64()),("security_id",pa.string()),
    ("session_date",pa.date32()),("decision_ts",pa.timestamp("us",tz="UTC")),
    ("target",pa.float64())])


def prepare_state_events(root, reader_manifest, spec, *, cancelled=lambda:False):
    """Stream exactly selected valid observations into an independently cached event file."""
    root=Path(root)
    grid=spec["grid"]
    reader=EvidenceReader(root,"evidence/reader.json",grid)
    pair_id=spec["pair_id"]
    _,definitions=_members(root,grid,reader.grid,spec.get("state_kind","dual"))
    if pair_id not in definitions: raise ValueError("Pair outside verified scope")
    features=definitions[pair_id]
    resolution=int(spec["resolution"])
    cells=set(map(int,spec["cells"]))
    maximum=resolution if len(features)==1 else resolution**2
    if resolution not in (3,5,10) or not cells or min(cells)<0 or max(cells)>=maximum:
        raise ValueError("Invalid selected cells")
    if spec["target_id"] not in reader.grid["targets"]: raise ValueError("Target outside verified scope")
    event_state={key:spec[key] for key in ("grid","state_kind","pair_id","target_id","resolution") if key in spec}
    event_state["cells"]=sorted(cells)
    if "grouping" in spec:
        event_state["grouping"]=spec["grouping"]
        event_state["group_ids"]=sorted(set(map(int,spec["group_ids"])))
    identity=digest({"evidence":reader_manifest["evidence_id"],"state":event_state,"schema":1})
    destination=root/"research"/"diagnostics"/identity/"events.parquet"
    marker=destination.parent/"events.json"
    if destination.exists() and marker.exists():
        committed=json.loads(marker.read_text(encoding="utf-8"))
        if committed.get("identity")==identity and committed.get("sha256")==file_digest(destination):
            return destination,identity
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix(".partial.parquet")
    selected=0
    offset=0
    obs_path=root/reader.grid["observations"]
    with pq.ParquetWriter(temporary,EVENT_SCHEMA,compression="zstd") as writer:
        for batch in pq.ParquetFile(obs_path).iter_batches(batch_size=100_000,
                          columns=["observation_id","security_id","session_date","decision_ts"]):
            if cancelled():raise InterruptedError("Diagnostic cancelled")
            stop=offset+batch.num_rows
            packed=reader.read_columns("bins",list(features),offset,stop)
            target=reader.read_columns("targets",[spec["target_id"]],offset,stop)[:,0]
            a=decode_packed_bins(packed[:,0],resolution)
            if len(features)==2:
                b=decode_packed_bins(packed[:,1],resolution)
                cell=a*resolution+b
                valid=(a>=0)&(b>=0)
            else:
                cell=a;valid=a>=0
            active=valid&np.isfinite(target)&np.isin(cell,list(cells))
            if "grouping" in spec:
                groups=reader.read_groups(spec["grouping"],offset,stop)
                active&=np.isin(groups,list(map(int,spec["group_ids"])))
            if np.any(active):
                table=batch.filter(pa.array(active))
                table=table.append_column("target",pa.array(target[active].astype(np.float64)))
                writer.write_table(pa.Table.from_batches([table.cast(EVENT_SCHEMA)],schema=EVENT_SCHEMA))
                selected+=int(active.sum())
            offset=stop
    if offset!=reader.rows:raise ValueError("Observation stream and verified arrays disagree")
    os.replace(temporary,destination)
    atomic_json(marker,{"identity":identity,"evidence_id":reader_manifest["evidence_id"],
                    "sha256":file_digest(destination),
                    "selected_observations":selected,"status":"complete","path":destination.relative_to(root).as_posix()})
    return destination,identity


def inspect_state(root,reader_manifest,spec,*,cancelled=lambda:False):
    root=Path(root)
    kind=spec["kind"]
    if kind not in {"symbol","time","opportunities"}:raise ValueError("Unsupported independent diagnostic")
    events,identity=prepare_state_events(root,reader_manifest,spec,cancelled=cancelled)
    destination=events.parent/f"{kind}.json"
    if destination.exists():return {"status":"complete","result":destination.relative_to(root).as_posix()}
    with duckdb.connect() as con:
        if kind=="symbol":
            rows=con.execute("""SELECT security_id,count(*) n,avg(target)*10000 mean_bps,
                sum(target)*10000 sum_bps FROM read_parquet(?) GROUP BY 1 ORDER BY n DESC,security_id""",[str(events)]).fetchall()
            result={"basis":"valid_active_observations","rows":[dict(security_id=s,n=n,mean_bps=m,sum_bps=v) for s,n,m,v in rows]}
        elif kind=="time":
            rows=con.execute("""SELECT strftime(session_date,'%Y-%m') month,count(*) n,
                avg(target)*10000 mean_bps FROM read_parquet(?) GROUP BY 1 ORDER BY 1""",[str(events)]).fetchall()
            result={"basis":"valid_active_observations","rows":[dict(month=m,n=n,mean_bps=v) for m,n,v in rows]}
        else:
            ledger=root/"cache"/"targets"/f"{spec['grid']}.parquet"
            if not ledger.exists():
                return {"status":"unavailable","reason":"Exact target exit ledger is absent"}
            step=5 if spec["grid"]=="intraday_5m" else 1 if spec["grid"]=="intraday_1m" else None
            if step is None and spec["grid"] not in {"daily_close","preclose_1555"}:
                return {"status":"unavailable","reason":"Exact episode adjacency is undefined for this grid"}
            query="""SELECT e.observation_id,e.security_id,e.session_date,e.decision_ts,t.exit_ts
                FROM read_parquet(?) e JOIN read_parquet(?) t
                  ON e.observation_id=t.observation_id AND t.target_id=?
                ORDER BY e.security_id,e.session_date,e.decision_ts"""
            cursor=con.execute(query,[str(events),str(ledger),spec["target_id"]])
            previous={};next_allowed={};episodes=0;accepted=0;missing_exit=0
            while batch:=cursor.fetchmany(10000):
                if cancelled():raise InterruptedError("Diagnostic cancelled")
                for obs_id,security,session,decision,exit_ts in batch:
                    key=(security,session)
                    prior=previous.get(key)
                    if step is not None and prior is not None and decision-prior==__import__("datetime").timedelta(minutes=step):
                        previous[key]=decision;continue
                    episodes+=1;previous[key]=decision
                    if exit_ts is None:missing_exit+=1;continue
                    if decision>=next_allowed.get(security,decision):
                        accepted+=1;next_allowed[security]=exit_ts
            result={"basis":"episode_starts_with_exact_target_exits","episode_count":episodes,
                    "independent_opportunity_count":accepted,"missing_exit_count":missing_exit}
    payload={"status":"complete","evidence_id":reader_manifest["evidence_id"],
             "diagnostic_id":digest({"event":identity,"kind":kind}),"kind":kind,"result":result}
    atomic_json(destination,payload)
    return {"status":"complete","result":destination.relative_to(root).as_posix()}
