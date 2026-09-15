class TargetRegistry:
    def __init__(self,specs):
        self._specs=tuple(specs); ids=[x.target_id for x in self._specs]
        if len(ids)!=len(set(ids)):raise ValueError("Duplicate target_id")
        for x in self._specs:
            if x.return_basis not in {"raw","benchmark_adjusted","beta_residual"}:raise ValueError(f"Invalid return basis: {x.target_id}")
    def all(self):return self._specs

