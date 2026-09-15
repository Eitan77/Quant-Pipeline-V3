import numpy as np
from .base import TargetArray
class TargetEngine:
    def __init__(self,implementations):self.implementations=implementations
    def compute(self,spec,observation_index,inputs):
        out=self.implementations[spec.implementation_id].compute(spec=spec,observation_index=observation_index,inputs=inputs)
        if len(out.values)!=len(observation_index) or len(out.valid)!=len(observation_index):raise ValueError(f"{spec.target_id}: observation alignment mismatch")
        return out

