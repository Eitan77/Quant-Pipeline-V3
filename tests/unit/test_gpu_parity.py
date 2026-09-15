import numpy as np,pytest,torch
from quant_pipeline.discovery.surface_cpu import scan_surface_cpu
from quant_pipeline.discovery.surface_torch import TorchSurfaceScanner
@pytest.mark.skipif(not torch.cuda.is_available(),reason="CUDA unavailable")
def test_cpu_gpu_parity():
    rng=np.random.default_rng(4); a=rng.integers(0,5,1000,dtype=np.uint8); b=rng.integers(0,5,1000,dtype=np.uint8); y=rng.normal(size=1000).astype(np.float32); v=np.ones(1000,bool)
    cpu=scan_surface_cpu(state_a=a,state_b=b,target_bps=y,target_valid=v,resolution=5); gpu=TorchSurfaceScanner().scan_one(state_a=a,state_b=b,target_bps=y,target_valid=v,resolution=5)
    np.testing.assert_array_equal(cpu.counts,gpu.counts); np.testing.assert_allclose(cpu.sums_bps,gpu.sums_bps,rtol=1e-7,atol=1e-7); np.testing.assert_allclose(cpu.means_bps,gpu.means_bps,rtol=1e-7,atol=1e-7,equal_nan=True)

