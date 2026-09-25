"""Shared host/GPU admission limits for production and research jobs."""
from __future__ import annotations

import psutil


class ResourcePolicy:
    def __init__(self, machine):
        self.machine = machine
        self.host_reserve = int(machine.get("host_reserve_gb", 6) * (1 << 30))
        self.gpu_ceiling = int(machine.get("gpu_working_ceiling_gb", 9.5) * (1 << 30))

    def state_budget(self, device="cpu"):
        host_free = max(0, psutil.virtual_memory().available - self.host_reserve)
        # GPU accumulators stay on device; larger batches reuse the same input
        # pass across adjacent group partitions without consuming host RAM.
        budget = min(2 * (1 << 30), host_free // 4)
        if device != "cpu":
            import torch
            free, _ = torch.cuda.mem_get_info(device)
            budget = min(5 * (1 << 30), host_free, self.gpu_ceiling, int(free * .5))
        if budget < 16 * (1 << 20):
            raise MemoryError("Insufficient live host/GPU headroom for a subgroup tile")
        return int(budget)

    def duckdb_gib(self):
        available = max(0, psutil.virtual_memory().available - self.host_reserve)
        requested = int(self.machine.get("duckdb_memory_limit_gb", 4))
        return max(1, min(24, requested, max(1, available // (1 << 30) // 2)))

    @staticmethod
    def feature_workers(compute, runtime_cap=None):
        from quant_pipeline.alpha_discovery.resources import configured_feature_worker_cap
        limit = configured_feature_worker_cap(compute)
        if runtime_cap is not None:
            limit = min(limit, int(runtime_cap))
        reserve=int(float(compute.host_reserve_gb or 6)*(1<<30))
        available=max(0,psutil.virtual_memory().available-reserve)
        per_worker=max(1,int(float(compute.feature_default_worker_memory_gb)*
                             float(compute.feature_memory_guard_multiplier)*(1<<30)))
        limit=min(limit,max(1,available//per_worker))
        return max(1, limit)

    def compatibility_workers(self):
        """Threaded Arrow/Numpy reductions share storage and accumulator memory."""
        logical=max(1,psutil.cpu_count(logical=True) or 1)
        available=max(0,psutil.virtual_memory().available-self.host_reserve)
        # Bound concurrent decoded tiles while allowing the shared-memory reducer
        # to use the host; unlike feature workers these are not full processes.
        memory_cap=max(1,available//(512*(1<<20)))
        return max(1,min(logical,int(memory_cap)))
