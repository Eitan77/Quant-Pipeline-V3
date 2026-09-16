from __future__ import annotations

from dataclasses import dataclass,field


@dataclass
class AdaptiveFeatureConcurrency:
    minimum:int
    maximum:int
    initial:int
    step:int
    tuning_window_seconds:float
    tuning_min_completions:int
    min_gain_fraction:float
    regression_fraction:float
    memory_guard_multiplier:float
    default_worker_memory_bytes:int
    cooldown_seconds:float
    current:int=field(init=False)
    best:int=field(init=False)
    best_rate:float=field(default=0.0,init=False)
    previous_level:int|None=field(default=None,init=False)
    previous_rate:float|None=field(default=None,init=False)
    estimated_peak_worker_bytes:int=field(default=0,init=False)
    _epoch_started:float|None=field(default=None,init=False)
    _epoch_work_units:int=field(default=0,init=False)
    _epoch_completions:int=field(default=0,init=False)
    _cooldown_until:float=field(default=0.0,init=False)
    _stop_upward:bool=field(default=False,init=False)
    _small_gain_holds:int=field(default=0,init=False)

    def __post_init__(self)->None:
        self.maximum=max(1,int(self.maximum)); self.minimum=min(self.maximum,max(1,int(self.minimum)))
        self.step=max(1,int(self.step)); self.current=min(self.maximum,max(self.minimum,int(self.initial)))
        self.best=self.current

    def begin_wave(self,now:float)->None:
        self.current=min(self.maximum,max(self.minimum,self.best)); self.best_rate=0.0
        self.previous_level=None; self.previous_rate=None
        self._stop_upward=False; self._small_gain_holds=0; self._reset_epoch(now)

    def _reset_epoch(self,now:float)->None:
        self._epoch_started=float(now); self._epoch_work_units=0; self._epoch_completions=0

    def observe(self,*,work_units:int,peak_rss_bytes:int,now:float)->None:
        if self._epoch_started is None: self._epoch_started=float(now)
        self._epoch_work_units+=max(0,int(work_units)); self._epoch_completions+=1
        self.estimated_peak_worker_bytes=max(self.estimated_peak_worker_bytes,max(0,int(peak_rss_bytes)))

    def ready(self,now:float)->bool:
        return (self._epoch_started is not None and float(now)-self._epoch_started>=self.tuning_window_seconds
                and self._epoch_completions>=self.tuning_min_completions)

    def evaluate(self,*,available_bytes:int,reserve_bytes:int,now:float)->dict|None:
        elapsed=max(1e-9,float(now)-(self._epoch_started if self._epoch_started is not None else float(now)))
        rate=self._epoch_work_units/elapsed
        old=self.current; action="hold"; reason="insufficient_gain"
        worker_bytes=max(self.estimated_peak_worker_bytes,int(self.default_worker_memory_bytes))

        if int(available_bytes)<=int(reserve_bytes):
            self.current=max(self.minimum,self.current-self.step); self._cooldown_until=float(now)+self.cooldown_seconds
            action="decrease" if self.current<old else "hold"; reason="memory_pressure"
        elif not self.ready(now):
            return None
        elif self.previous_level is not None and self.previous_rate is not None and self.current>self.previous_level:
            if rate<self.previous_rate*(1.0-self.regression_fraction):
                self.current=self.previous_level; self.best=self.previous_level; self.best_rate=self.previous_rate
                self._stop_upward=True; action="decrease"; reason="throughput_regressed"
            elif rate>=self.previous_rate*(1.0+self.min_gain_fraction):
                self.best=self.current; self.best_rate=rate; self._small_gain_holds=0
                action,reason=self._probe(available_bytes,reserve_bytes,worker_bytes,now)
            elif rate>=self.previous_rate:
                if self._small_gain_holds==0:
                    self._small_gain_holds=1; action="hold"; reason="small_gain_remeasure"
                else:
                    self.best=self.current; self.best_rate=max(self.best_rate,rate); self._stop_upward=True
                    action="hold"; reason="small_gain_hold_best"
            else:
                self.current=self.previous_level; self.best=self.previous_level; self.best_rate=self.previous_rate
                self._stop_upward=True; action="decrease"; reason="no_throughput_gain"
        else:
            self.best=self.current; self.best_rate=max(self.best_rate,rate)
            action,reason=self._probe(available_bytes,reserve_bytes,worker_bytes,now)

        event={"action":action,"from_workers":old,"to_workers":self.current,
               "completed_tasks":self._epoch_completions,"work_units":self._epoch_work_units,
               "window_seconds":elapsed,"throughput_work_units_per_second":rate,
               "available_bytes":int(available_bytes),"reserve_bytes":int(reserve_bytes),
               "estimated_peak_worker_bytes":int(worker_bytes),"reason":reason}
        self._reset_epoch(now)
        return event

    def _probe(self,available:int,reserve:int,worker_bytes:int,now:float)->tuple[str,str]:
        if self._stop_upward: return "hold","wave_best_selected"
        if float(now)<self._cooldown_until: return "hold","memory_cooldown"
        increment=min(self.step,self.maximum-self.current)
        if increment<=0: return "hold","hard_cap"
        required=int(worker_bytes*increment*self.memory_guard_multiplier)
        if int(available)-int(reserve)<=required: return "hold","insufficient_memory_headroom"
        old=self.current; self.previous_level=old; self.previous_rate=self.best_rate
        self.current=min(self.maximum,self.current+increment)
        return "increase","throughput_improved_and_memory_safe"
