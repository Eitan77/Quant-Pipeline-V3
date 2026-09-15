from datetime import datetime,timezone,timedelta
import json
import pytest
from quant_pipeline.telemetry import ResourcePlan,StallWatchdog,run_with_resource_recovery

def test_resource_failures_degrade_but_logic_failures_stop():
    seen=[]
    def operation(plan):
        seen.append(plan)
        if len(seen)<3: raise MemoryError("CUDA out of memory")
        return plan
    result=run_with_resource_recovery(operation,ResourcePlan(tile_pairs=64,workers=8),max_retries=3)
    assert (result.tile_pairs,result.workers,result.attempts)==(16,2,2)
    with pytest.raises(ValueError): run_with_resource_recovery(lambda _:(_ for _ in ()).throw(ValueError("causality violation")),ResourcePlan())

def test_stall_watchdog_captures_diagnostics(tmp_path):
    old=datetime.now(timezone.utc)-timedelta(hours=1); (tmp_path/"STATUS.json").write_text(json.dumps({"heartbeat":old.isoformat(),"stage":"duals","completed":1,"expected":9}))
    result=StallWatchdog(tmp_path,stale_seconds=60).inspect(); assert result["stalled"] and result["diagnostic_path"]
