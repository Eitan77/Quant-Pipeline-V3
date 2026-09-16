from __future__ import annotations
from datetime import datetime,timezone
import json,tempfile,time
from pathlib import Path
import numpy as np,torch,yaml
from quant_pipeline.app import run_pipeline
from quant_pipeline.config import load_research_config,load_machine_config
from quant_pipeline.discovery.surface_torch import TorchSurfaceScanner
ROOT=Path(__file__).resolve().parents[1]
r=load_research_config(ROOT/"configs/research/smoke.yaml"); r["run_name"]="benchmark_smoke"
m=load_machine_config(ROOT/"configs/machines/local.yaml")
with tempfile.TemporaryDirectory(dir=m["scratch_root"]) as td:
    t=Path(td); bm={**m,"cache_root":str(t/"cache"),"run_root":str(t/"runs"),"scratch_root":str(t/"scratch"),"duckdb_temp":str(t/"scratch/duckdb")}
    a=time.perf_counter(); run_pipeline(research=r,machine=bm); cold=time.perf_counter()-a
    a=time.perf_counter(); run_pipeline(research=r,machine=bm,resume=True); warm=time.perf_counter()-a
rng=np.random.default_rng(9); n=175_000; a=rng.integers(0,10,n,dtype=np.uint8); b=rng.integers(0,10,n,dtype=np.uint8); y=rng.normal(size=n).astype(np.float32); valid=np.ones(n,bool); scanner=TorchSurfaceScanner("cuda:0"); scanner.scan_one(state_a=a,state_b=b,target_bps=y,target_valid=valid,resolution=10); torch.cuda.synchronize(); t0=time.perf_counter(); loops=30
for _ in range(loops): scanner.scan_one(state_a=a,state_b=b,target_bps=y,target_valid=valid,resolution=10)
torch.cuda.synchronize(); elapsed=time.perf_counter()-t0
external=Path(m["run_root"])/"v3_external_smoke"; status=json.loads((external/"STATUS.json").read_text()) if (external/"STATUS.json").exists() else {}
checkpoint=json.loads((external/"checkpoints/scan-duals-coarse.json").read_text()) if (external/"checkpoints/scan-duals-coarse.json").exists() else {}
times=[json.loads(x.read_text()) for x in (external/"checkpoints").glob("*.json")] if (external/"checkpoints").exists() else []
started=[datetime.fromisoformat(x["started_at"]) for x in times if x.get("started_at")]; completed=[datetime.fromisoformat(x["completed_at"]) for x in times if x.get("completed_at")]
external_cold=(max(completed)-min(started)).total_seconds() if started and completed else None
payload={"created_at_utc":datetime.now(timezone.utc).isoformat(),"deterministic_smoke_cold_seconds":cold,"deterministic_smoke_warm_resume_seconds":warm,"gpu_microbenchmark":{"device":torch.cuda.get_device_name(0),"observations":n,"pair_targets":loops,"seconds":elapsed,"pair_targets_per_second":loops/elapsed},"external_smoke":{"rows":175419,"cold_wall_seconds":external_cold,"latest_resume_seconds":status.get("elapsed_seconds"),"dual_pair_targets_per_second":checkpoint.get("pair_targets_per_second"),"resolution_tests_per_second":checkpoint.get("resolution_tests_per_second"),"backend":checkpoint.get("backend")}}
out=ROOT/"docs/BENCHMARKS.json"; out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8"); print(json.dumps(payload,indent=2))
