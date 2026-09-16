from __future__ import annotations

import numpy as np


def event_path_metrics(rows: list[dict]) -> dict:
    values=np.asarray([row.get("direction_aligned_mean_bps",np.nan) for row in rows],float)
    finite=np.flatnonzero(np.isfinite(values))
    if not len(finite) or np.nanmax(values)<=0:
        return {"path_status":"no_favorable_peak","time_to_25pct":None,"time_to_50pct":None,
                "time_to_75pct":None,"time_to_peak":None,"peak_bps":None,"terminal_bps":float(values[finite[-1]]) if len(finite) else None,
                "post_peak_giveback_bps":None}
    peak_i=int(np.nanargmax(values)); peak=float(values[peak_i])
    result={"path_status":"favorable_peak","time_to_peak":rows[peak_i]["horizon"],"peak_bps":peak,
            "terminal_bps":float(values[finite[-1]]),"post_peak_giveback_bps":peak-float(values[finite[-1]])}
    for fraction,label in ((.25,"time_to_25pct"),(.5,"time_to_50pct"),(.75,"time_to_75pct")):
        hit=next((rows[i]["horizon"] for i in finite if values[i]>=fraction*peak),None); result[label]=hit
    return result


def direction_aware_excursions(frame,direction:int):
    result=frame.copy()
    if direction>=0:
        result["directional_mfe"]=result["mfe"]; result["directional_mae"]=result["mae"]
        result["time_to_directional_mfe"]=result["time_to_mfe"]; result["time_to_directional_mae"]=result["time_to_mae"]
    else:
        result["directional_mfe"]=-result["mae"]; result["directional_mae"]=-result["mfe"]
        result["time_to_directional_mfe"]=result["time_to_mae"]; result["time_to_directional_mae"]=result["time_to_mfe"]
    result["directional_terminal_return"]=direction*result["terminal_return"]
    return result
