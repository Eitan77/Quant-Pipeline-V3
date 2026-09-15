from .base import validate_feature_output
class FeatureEngine:
    def __init__(self,implementations):self.implementations=implementations
    def compute(self,spec,observation_index,inputs):
        impl=self.implementations[spec.implementation_id]; values=impl.compute(spec=spec,observation_index=observation_index,inputs=inputs); validate_feature_output(spec,values,len(observation_index)); return values

