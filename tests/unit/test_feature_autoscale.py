from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from quant_pipeline.alpha_discovery.feature_autoscale import AdaptiveFeatureConcurrency
from quant_pipeline.alpha_discovery.resources import child_numeric_thread_limits


def _controller(**overrides):
    values=dict(minimum=4,maximum=16,initial=6,step=2,tuning_window_seconds=10,
                tuning_min_completions=8,min_gain_fraction=.02,regression_fraction=.05,
                memory_guard_multiplier=1.25,default_worker_memory_bytes=1<<30,cooldown_seconds=5)
    values.update(overrides); controller=AdaptiveFeatureConcurrency(**values); controller.begin_wave(0)
    return controller


def _epoch(controller,work,now,available=30<<30,reserve=6<<30):
    for _ in range(8): controller.observe(work_units=work,peak_rss_bytes=512<<20,now=now)
    return controller.evaluate(available_bytes=available,reserve_bytes=reserve,now=now)


def test_ramps_up_and_respects_hard_cap():
    controller=_controller(maximum=10)
    assert _epoch(controller,10,10)["to_workers"]==8
    assert _epoch(controller,13,20)["to_workers"]==10
    assert _epoch(controller,20,30)["to_workers"]==10


def test_throughput_regression_backs_off():
    controller=_controller()
    assert _epoch(controller,10,10)["to_workers"]==8
    event=_epoch(controller,8,20)
    assert event["reason"]=="throughput_regressed" and controller.current==6


def test_memory_pressure_cooldown_and_minimum():
    controller=_controller(tuning_window_seconds=1,cooldown_seconds=5)
    event=controller.evaluate(available_bytes=6<<30,reserve_bytes=6<<30,now=.1)
    assert event["reason"]=="memory_pressure" and controller.current==4
    _epoch(controller,10,2)
    assert controller.current==4
    controller.evaluate(available_bytes=5<<30,reserve_bytes=6<<30,now=2.1)
    assert controller.current==4


def _thread_env():
    return {key:os.environ.get(key) for key in
            ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS","NUMEXPR_NUM_THREADS")}


def test_child_numeric_thread_limits_are_inherited():
    with child_numeric_thread_limits(blas_threads=1,omp_threads=1):
        with ProcessPoolExecutor(max_workers=1) as pool:
            assert set(pool.submit(_thread_env).result().values())=={"1"}


def test_worker_waits_for_headroom_before_read(monkeypatch,tmp_path):
    from quant_pipeline.alpha_discovery import resources,run
    from quant_pipeline.alpha_discovery.features import base
    calls={"memory":0,"read":0}
    def memory():
        calls["memory"]+=1
        return ((4 if calls["memory"]<3 else 8)<<30,32<<30)
    def read(*args,**kwargs):
        assert calls["memory"]>=3; calls["read"]+=1
        return pd.DataFrame({"observation_id":[0],"emit":[True]})
    class Builder:
        def __init__(self,frame): self.frame=frame
    monkeypatch.setattr(resources,"_system_memory",memory)
    monkeypatch.setattr(run.time,"sleep",lambda _:None)
    monkeypatch.setattr(run.pd,"read_parquet",read)
    monkeypatch.setattr(base,"FeatureBuilder",Builder)
    result=run._build_alpha_security_lifecycle("panel",[],"s",str(tmp_path),6<<30)
    assert calls["read"]==1 and result["emitted_rows"]==1
