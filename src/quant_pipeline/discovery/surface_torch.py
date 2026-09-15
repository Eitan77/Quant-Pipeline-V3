from __future__ import annotations
import numpy as np, torch
from .surface_cpu import INVALID_STATE
from quant_pipeline.contracts import SurfaceStats

class TorchSurfaceScanner:
    def __init__(self,device="cuda:0"):
        self.device=torch.device(device)
        if self.device.type=="cuda" and not torch.cuda.is_available(): raise RuntimeError("CUDA unavailable")
    @torch.inference_mode()
    def scan_one(self,*,state_a,state_b,target_bps,target_valid,resolution):
        a=torch.as_tensor(state_a,device=self.device); b=torch.as_tensor(state_b,device=self.device); y=torch.as_tensor(target_bps,device=self.device,dtype=torch.float64); tv=torch.as_tensor(target_valid,device=self.device,dtype=torch.bool)
        v=tv&torch.isfinite(y)&(a!=INVALID_STATE)&(b!=INVALID_STATE)&(a<resolution)&(b<resolution); n=resolution**2
        if bool(v.any()):
            cell=a[v].long()*resolution+b[v].long(); counts=torch.bincount(cell,minlength=n); sums=torch.bincount(cell,weights=y[v],minlength=n)
        else: counts=torch.zeros(n,dtype=torch.int64,device=self.device); sums=torch.zeros(n,dtype=torch.float64,device=self.device)
        means=torch.full((n,),float("nan"),dtype=torch.float64,device=self.device); nz=counts>0; means[nz]=sums[nz]/counts[nz]; shape=(resolution,resolution)
        return SurfaceStats(resolution,counts.reshape(shape).cpu().numpy(),sums.reshape(shape).cpu().numpy(),means.reshape(shape).cpu().numpy())

class BatchedTorchSurfaceScanner:
    def __init__(self,device="cuda:0",observation_chunk=1_000_000): self.one=TorchSurfaceScanner(device); self.observation_chunk=observation_chunk
    def scan_pair_batch(self,*,states_a,states_b,target_bps,target_valid,resolution):
        out=[self.one.scan_one(state_a=a,state_b=b,target_bps=target_bps,target_valid=target_valid,resolution=resolution) for a,b in zip(states_a,states_b)]
        return np.stack([x.counts.ravel() for x in out]),np.stack([x.sums_bps.ravel() for x in out])

