from __future__ import annotations
import argparse,json
from pathlib import Path
from quant_pipeline.app import run_pipeline,status
from quant_pipeline.config import load_machine_config,load_research_config
from quant_pipeline.errors import SealedDataViolation
def parser():
    p=argparse.ArgumentParser(prog="quant_pipeline"); s=p.add_subparsers(dest="command",required=True)
    from quant_pipeline.production.research_cli import add_parser
    add_parser(s)
    for cmd in ("run",): q=s.add_parser(cmd); q.add_argument("--request",type=Path,required=True); q.add_argument("--machine",type=Path,required=True)
    for cmd in ("resume","status"): q=s.add_parser(cmd); q.add_argument("--run-id",required=True); q.add_argument("--machine",type=Path,required=True)
    for cmd in ("replicate","export-sip"): q=s.add_parser(cmd); q.add_argument("--candidate-id",required=True); q.add_argument("--machine",type=Path,required=True)
    return p
def main():
    from quant_pipeline.production.research_cli import main as research_main
    a=parser().parse_args(); m=load_machine_config(a.machine)
    if a.command=="research": print(json.dumps(research_main(a),indent=2,default=str)); return 0
    if a.command=="run":
        run_id=run_pipeline(research=load_research_config(a.request),machine=m)
        print(run_id)
        return 0 if status(run_id,m).get("stage")=="complete" else 2
    if a.command=="status": print(json.dumps(status(a.run_id,m),indent=2)); return 0
    if a.command=="resume":
        req=Path(m["run_root"])/a.run_id/"request.yaml"
        if not req.exists(): raise FileNotFoundError(f"Stored run request is missing: {req}")
        research=load_research_config(req)
        if research["run_name"]!=a.run_id: raise RuntimeError(f"Stored request run_name {research['run_name']!r} does not match {a.run_id!r}")
        print(run_pipeline(research=research,machine=m,resume=True))
        return 0 if status(a.run_id,m).get("stage")=="complete" else 2
    if a.command=="replicate":
        from quant_pipeline.candidates.service import promote_replication
        print(promote_replication(a.candidate_id,m)); return 0
    if a.command=="export-sip":
        from quant_pipeline.candidates.service import export_candidate_sip
        print(export_candidate_sip(a.candidate_id,m)); return 0
if __name__=="__main__": raise SystemExit(main())
