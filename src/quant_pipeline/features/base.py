import numpy as np
def validate_feature_output(spec,values,n_obs):
    values=np.asarray(values)
    if values.ndim!=1:raise ValueError(f"{spec.feature_id}: output must be 1-D")
    if len(values)!=n_obs:raise ValueError(f"{spec.feature_id}: length mismatch")
    if str(values.dtype)!=spec.output_dtype:raise TypeError(f"{spec.feature_id}: expected {spec.output_dtype}, got {values.dtype}")

