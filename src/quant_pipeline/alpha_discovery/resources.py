from __future__ import annotations
from contextlib import contextmanager
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


def logical_cpu_count() -> int:
    return max(1,os.cpu_count() or 1)


def configured_feature_worker_cap(compute) -> int:
    logical=logical_cpu_count()
    return logical if compute.cpu_workers=="auto" else max(1,min(logical,int(compute.cpu_workers)))


def configured_duckdb_threads(compute) -> int:
    logical=logical_cpu_count()
    return logical if compute.duckdb_threads=="auto" else max(1,min(logical,int(compute.duckdb_threads)))


def host_memory_reserve_bytes(compute,total:int)->int:
    if compute.host_reserve_gb is not None:
        return max(1<<30,int(float(compute.host_reserve_gb)*(1<<30)))
    return max(1<<30,int(total*(1-float(compute.host_memory_fraction))))


@contextmanager
def child_numeric_thread_limits(*,blas_threads:int,omp_threads:int):
    keys={"OMP_NUM_THREADS":str(omp_threads),"MKL_NUM_THREADS":str(blas_threads),
          "OPENBLAS_NUM_THREADS":str(blas_threads),"NUMEXPR_NUM_THREADS":str(blas_threads)}
    previous={key:os.environ.get(key) for key in keys}; os.environ.update(keys)
    try: yield
    finally:
        for key,value in previous.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value


def calibrated_resources(compute) -> tuple[int, str, dict]:
    logical=logical_cpu_count()
    available,total=_system_memory()
    reserved=host_memory_reserve_bytes(compute,total)
    usable=max(4*(1<<30),available-reserved)
    workers=configured_feature_worker_cap(compute)
    memory=f"{max(4,int(usable*.75/(1<<30)))}GB" if str(compute.duckdb_memory_limit).lower()=="auto" else str(compute.duckdb_memory_limit)
    return workers,memory,{"logical_cpus":logical,"selected_workers":workers,"available_bytes":available,"reserved_bytes":reserved,"worker_memory_budget_bytes":usable}


def host_memory_headroom(compute) -> tuple[int, int, int]:
    """Return live available bytes, configured safety reserve, and total RAM."""
    available,total=_system_memory()
    reserved=host_memory_reserve_bytes(compute,total)
    return available,reserved,total
