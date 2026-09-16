from __future__ import annotations
import json,os
from dataclasses import dataclass
from pathlib import Path
import numpy as np,pyarrow.parquet as pq
from quant_pipeline.errors import SealedDataViolation
from quant_pipeline.execution_data import write_sip_signal_export

def find_candidate(candidate_id:str,machine:dict):
    for p in Path(machine["run_root"]).glob("*/edge_registry.parquet"):
        rows=pq.read_table(p).to_pylist()
        for row in rows:
            if row.get("candidate_id")==candidate_id:return p.parent,row
    raise KeyError(f"Candidate not found: {candidate_id}")

def export_candidate_sip(candidate_id:str,machine:dict)->Path:
    run,row=find_candidate(candidate_id,machine); payload=row["state_payload"]
    if int(row["direction"])==0: raise ValueError("Descriptive zero-direction candidate cannot be exported as a SIP signal")
    production_signals=run/"candidates"/candidate_id/"dossier"/"signals.parquet"
    if production_signals.exists():
        frame=pq.read_table(production_signals).to_pandas(); rows=[{"candidate_id":candidate_id,"security_id":x.security_id,"symbol":x.symbol,"signal_ts_utc":x.signal_timestamp,"signal_timestamp":x.signal_timestamp,"direction":int(x.direction),"reference_exit_ts_utc":x.reference_exit_timestamp,"reference_exit_timestamp":x.reference_exit_timestamp,"state_definition":row["state_definition"],"resolution":int(row["resolution"]),"state_payload":row["state_payload"]} for x in frame.itertuples(index=False)]; out=run/"execution_data"/f"{candidate_id}.parquet"; out.parent.mkdir(exist_ok=True); return write_sip_signal_export(candidate=type("C",(),{"candidate_id":candidate_id})(),rows=rows,output_path=out)
    cells=payload.get("cells") if isinstance(payload,dict) else None
    if not cells:raise ValueError("Candidate has no structured cells")
    a=np.load(run/"canonical_states"/f"{row['feature_a_id']}__r{row['resolution']}.npy",mmap_mode="r")
    b=np.load(run/"canonical_states"/f"{row['feature_b_id']}__r{row['resolution']}.npy",mmap_mode="r")
    active=np.zeros(len(a),bool)
    for cell in cells:active|=(a==cell[0])&(b==cell[1])
    index=pq.read_table(run/"observation_index.parquet").to_pandas(); index=index.loc[active]
    horizon=int(row["target_id"].split("_")[1].removesuffix("m")); rows=[]
    for x in index.itertuples(index=False):
        exit_ts=x.decision_ts_utc+__import__('pandas').Timedelta(minutes=horizon); rows.append({"candidate_id":candidate_id,"security_id":int(x.security_id),"symbol":str(x.symbol),"signal_ts_utc":x.decision_ts_utc,"signal_timestamp":x.decision_ts_utc,"direction":int(row["direction"]),"reference_exit_ts_utc":exit_ts,"reference_exit_timestamp":exit_ts,"state_definition":row["state_definition"],"state_payload":row["state_payload"],"resolution":int(row["resolution"])})
    out=run/"execution_data"/f"{candidate_id}.parquet";out.parent.mkdir(exist_ok=True);return write_sip_signal_export(candidate=type("C",(),{"candidate_id":candidate_id})(),rows=rows,output_path=out)

def promote_replication(candidate_id:str,machine:dict)->Path:
    run,row=find_candidate(candidate_id,machine); auth=run/"authorizations"/f"{candidate_id}.json"
    if row.get("status")!="dossier_complete": raise SealedDataViolation("Candidate dossier is not complete")
    if not auth.exists():raise SealedDataViolation(f"Missing explicit replication authorization record: {auth}")
    a=json.loads(auth.read_text(encoding="utf-8")); required={"candidate_id","definition_hash","scope","authorized_by","authorized_at_utc"}
    if required-set(a) or a["candidate_id"]!=candidate_id or a["definition_hash"]!=row["definition_hash"] or a["scope"]!="sealed_replication":raise SealedDataViolation("Invalid replication authorization record")
    request={"candidate_id":candidate_id,"definition_hash":row["definition_hash"],"state_payload":row["state_payload"],"return_basis":row["return_basis"],"authorization":a,"status":"replication_authorized"}
    out=run/"replication"/f"{candidate_id}.request.json";out.parent.mkdir(exist_ok=True);tmp=out.with_suffix(".partial");tmp.write_text(json.dumps(request,indent=2,sort_keys=True,default=str),encoding="utf-8");os.replace(tmp,out);return out
