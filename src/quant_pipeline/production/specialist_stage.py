from __future__ import annotations
from pathlib import Path
import numpy as np,pandas as pd
from quant_pipeline.discovery.specialist import specialist_probe
from quant_pipeline.production.outputs import ProductionData
from quant_pipeline.production.zoom_requests import state_key

def run_production_specialist_probe(*,legacy_run,duals:pd.DataFrame,research:dict)->Path:
    minimum=int(research.get("specialist",{}).get("min_local_n",20)); minimum_state=int(research.get("specialist",{}).get("min_selected_n",20)); data=ProductionData(legacy_run); rows=[]
    guaranteed=duals.get("guaranteed_explicit",pd.Series(False,index=duals.index)).fillna(False).astype(bool); selected=duals[duals.selected_n.ge(minimum_state)|guaranteed].copy()
    if "state_key" not in selected:selected["state_key"]=[state_key(x) for x in selected.to_dict("records")] if len(selected) else pd.Series(dtype=str)
    for row in selected.drop_duplicates("state_key").to_dict("records"):
        _,obs,_,_,y,mask,_,_=data.selected(row); probe=specialist_probe(security_id=obs.security_id.to_numpy(),active=mask,returns_bps=y*10_000.0,min_local_n=minimum); positive=probe.get("fraction_positive") or 0.0; negative=probe.get("fraction_negative") or 0.0; global_bps=float(row["selected_state_bps"]); local_sign=1 if positive>negative else -1 if negative>positive else 0; disagreement=float(local_sign!=0 and np.sign(global_bps)!=local_sign)
        rows.append({"state_key":row["state_key"],"pair_id":row["pair_id"],"feature_a":row["feature_a"],"feature_b":row["feature_b"],"target_id":row["target_id"],"resolution":int(row["v3_resolution"]),"selected_cell":int(row["selected_cell"]),"specialist_min_local_n":minimum,"global_effect_bps":global_bps,"global_vs_local_disagreement":disagreement,**probe})
    columns=["state_key","pair_id","feature_a","feature_b","target_id","resolution","selected_cell","specialist_min_local_n","symbols_active","symbols_eligible","fraction_positive","fraction_negative","effect_dispersion_bps","top_symbol_share","top5_symbol_share","global_effect_bps","global_vs_local_disagreement","min_local_active_n","median_local_active_n","max_local_active_n"]
    destination=legacy_run.root/"specialist_summary.parquet"; pd.DataFrame(rows,columns=columns).to_parquet(destination,index=False); return destination
