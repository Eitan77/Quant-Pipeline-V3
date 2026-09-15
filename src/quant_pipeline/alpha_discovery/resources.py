from __future__ import annotations
import os


def _system_memory() -> tuple[int, int]:
    try:
        import psutil
        status=psutil.virtual_memory()
        return int(status.available),int(status.total)
    except ImportError:
        if os.name=="nt":
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_=[("length",ctypes.c_ulong),("memory_load",ctypes.c_ulong),
                          ("total_physical",ctypes.c_ulonglong),("available_physical",ctypes.c_ulonglong),
                          ("total_page_file",ctypes.c_ulonglong),("available_page_file",ctypes.c_ulonglong),
                          ("total_virtual",ctypes.c_ulonglong),("available_virtual",ctypes.c_ulonglong),
                          ("available_extended_virtual",ctypes.c_ulonglong)]
            status=MemoryStatus(); status.length=ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                raise OSError("GlobalMemoryStatusEx failed")
            return int(status.available_physical),int(status.total_physical)
        page_size=os.sysconf("SC_PAGE_SIZE")
        return int(page_size*os.sysconf("SC_AVPHYS_PAGES")),int(page_size*os.sysconf("SC_PHYS_PAGES"))


def calibrated_resources(compute) -> tuple[int, str, dict]:
    logical=max(1,os.cpu_count() or 1)
    available,total=_system_memory()
    reserved=max(1*(1<<30),int(total*(1-float(compute.host_memory_fraction))))
    usable=max(4*(1<<30),available-reserved)
    # The pool exposes every logical CPU. Feature submission is throttled from
    # live host memory instead of assuming a fixed amount of RAM per worker.
    workers=logical if compute.cpu_workers=="auto" else int(compute.cpu_workers)
    memory=f"{max(4,int(usable*.75/(1<<30)))}GB" if str(compute.duckdb_memory_limit).lower()=="auto" else str(compute.duckdb_memory_limit)
    return workers,memory,{"logical_cpus":logical,"selected_workers":workers,"available_bytes":available,"reserved_bytes":reserved,"worker_memory_budget_bytes":usable}


def host_memory_headroom(compute) -> tuple[int, int, int]:
    """Return live available bytes, configured safety reserve, and total RAM."""
    available,total=_system_memory()
    reserved=max(1*(1<<30),int(total*(1-float(compute.host_memory_fraction))))
    return available,reserved,total
