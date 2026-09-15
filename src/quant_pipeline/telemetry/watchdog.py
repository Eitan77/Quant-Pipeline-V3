from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path


FATAL_MARKERS=("causality", "schema", "corrupt", "parity", "invalid feature")
RESOURCE_MARKERS=("out of memory", "cuda oom", "cannot allocate memory", "temporary i/o", "temporarily unavailable")


def failure_class(exc: BaseException) -> str:
    text=f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in FATAL_MARKERS): return "fatal_correctness"
    if isinstance(exc,(MemoryError,TimeoutError,OSError)) or any(marker in text for marker in RESOURCE_MARKERS): return "recoverable_resource"
    return "fatal_unknown"


@dataclass(frozen=True,slots=True)
class ResourcePlan:
    tile_pairs:int=8192
    workers:int=6
    attempts:int=0

    def degraded(self) -> "ResourcePlan":
        return replace(self,tile_pairs=max(1,self.tile_pairs//2),workers=max(1,self.workers//2),attempts=self.attempts+1)


def run_with_resource_recovery(operation,plan:ResourcePlan,max_retries:int=3,on_retry=None):
    current=plan
    while True:
        try: return operation(current)
        except Exception as exc:
            if failure_class(exc)!="recoverable_resource" or current.attempts>=max_retries: raise
            current=current.degraded()
            if on_retry: on_retry(exc,current)


class StallWatchdog:
    def __init__(self,run_dir:Path,stale_seconds:int=900): self.run_dir=Path(run_dir); self.stale_seconds=stale_seconds
    def inspect(self,now:datetime|None=None):
        status_path=self.run_dir/"STATUS.json"
        if not status_path.exists(): return {"stalled":True,"reason":"missing_status"}
        status=json.loads(status_path.read_text(encoding="utf-8")); heartbeat=datetime.fromisoformat(status["heartbeat"]); now=now or datetime.now(timezone.utc); age=(now-heartbeat).total_seconds(); result={"stalled":age>self.stale_seconds,"heartbeat_age_seconds":age,"stage":status.get("stage"),"completed":status.get("completed"),"expected":status.get("expected")}
        if result["stalled"]:
            path=self.run_dir/"diagnostics"/f"stall-{now.strftime('%Y%m%dT%H%M%SZ')}.json"; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps({**result,"status":status},indent=2,sort_keys=True),encoding="utf-8"); result["diagnostic_path"]=str(path)
        return result
