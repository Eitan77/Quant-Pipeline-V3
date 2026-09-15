from __future__ import annotations
import argparse,json
from pathlib import Path
from quant_pipeline.app import run_pipeline,status
from quant_pipeline.config import load_machine_config,load_research_config
from quant_pipeline.errors import SealedDataViolation
def parser():
    p=argparse.ArgumentParser(prog="quant_pipeline"); s=p.add_subparsers(dest="command",required=True)
    for cmd in ("run",): q=s.add_parser(cmd); q.add_argument("--request",type=Path,required=True); q.add_argument("--machine",type=Path,required=True)
    for cmd in ("resume","status"): q=s.add_parser(cmd); q.add_argument("--run-id",required=True); q.add_argument("--machine",type=Path,required=True)
    for cmd in ("replicate","export-sip"): q=s.add_parser(cmd); q.add_argument("--candidate-id",required=True); q.add_argument("--machine",type=Path,required=True)
    return p
def main():
    a=parser().parse_args(); m=load_machine_config(a.machine)
    if a.command=="run": print(run_pipeline(research=load_research_config(a.request),machine=m)); return 0
    if a.command=="status": print(json.dumps(status(a.run_id,m),indent=2)); return 0
    if a.command=="resume":
        req=Path(m["run_root"])/a.run_id/"request.yaml"
        if not req.exists(): req=Path("configs/research/smoke.yaml")
        print(run_pipeline(research=load_research_config(req),machine=m,resume=True)); return 0
    if a.command=="replicate": raise SealedDataViolation("Replication requires a separate signed authorization record and is intentionally unavailable to discovery CLI")
    if a.command=="export-sip": raise RuntimeError("Use a frozen candidate from a completed run; export service requires candidate run context")
if __name__=="__main__": raise SystemExit(main())

