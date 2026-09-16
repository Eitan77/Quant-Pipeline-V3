from pathlib import Path
import pytest

def make_test_machine(root:Path)->dict:
    source=root/"source"; source.mkdir(parents=True,exist_ok=True)
    return {"data_root":str(source),"source_catalog":str(source/"catalog.duckdb"),"cache_root":str(root/"cache"),"run_root":str(root/"runs"),"scratch_root":str(root/"scratch"),"duckdb_temp":str(root/"scratch/duckdb"),"gpu_device":"cuda:0","feature_workers":2,"duckdb_threads":2,"duckdb_memory_limit_gb":2}

@pytest.fixture
def test_machine(tmp_path): return make_test_machine(tmp_path)
