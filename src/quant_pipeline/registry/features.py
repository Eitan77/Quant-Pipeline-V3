from quant_pipeline.hashing import content_hash
class FeatureRegistry:
    def __init__(self,specs):
        self._specs=tuple(specs); ids=[x.feature_id for x in self._specs]
        if len(ids)!=len(set(ids)):raise ValueError("Duplicate feature_id")
        for x in self._specs:
            if not x.availability_rule or not x.price_basis or not x.concept_id:raise ValueError(f"Incomplete causal feature metadata: {x.feature_id}")
    def all(self):return self._specs
    def canonical(self):return tuple(x for x in self._specs if x.canonical)

