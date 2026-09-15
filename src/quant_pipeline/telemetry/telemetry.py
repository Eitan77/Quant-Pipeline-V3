from __future__ import annotations
from datetime import datetime,timezone
import json,os,shutil,subprocess
from pathlib import Path
import psutil

class Telemetry:
    def __init__(self,run_dir:Path): self.run_dir=Path(run_dir); self.run_dir.mkdir(parents=True,exist_ok=True); self.status={"stage":"initializing","completed":0,"expected":0,"last_error":None}
    def event(self,name,**fields):
        now=datetime.now(timezone.utc).isoformat(); row={"ts_utc":now,"event":name,**fields}
        with (self.run_dir/"events.jsonl").open("a",encoding="utf-8") as f: f.write(json.dumps(row,default=str)+"\n")
        vm=psutil.virtual_memory(); disk=shutil.disk_usage(self.run_dir)
        self.status.update({"heartbeat":now,"pid":os.getpid(),"rss_gb":psutil.Process().memory_info().rss/1024**3,"available_ram_gb":vm.available/1024**3,"cpu_percent":psutil.cpu_percent(),"disk_free_gb":disk.free/1024**3})
        try:
            line=subprocess.check_output(["nvidia-smi","--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,clocks.sm,power.draw","--format=csv,noheader,nounits"],text=True,timeout=3).strip().splitlines()[0]
            util,used,total,temp,clock,power=(float(x.strip()) for x in line.split(",")); self.status.update({"gpu_util_percent":util,"gpu_memory_used_mb":used,"gpu_memory_total_mb":total,"gpu_temperature_c":temp,"gpu_clock_mhz":clock,"gpu_power_w":power})
        except Exception: pass
        if "stage" in fields:self.status["stage"]=fields["stage"]
        tmp=self.run_dir/"STATUS.json.partial"; tmp.write_text(json.dumps(self.status,indent=2,sort_keys=True,default=str),encoding="utf-8"); os.replace(tmp,self.run_dir/"STATUS.json")
    def progress(self,stage,completed,expected,**fields): self.status.update({"stage":stage,"completed":completed,"expected":expected,**fields}); self.event("progress",stage=stage,completed=completed,expected=expected)
