"""Streaming consumers for exact subgroup moment blocks."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def consume_block(query_state, moments, metadata):
    """Consume all populated cells before a recomputable block may be evicted.

    A query state may specify exact pair, target, group, resolution and minimum N
    filters. Without a query, this still records a complete signed sweep summary.
    """
    task = metadata["task"]
    spec = query_state.get("spec", {})
    if "resolution" in spec and int(spec["resolution"]) != task["resolution"]:
        return
    if "group_id" in spec and not task["group_start"] <= int(spec["group_id"]) < task["group_stop"]:
        return
    minimum = int(spec.get("min_n", 0))
    output = query_state.get("stream")
    sweep = output is None and not query_state.get("top_k") and not spec
    torch = getattr(moments, "torch", None) if sweep else None
    if torch is not None:
        n, sums = moments.n, moments.s
    else:
        n, sums = moments.counts_and_sums() if hasattr(moments, "counts_and_sums") else moments.numpy()[:2]
    summary = {"task_id": task["task_id"], "rows_evaluated": metadata["rows_evaluated"],
               "cells_evaluated": int(n.numel() if torch is not None else n.size),
               "populated_cells": 0 if torch is not None else int(np.count_nonzero(n)),
               "positive_cells": 0, "negative_cells": 0, "zero_cells": 0,
               "eligible_cells": 0, "max_abs_mean_bps": None}
    if sweep:
        populated=n>0
        if torch is not None:
            # Transfer five scalars, not the entire dense count/sum block.
            means=torch.where(populated,sums/n.clamp_min(1),0)
            values=torch.stack((populated.sum(),(populated&(means>0)).sum(),
                                (populated&(means<0)).sum(),(populated&(means==0)).sum(),
                                means.abs().amax())).cpu().tolist()
            summary.update(populated_cells=int(values[0]),eligible_cells=int(values[0]),
                           positive_cells=int(values[1]),negative_cells=int(values[2]),
                           zero_cells=int(values[3]),max_abs_mean_bps=values[4]*1e4 if values[0] else None)
        else:
            means=np.divide(sums,n,out=np.zeros_like(sums),where=populated)
            summary["eligible_cells"]=int(populated.sum())
            summary["positive_cells"]=int((populated&(means>0)).sum())
            summary["negative_cells"]=int((populated&(means<0)).sum())
            summary["zero_cells"]=int((populated&(means==0)).sum())
            summary["max_abs_mean_bps"]=float(np.max(np.abs(means[populated]))*1e4) if populated.any() else None
        journal=query_state.get("journal")
        if journal is not None:
            Path(journal).parent.mkdir(parents=True,exist_ok=True)
            with Path(journal).open("a",encoding="utf-8") as stream:
                stream.write(json.dumps(summary,sort_keys=True)+"\n")
        query_state["tasks_evaluated"]=query_state.get("tasks_evaluated",0)+1
        query_state["cells_evaluated"]=query_state.get("cells_evaluated",0)+summary["cells_evaluated"]
        return summary
    best = 0.0
    resolution = task["resolution"]
    for ti, target in enumerate(task["target_ids"]):
        if "target_id" in spec and spec["target_id"] != target:
            continue
        for pi, pair in enumerate(task["pair_ids"]):
            if "pair_id" in spec and spec["pair_id"] != pair:
                continue
            for gi in range(n.shape[2]):
                group_id = task["group_start"] + gi
                if "group_id" in spec and group_id != int(spec["group_id"]):
                    continue
                ns = n[ti, pi, gi]
                ss = sums[ti, pi, gi]
                total_n = int(ns.sum())
                if total_n == 0:
                    continue
                baseline = float(ss.sum() / total_n)
                if task["state_kind"] == "dual":
                    rn = ns.reshape(resolution, resolution).sum(axis=1)
                    rs = ss.reshape(resolution, resolution).sum(axis=1)
                    cn = ns.reshape(resolution, resolution).sum(axis=0)
                    cs = ss.reshape(resolution, resolution).sum(axis=0)
                for cell, count in enumerate(ns):
                    if count < minimum or count == 0:
                        continue
                    mean = float(ss[cell] / count)
                    summary["eligible_cells"] += 1
                    summary["positive_cells" if mean > 0 else "negative_cells" if mean < 0 else "zero_cells"] += 1
                    best = max(best, abs(mean) * 1e4)
                    if output is not None:
                        row = {"pair_id": pair, "target_id": target, "resolution": resolution,
                               "group_id": group_id, "cell_index": cell, "n": int(count),
                               "sum_y": float(ss[cell]), "raw_mean_bps": mean * 1e4,
                               "frequency": float(count / total_n), "baseline_bps": baseline * 1e4}
                        if task["state_kind"] == "dual":
                            a, b = divmod(cell, resolution)
                            row["interaction_lift_bps"] = 1e4 * (mean - rs[a]/rn[a] - cs[b]/cn[b] + baseline)
                        output.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                    elif query_state.get("top_k"):
                        row = {"pair_id": pair, "target_id": target, "resolution": resolution,
                               "group_id": group_id, "cell_index": cell, "n": int(count),
                               "sum_y": float(ss[cell]), "raw_mean_bps": mean * 1e4,
                               "frequency": float(count / total_n), "baseline_bps": baseline * 1e4}
                        if task["state_kind"] == "dual":
                            a, b = divmod(cell, resolution)
                            row["interaction_lift_bps"] = 1e4 * (mean - rs[a]/rn[a] - cs[b]/cn[b] + baseline)
                        top = query_state.setdefault("top", [])
                        top.append(row)
                        if len(top) > 2 * query_state["top_k"]:
                            top.sort(key=lambda item: (-abs(item["raw_mean_bps"]), item["pair_id"],
                                                       item["target_id"], item["resolution"], item["group_id"], item["cell_index"]))
                            del top[query_state["top_k"]:]
    summary["max_abs_mean_bps"] = best if summary["eligible_cells"] else None
    journal = query_state.get("journal")
    if journal is not None:
        Path(journal).parent.mkdir(parents=True, exist_ok=True)
        with Path(journal).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(summary, sort_keys=True) + "\n")
    query_state["tasks_evaluated"] = query_state.get("tasks_evaluated", 0) + 1
    query_state["cells_evaluated"] = query_state.get("cells_evaluated", 0) + summary["cells_evaluated"]
    return summary
