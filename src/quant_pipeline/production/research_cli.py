"""Local JSON command surface for committed research evidence."""
from __future__ import annotations

import json
import time
from pathlib import Path

from quant_pipeline.config import load_machine_config

from .research_jobs import JobStore,run_one,worker_lock
from .research_service import ResearchService


def add_parser(commands):
    root=commands.add_parser("research")
    leaves=root.add_subparsers(dest="research_command",required=True)
    for name in ("describe","query","search","inspect","experiment","worker"):
        parser=leaves.add_parser(name)
        parser.add_argument("--machine",type=Path,required=True)
        parser.add_argument("--run-id",required=True)
        if name=="describe": parser.add_argument("--details",action="store_true")
        if name in {"query","search","inspect","experiment"}:
            parser.add_argument("--spec",type=Path,required=True)
        if name=="worker":
            mode=parser.add_mutually_exclusive_group(required=True)
            mode.add_argument("--once",action="store_true")
            mode.add_argument("--poll",action="store_true")
    jobs=leaves.add_parser("job")
    actions=jobs.add_subparsers(dest="job_command",required=True)
    for name in ("status","results","cancel","retry"):
        parser=actions.add_parser(name)
        parser.add_argument("--machine",type=Path,required=True)
        parser.add_argument("--run-id",required=True)
        parser.add_argument("--job-id",required=True)


def _read_spec(path):
    value=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError("Research spec must be a JSON object")
    return value


def _worker(service,machine,poll):
    root=Path(machine["run_root"])
    store=JobStore(service.root/"research"/"jobs.sqlite")
    handlers={
        "subgroup_search":lambda spec,cancelled:service.search(spec["payload"],cancelled),
        "diagnostic":lambda spec,cancelled:service.inspect(spec["payload"],cancelled),
        "neighbor_scan":lambda spec,cancelled:service.experiment(spec["payload"],cancelled),
        "backtest":lambda spec,cancelled:service.experiment(spec["payload"],cancelled),
    }
    completed=0
    try:
        with worker_lock(root/"research_worker.lock"):
            store.recover_after_lock()
            while True:
                with worker_lock(root/"numerical_owner.lock"):
                    ran=run_one(store,handlers)
                if ran: completed+=1
                elif not poll: break
                else: time.sleep(2)
    finally: store.close()
    return {"status":"stopped","jobs_processed":completed}


def main(args):
    machine=load_machine_config(args.machine)
    service=ResearchService(machine,args.run_id)
    command=args.research_command
    if command=="describe": return service.describe(include_definitions=args.details)
    if command=="query": return service.query(_read_spec(args.spec))
    if command in {"search","inspect","experiment"}:
        payload=_read_spec(args.spec)
        identity=service.describe()["evidence_id"]
        if not identity: raise RuntimeError("No verified evidence published for this run")
        kind={"search":"subgroup_search","inspect":"diagnostic","experiment":"backtest" if payload.get("kind")=="backtest" else "neighbor_scan"}[command]
        store=JobStore(service.root/"research"/"jobs.sqlite")
        try: job_id=store.submit({"kind":kind,"run_id":args.run_id,"evidence_id":identity,"payload":payload})
        finally: store.close()
        return {"job_id":job_id,"status":"queued","worker_available":"unknown","worker_command":f"research worker --machine {args.machine} --run-id {args.run_id} --once"}
    if command=="worker": return _worker(service,machine,args.poll)
    if command=="job":
        if args.job_command=="status": return service.job_status(args.job_id)
        if args.job_command=="results": return service.job_results(args.job_id)
        if args.job_command=="cancel": return service.cancel(args.job_id)
        store=JobStore(service.root/"research"/"jobs.sqlite")
        try: store.retry(args.job_id); return store.get(args.job_id)
        finally: store.close()
    raise ValueError(command)
