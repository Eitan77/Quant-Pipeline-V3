from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import heapq
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

REPO = os.environ.get("GITHUB_REPOSITORY", "Eitan77/Quant-Pipeline-V3")
TAG = "v3-discovery"
ROOT = Path.cwd()
DATA = ROOT / "_v3_release"
OUT = ROOT / "_v3_analysis"
DATA.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

RNG = np.random.default_rng(20260920)
SAMPLE_P = 0.002
TOP_K = 350

def sh(cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True)

def download_assets():
    pats = [
        "bundle_manifest.json", "manifest.json", "EVIDENCE_COMPLETE.json",
        "exhaustiveness_manifest.json", "STATUS.json", "source_manifest.json",
        "feature_registry.parquet", "target_registry.parquet", "single_summary.parquet",
        "dual_summary_*.parquet", "specialist_*.parquet", "temporal_*.parquet",
        "trial_ledger.parquet", "resolution_comparison.parquet", "edge_families.parquet",
        "edge_registry.parquet", "candidate_summary.parquet", "variant_summary.parquet",
        "chronological_diagnostics.parquet", "crossfit_diagnostics.parquet",
        "time_of_day.parquet", "coverage.parquet", "regime_breakdown.parquet",
        "tail_ladder.parquet", "horizon_ladder.parquet", "data_dictionary.md",
    ]
    cmd = ["gh", "release", "download", TAG, "--repo", REPO, "--dir", str(DATA), "--clobber"]
    for p in pats:
        cmd += ["--pattern", p]
    sh(cmd)

def jload(name):
    p = DATA / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_parse_error": str(e)}

def parquet_schema(files):
    out = {}
    for f in files:
        try:
            s = pq.ParquetFile(f).schema_arrow
            out[f.name] = [{"name": x.name, "type": str(x.type)} for x in s]
        except Exception as e:
            out[f.name] = [{"error": str(e)}]
    return out

def n_bucket(n):
    n = np.asarray(n)
    out = np.full(n.shape, "0", dtype=object)
    out[n < 20] = "<20"
    out[(n >= 20) & (n < 100)] = "20-99"
    out[(n >= 100) & (n < 250)] = "100-249"
    out[(n >= 250) & (n < 1000)] = "250-999"
    out[(n >= 1000) & (n < 5000)] = "1000-4999"
    out[n >= 5000] = "5000+"
    return out

class StreamStats:
    def __init__(self):
        self.d = defaultdict(lambda: {
            "count": 0, "finite": 0, "positive": 0, "negative": 0,
            "sum": 0.0, "sumsq": 0.0, "sample": []
        })

    def add(self, key, values):
        v = np.asarray(values, dtype=float)
        st = self.d[key]
        st["count"] += int(v.size)
        f = v[np.isfinite(v)]
        st["finite"] += int(f.size)
        if not f.size:
            return
        st["positive"] += int((f > 0).sum())
        st["negative"] += int((f < 0).sum())
        st["sum"] += float(f.sum())
        st["sumsq"] += float(np.square(f).sum())
        mask = RNG.random(f.size) < SAMPLE_P
        if mask.any():
            st["sample"].extend(f[mask].astype(float).tolist())
            if len(st["sample"]) > 60000:
                idx = RNG.choice(len(st["sample"]), size=50000, replace=False)
                arr = np.asarray(st["sample"], dtype=float)[idx]
                st["sample"] = arr.tolist()

    def export(self):
        result = {}
        for key, st in self.d.items():
            f = st["finite"]
            mean = st["sum"] / f if f else None
            var = (st["sumsq"] / f - mean * mean) if f else None
            sample = np.asarray(st["sample"], dtype=float)
            qs = {}
            if sample.size:
                for q in [0.01,0.05,0.10,0.25,0.50,0.75,0.90,0.95,0.99]:
                    qs[str(q)] = float(np.quantile(sample, q))
            result[str(key)] = {
                "count": st["count"], "finite": f,
                "positive": st["positive"], "negative": st["negative"],
                "mean": mean, "std": math.sqrt(max(var,0)) if var is not None else None,
                "sample_n_for_quantiles": int(sample.size), "quantiles": qs,
            }
        return result

class TopStore:
    def __init__(self, k=TOP_K):
        self.k = k
        self.heaps = defaultdict(list)
        self.counter = 0

    def push_many(self, name, scores, mask, record_fn, local_keep=80):
        s = np.asarray(scores, dtype=float).ravel()
        m = np.asarray(mask, dtype=bool).ravel() & np.isfinite(s)
        idx = np.flatnonzero(m)
        if not idx.size:
            return
        if idx.size > local_keep:
            vals = s[idx]
            pick = np.argpartition(vals, -local_keep)[-local_keep:]
            idx = idx[pick]
        for j in idx:
            score = float(s[j])
            rec = record_fn(int(j))
            self.counter += 1
            item = (score, self.counter, rec)
            h = self.heaps[name]
            if len(h) < self.k:
                heapq.heappush(h, item)
            elif score > h[0][0]:
                heapq.heapreplace(h, item)

    def export(self):
        rows = []
        for name, h in self.heaps.items():
            for score, _, rec in sorted(h, reverse=True):
                rows.append({"criterion": name, "criterion_score": score, **rec})
        return rows

def family(name):
    s = str(name)
    return s.split("__", 1)[0] if "__" in s else s

def horizon(target):
    s = str(target).lower()
    m = re.search(r"(?:target_)?(\d+)(m|h)", s)
    if m:
        n = int(m.group(1))
        return f"{n}{m.group(2)}"
    if "eod" in s:
        return "EOD"
    return "unknown"

def target_kind(target):
    s = str(target).lower()
    for x in ["beta_residual", "benchmark_adjusted", "residual", "raw"]:
        if x in s:
            return x
    return "other"

def take_list(arr, row_idx):
    return pc.take(arr, pa.array(row_idx, type=pa.int64()))

def flatten_matrix(list_arr, row_idx, cells, dtype=float):
    sub = take_list(list_arr, row_idx)
    flat = pc.list_flatten(sub).to_numpy(zero_copy_only=False)
    return np.asarray(flat, dtype=dtype).reshape(len(row_idx), cells)

def col_numpy(batch, name, default=np.nan, dtype=float):
    if name not in batch.schema.names:
        return np.full(batch.num_rows, default, dtype=dtype)
    a = batch.column(batch.schema.get_field_index(name))
    try:
        return np.asarray(a.to_numpy(zero_copy_only=False), dtype=dtype)
    except Exception:
        return np.asarray(a.to_pylist(), dtype=dtype)

def col_py(batch, name, default=""):
    if name not in batch.schema.names:
        return [default] * batch.num_rows
    return batch.column(batch.schema.get_field_index(name)).to_pylist()

def write_surface_batch(writer, batch):
    names = batch.schema.names
    d = {
        "pair_id": col_py(batch, "pair_id"),
        "feature_a": col_py(batch, "feature_a"),
        "feature_b": col_py(batch, "feature_b"),
        "target_id": col_py(batch, "target_id"),
        "resolution": col_numpy(batch, "v3_resolution", default=-1, dtype=np.int16),
        "selected_cell": col_numpy(batch, "selected_cell", default=-1, dtype=np.int32),
        "selected_n": col_numpy(batch, "selected_n"),
        "selected_frequency": col_numpy(batch, "selected_frequency"),
        "selected_state_bps": col_numpy(batch, "selected_state_bps"),
        "selected_interaction_lift_bps": col_numpy(batch, "selected_interaction_lift_bps"),
        "weighted_state_contribution_bps": col_numpy(batch, "weighted_state_contribution_bps"),
        "neighbor_effect_retention": col_numpy(batch, "neighbor_effect_retention"),
        "plateau_area": col_numpy(batch, "plateau_area"),
        "surface_spread_bps": col_numpy(batch, "surface_spread_bps"),
    }
    d["family_a"] = [family(x) for x in d["feature_a"]]
    d["family_b"] = [family(x) for x in d["feature_b"]]
    d["horizon"] = [horizon(x) for x in d["target_id"]]
    d["target_kind"] = [target_kind(x) for x in d["target_id"]]
    table = pa.Table.from_pydict(d)
    if writer[0] is None:
        writer[0] = pq.ParquetWriter(OUT / "surface_compact.parquet", table.schema, compression="zstd")
    writer[0].write_table(table)

def analyze_dual(files):
    stats_raw = StreamStats()
    stats_inter = StreamStats()
    stats_freq = StreamStats()
    stats_se = StreamStats()
    top = TopStore()
    writer = [None]
    total_surfaces = 0
    total_cells = 0

    for f in files:
        pf = pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=12000):
            total_surfaces += batch.num_rows
            write_surface_batch(writer, batch)
            res_all = col_numpy(batch, "v3_resolution", dtype=np.int16)
            pair_all = col_py(batch, "pair_id")
            fa_all = col_py(batch, "feature_a")
            fb_all = col_py(batch, "feature_b")
            tgt_all = col_py(batch, "target_id")
            counts_arr = batch.column(batch.schema.get_field_index("surface_counts"))
            sums_arr = batch.column(batch.schema.get_field_index("surface_sums"))
            sumsq_arr = batch.column(batch.schema.get_field_index("surface_sumsq"))

            for r in sorted(set(int(x) for x in res_all)):
                idx = np.flatnonzero(res_all == r)
                if not idx.size:
                    continue
                cells = r * r
                counts = flatten_matrix(counts_arr, idx, cells, float)
                sums = flatten_matrix(sums_arr, idx, cells, float)
                sumsq = flatten_matrix(sumsq_arr, idx, cells, float)
                total_cells += int(counts.size)
                with np.errstate(divide="ignore", invalid="ignore"):
                    raw = 10000.0 * sums / counts
                    total_n = counts.sum(axis=1)
                    freq = counts / total_n[:, None]
                    var = (sumsq - sums * sums / counts) / (counts - 1)
                    var = np.maximum(var, 0)
                    se = 10000.0 * np.sqrt(var / counts)
                    cell_mean = sums / counts
                    row_counts = counts.reshape(-1, r, r).sum(axis=2)
                    row_sums = sums.reshape(-1, r, r).sum(axis=2)
                    col_counts = counts.reshape(-1, r, r).sum(axis=1)
                    col_sums = sums.reshape(-1, r, r).sum(axis=1)
                    row_mean = row_sums / row_counts
                    col_mean = col_sums / col_counts
                    overall = sums.sum(axis=1) / total_n
                    inter = 10000.0 * (
                        cell_mean.reshape(-1, r, r)
                        - row_mean[:, :, None]
                        - col_mean[:, None, :]
                        + overall[:, None, None]
                    ).reshape(-1, cells)
                    weighted = raw * freq
                    z = np.abs(raw) / se

                nb = n_bucket(counts)
                for b in ["<20","20-99","100-249","250-999","1000-4999","5000+"]:
                    m = nb == b
                    if m.any():
                        stats_raw.add((r,b), raw[m])
                        stats_inter.add((r,b), inter[m])
                        stats_freq.add((r,b), freq[m])
                        stats_se.add((r,b), se[m])

                pair = [pair_all[i] for i in idx]
                fa = [fa_all[i] for i in idx]
                fb = [fb_all[i] for i in idx]
                tgt = [tgt_all[i] for i in idx]

                def rec_fn(j):
                    rr = j // cells
                    cc = j % cells
                    return {
                        "pair_id": pair[rr], "feature_a": fa[rr], "feature_b": fb[rr],
                        "target_id": tgt[rr], "resolution": r, "cell_index": cc,
                        "active_n": float(counts[rr,cc]), "raw_edge_bps": float(raw[rr,cc]),
                        "frequency": float(freq[rr,cc]), "se_bps": float(se[rr,cc]),
                        "interaction_lift_bps": float(inter[rr,cc]),
                        "weighted_contribution_bps": float(weighted[rr,cc]),
                    }

                for threshold in [20,250,1000]:
                    m = counts >= threshold
                    top.push_many(f"raw_positive_n{threshold}_r{r}", raw, m, rec_fn)
                    top.push_many(f"raw_negative_n{threshold}_r{r}", -raw, m, rec_fn)
                    top.push_many(f"abs_raw_n{threshold}_r{r}", np.abs(raw), m, rec_fn)
                    top.push_many(f"abs_interaction_n{threshold}_r{r}", np.abs(inter), m, rec_fn)
                m250 = counts >= 250
                top.push_many(f"abs_weighted_n250_r{r}", np.abs(weighted), m250, rec_fn)
                top.push_many(f"abs_z_n250_r{r}", z, m250 & (np.abs(raw) >= 0.25), rec_fn)
                top.push_many(f"largeN_edge_r{r}", np.abs(raw)*np.sqrt(np.maximum(counts,0)), counts>=5000, rec_fn)

    if writer[0] is not None:
        writer[0].close()

    tops = top.export()
    pd.DataFrame(tops).to_csv(OUT / "dual_top_cells.csv", index=False)
    return {
        "surface_rows": total_surfaces, "expanded_cell_count": total_cells,
        "raw_background": stats_raw.export(),
        "interaction_background": stats_inter.export(),
        "frequency_background": stats_freq.export(),
        "se_background": stats_se.export(),
        "top_record_count": len(tops),
    }

def specialist_records(files):
    stats = {k: StreamStats() for k in [
        "cancellation_score","symbol_effect_dispersion_bps","positive_symbol_fraction",
        "negative_symbol_fraction","top_symbol_contribution_share","top5_symbol_contribution_share",
        "eligible_symbol_count"
    ]}
    top = TopStore()
    rows_seen = 0
    cells_seen = 0
    for f in files:
        pf = pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=14000):
            rows_seen += batch.num_rows
            res_all = col_numpy(batch, "resolution", dtype=np.int16)
            pair_all = col_py(batch, "pair_id")
            tgt_all = col_py(batch, "target_id")
            for r in sorted(set(int(x) for x in res_all)):
                idx = np.flatnonzero(res_all == r)
                if not idx.size: continue
                c = r*r
                arrays = {}
                for name in stats:
                    arrays[name] = flatten_matrix(batch.column(batch.schema.get_field_index(name)), idx, c, float)
                    stats[name].add(r, arrays[name].ravel())
                cells_seen += int(idx.size*c)
                elig = arrays["eligible_symbol_count"]
                pos = arrays["positive_symbol_fraction"]
                neg = arrays["negative_symbol_fraction"]
                disp = arrays["symbol_effect_dispersion_bps"]
                cancel = arrays["cancellation_score"]
                top1 = arrays["top_symbol_contribution_share"]
                balance = 2*np.minimum(pos,neg)
                cancellation_structure = disp * balance
                pair = [pair_all[i] for i in idx]
                tgt = [tgt_all[i] for i in idx]
                def rec(j):
                    rr=j//c; cc=j%c
                    return {
                        "pair_id":pair[rr],"target_id":tgt[rr],"resolution":r,"cell_index":cc,
                        "eligible_symbol_count":float(elig[rr,cc]),
                        "positive_symbol_fraction":float(pos[rr,cc]),
                        "negative_symbol_fraction":float(neg[rr,cc]),
                        "symbol_effect_dispersion_bps":float(disp[rr,cc]),
                        "cancellation_score":float(cancel[rr,cc]),
                        "top_symbol_contribution_share":float(top1[rr,cc]),
                        "top5_symbol_contribution_share":float(arrays["top5_symbol_contribution_share"][rr,cc]),
                        "best_positive_local_bps":float(flatten_matrix(batch.column(batch.schema.get_field_index("best_positive_local_bps")), idx, c, float)[rr,cc]) if "best_positive_local_bps" in batch.schema.names else np.nan,
                        "best_negative_local_bps":float(flatten_matrix(batch.column(batch.schema.get_field_index("best_negative_local_bps")), idx, c, float)[rr,cc]) if "best_negative_local_bps" in batch.schema.names else np.nan,
                    }
                mask = elig >= 10
                top.push_many(f"cancellation_r{r}", cancel, mask & np.isfinite(cancel), rec)
                top.push_many(f"balanced_dispersion_r{r}", cancellation_structure, mask & np.isfinite(cancellation_structure), rec)
                top.push_many(f"symbol_dispersion_r{r}", disp, mask & np.isfinite(disp), rec)
                top.push_many(f"symbol_concentration_r{r}", top1, mask & np.isfinite(top1), rec)
                sign_cons = np.maximum(pos,neg)
                top.push_many(f"symbol_sign_consistency_r{r}", sign_cons, mask & np.isfinite(sign_cons), rec)
    tops=top.export()
    pd.DataFrame(tops).to_csv(OUT/"specialist_top_cells.csv",index=False)
    return {
        "surface_rows":rows_seen,"expanded_cell_count":cells_seen,
        "background":{k:v.export() for k,v in stats.items()},
        "top_record_count":len(tops)
    }

def temporal_records(files):
    names=["fold_positive_fraction","fold_negative_fraction","worst_fold_bps","best_fold_bps",
           "median_fold_bps","fold_dispersion_bps","minimum_fold_n"]
    stats={k:StreamStats() for k in names}
    top=TopStore()
    rows_seen=0; cells_seen=0
    for f in files:
        pf=pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=14000):
            rows_seen+=batch.num_rows
            res_all=col_numpy(batch,"resolution",dtype=np.int16)
            pair_all=col_py(batch,"pair_id"); tgt_all=col_py(batch,"target_id")
            for r in sorted(set(int(x) for x in res_all)):
                idx=np.flatnonzero(res_all==r)
                if not idx.size:continue
                c=r*r
                arrays={}
                for name in names:
                    arrays[name]=flatten_matrix(batch.column(batch.schema.get_field_index(name)),idx,c,float)
                    stats[name].add(r,arrays[name].ravel())
                cells_seen+=int(idx.size*c)
                pos=arrays["fold_positive_fraction"]; neg=arrays["fold_negative_fraction"]
                med=arrays["median_fold_bps"]; disp=arrays["fold_dispersion_bps"]
                min_n=arrays["minimum_fold_n"]; worst=arrays["worst_fold_bps"]; best=arrays["best_fold_bps"]
                sign_cons=np.maximum(pos,neg)
                pair=[pair_all[i] for i in idx]; tgt=[tgt_all[i] for i in idx]
                def rec(j):
                    rr=j//c; cc=j%c
                    return {
                        "pair_id":pair[rr],"target_id":tgt[rr],"resolution":r,"cell_index":cc,
                        "fold_positive_fraction":float(pos[rr,cc]),"fold_negative_fraction":float(neg[rr,cc]),
                        "worst_fold_bps":float(worst[rr,cc]),"best_fold_bps":float(best[rr,cc]),
                        "median_fold_bps":float(med[rr,cc]),"fold_dispersion_bps":float(disp[rr,cc]),
                        "minimum_fold_n":float(min_n[rr,cc]),"fold_sign_consistency":float(sign_cons[rr,cc]),
                    }
                mask=min_n>=20
                top.push_many(f"stable_median_r{r}",np.abs(med)*sign_cons,mask & (sign_cons>=0.8),rec)
                top.push_many(f"allfold_median_r{r}",np.abs(med),mask & (sign_cons>=0.999),rec)
                top.push_many(f"temporal_dispersion_r{r}",disp,mask & np.isfinite(disp),rec)
                flip=np.minimum(np.maximum(best,0),np.maximum(-worst,0))
                top.push_many(f"strong_sign_flip_r{r}",flip,mask & (best>0) & (worst<0),rec)
    tops=top.export()
    pd.DataFrame(tops).to_csv(OUT/"temporal_top_cells.csv",index=False)
    return {
        "surface_rows":rows_seen,"expanded_cell_count":cells_seen,
        "background":{k:v.export() for k,v in stats.items()},
        "top_record_count":len(tops)
    }

def lookup_union(dual_files,specialist_files,temporal_files):
    frames=[]
    for name in ["dual_top_cells.csv","specialist_top_cells.csv","temporal_top_cells.csv"]:
        p=OUT/name
        if p.exists() and p.stat().st_size:
            df=pd.read_csv(p)
            frames.append(df[["pair_id","target_id","resolution","cell_index"]])
    if not frames:
        return pd.DataFrame()
    keys=pd.concat(frames,ignore_index=True).drop_duplicates()
    wanted=defaultdict(set)
    for row in keys.itertuples(index=False):
        wanted[(str(row.pair_id),str(row.target_id),int(row.resolution))].add(int(row.cell_index))

    records={}

    def ensure(k):
        if k not in records:
            records[k]={"pair_id":k[0],"target_id":k[1],"resolution":k[2],"cell_index":k[3]}
        return records[k]

    # dual enrichment
    for f in dual_files:
        pf=pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=12000):
            pairs=col_py(batch,"pair_id"); tgts=col_py(batch,"target_id")
            ress=col_numpy(batch,"v3_resolution",dtype=np.int16)
            fas=col_py(batch,"feature_a"); fbs=col_py(batch,"feature_b")
            counts_arr=batch.column(batch.schema.get_field_index("surface_counts"))
            sums_arr=batch.column(batch.schema.get_field_index("surface_sums"))
            ss_arr=batch.column(batch.schema.get_field_index("surface_sumsq"))
            for i,(p,t,r) in enumerate(zip(pairs,tgts,ress)):
                base=(str(p),str(t),int(r))
                cells=wanted.get(base)
                if not cells: continue
                n=np.asarray(counts_arr[i].as_py(),dtype=float)
                s=np.asarray(sums_arr[i].as_py(),dtype=float)
                ss=np.asarray(ss_arr[i].as_py(),dtype=float)
                rr=int(r); c=rr*rr
                with np.errstate(divide="ignore",invalid="ignore"):
                    raw=10000*s/n; total_n=n.sum(); freq=n/total_n
                    var=np.maximum((ss-s*s/n)/(n-1),0); se=10000*np.sqrt(var/n)
                    means=s/n
                    rc=n.reshape(rr,rr).sum(1); rs=s.reshape(rr,rr).sum(1)
                    cc=n.reshape(rr,rr).sum(0); cs=s.reshape(rr,rr).sum(0)
                    inter=10000*(means.reshape(rr,rr)-(rs/rc)[:,None]-(cs/cc)[None,:]+s.sum()/total_n).ravel()
                for ci in cells:
                    if ci>=c:continue
                    k=(base[0],base[1],base[2],ci); rec=ensure(k)
                    rec.update({
                        "feature_a":fas[i],"feature_b":fbs[i],
                        "family_a":family(fas[i]),"family_b":family(fbs[i]),
                        "horizon":horizon(t),"target_kind":target_kind(t),
                        "active_n":float(n[ci]),"raw_edge_bps":float(raw[ci]),
                        "frequency":float(freq[ci]),"se_bps":float(se[ci]),
                        "interaction_lift_bps":float(inter[ci]),
                        "weighted_contribution_bps":float(raw[ci]*freq[ci]),
                    })

    # specialist enrichment
    snames=["eligible_symbol_count","positive_symbol_fraction","negative_symbol_fraction",
            "symbol_effect_dispersion_bps","best_positive_local_bps","best_negative_local_bps",
            "top_symbol_contribution_share","top5_symbol_contribution_share","cancellation_score"]
    for f in specialist_files:
        pf=pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=14000):
            pairs=col_py(batch,"pair_id"); tgts=col_py(batch,"target_id")
            ress=col_numpy(batch,"resolution",dtype=np.int16)
            for i,(p,t,r) in enumerate(zip(pairs,tgts,ress)):
                base=(str(p),str(t),int(r)); cells=wanted.get(base)
                if not cells: continue
                vals={name:batch.column(batch.schema.get_field_index(name))[i].as_py() for name in snames if name in batch.schema.names}
                for ci in cells:
                    k=(base[0],base[1],base[2],ci); rec=ensure(k)
                    for name,v in vals.items():
                        if ci<len(v): rec[name]=v[ci]

    # temporal enrichment
    tnames=["fold_positive_fraction","fold_negative_fraction","worst_fold_bps","best_fold_bps",
            "median_fold_bps","fold_dispersion_bps","minimum_fold_n"]
    for f in temporal_files:
        pf=pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=14000):
            pairs=col_py(batch,"pair_id"); tgts=col_py(batch,"target_id")
            ress=col_numpy(batch,"resolution",dtype=np.int16)
            for i,(p,t,r) in enumerate(zip(pairs,tgts,ress)):
                base=(str(p),str(t),int(r)); cells=wanted.get(base)
                if not cells: continue
                vals={name:batch.column(batch.schema.get_field_index(name))[i].as_py() for name in tnames if name in batch.schema.names}
                for ci in cells:
                    k=(base[0],base[1],base[2],ci); rec=ensure(k)
                    for name,v in vals.items():
                        if ci<len(v): rec[name]=v[ci]
                    if "fold_positive_fraction" in rec and "fold_negative_fraction" in rec:
                        rec["fold_sign_consistency"]=max(rec["fold_positive_fraction"],rec["fold_negative_fraction"])
    df=pd.DataFrame(records.values())
    if not df.empty:
        df.to_csv(OUT/"top_cells_enriched.csv",index=False)
        df.to_parquet(OUT/"top_cells_enriched.parquet",index=False)
    return df

def run_query(con, sql):
    try:
        return con.execute(sql).fetchdf().replace({np.nan:None}).to_dict("records")
    except Exception as e:
        return [{"_error":str(e),"_sql":sql}]

def surface_analysis():
    p=OUT/"surface_compact.parquet"
    con=duckdb.connect()
    con.execute("SET memory_limit='3GB'")
    res={}
    res["by_resolution"]=run_query(con, f"""
        SELECT resolution, count(*) surfaces,
          approx_quantile(abs(selected_state_bps),[0.5,0.9,0.95,0.99]) abs_edge_q,
          approx_quantile(selected_n,[0.1,0.5,0.9,0.99]) n_q,
          approx_quantile(selected_frequency,[0.1,0.5,0.9,0.99]) freq_q,
          approx_quantile(abs(selected_interaction_lift_bps),[0.5,0.9,0.95,0.99]) abs_inter_q,
          avg(CASE WHEN selected_state_bps>0 THEN 1 ELSE 0 END) positive_frac,
          avg(CASE WHEN selected_state_bps<0 THEN 1 ELSE 0 END) negative_frac
        FROM read_parquet('{p}') GROUP BY 1 ORDER BY 1
    """)
    res["plateau_background"]=run_query(con, f"""
        SELECT resolution,
          approx_quantile(neighbor_effect_retention,[0.1,0.5,0.9,0.99]) neighbor_retention_q,
          approx_quantile(plateau_area,[0.1,0.5,0.9,0.99]) plateau_area_q,
          corr(abs(selected_state_bps),neighbor_effect_retention) edge_neighbor_corr
        FROM read_parquet('{p}') GROUP BY 1 ORDER BY 1
    """)
    res["target_horizon"]=run_query(con, f"""
        SELECT horizon,target_kind,count(*) surfaces,
          approx_quantile(abs(selected_state_bps),0.5) med_abs_edge,
          approx_quantile(abs(selected_state_bps),0.95) p95_abs_edge,
          avg(abs(selected_state_bps)>=2) frac_abs2,
          avg(selected_state_bps>0) positive_frac
        FROM read_parquet('{p}')
        GROUP BY 1,2 HAVING count(*)>=100 ORDER BY frac_abs2 DESC, surfaces DESC LIMIT 100
    """)
    res["family_pairs"]=run_query(con, f"""
        SELECT least(family_a,family_b) family_1,greatest(family_a,family_b) family_2,count(*) surfaces,
          approx_quantile(abs(selected_state_bps),0.5) med_abs_edge,
          approx_quantile(abs(selected_state_bps),0.95) p95_abs_edge,
          approx_quantile(abs(selected_interaction_lift_bps),0.95) p95_abs_inter,
          avg(abs(selected_state_bps)>=2) frac_abs2,
          avg(abs(selected_interaction_lift_bps)>=2) frac_inter2
        FROM read_parquet('{p}')
        GROUP BY 1,2 HAVING count(*)>=100
        ORDER BY frac_inter2 DESC, frac_abs2 DESC LIMIT 150
    """)
    res["broad_plateaus"]=run_query(con, f"""
        SELECT pair_id,feature_a,feature_b,target_id,resolution,selected_state_bps,selected_n,
               selected_frequency,selected_interaction_lift_bps,neighbor_effect_retention,plateau_area
        FROM read_parquet('{p}')
        WHERE selected_n>=250 AND abs(selected_state_bps)>=1
        ORDER BY coalesce(neighbor_effect_retention,0) DESC, coalesce(plateau_area,0) DESC,
                 abs(selected_state_bps) DESC LIMIT 500
    """)
    res["isolated_spikes"]=run_query(con, f"""
        SELECT pair_id,feature_a,feature_b,target_id,resolution,selected_state_bps,selected_n,
               selected_frequency,selected_interaction_lift_bps,neighbor_effect_retention,plateau_area
        FROM read_parquet('{p}')
        WHERE selected_n>=250 AND abs(selected_state_bps)>=2
          AND (coalesce(plateau_area,1)<=1 OR coalesce(neighbor_effect_retention,0)<0.2)
        ORDER BY abs(selected_state_bps) DESC LIMIT 500
    """)
    cross_sql=f"""
      WITH x AS (
        SELECT pair_id,target_id,any_value(feature_a) feature_a,any_value(feature_b) feature_b,
          max(CASE WHEN resolution=3 THEN selected_state_bps END) r3_edge,
          max(CASE WHEN resolution=5 THEN selected_state_bps END) r5_edge,
          max(CASE WHEN resolution=10 THEN selected_state_bps END) r10_edge,
          max(CASE WHEN resolution=3 THEN selected_interaction_lift_bps END) r3_inter,
          max(CASE WHEN resolution=5 THEN selected_interaction_lift_bps END) r5_inter,
          max(CASE WHEN resolution=10 THEN selected_interaction_lift_bps END) r10_inter,
          max(CASE WHEN resolution=3 THEN selected_n END) r3_n,
          max(CASE WHEN resolution=5 THEN selected_n END) r5_n,
          max(CASE WHEN resolution=10 THEN selected_n END) r10_n,
          max(CASE WHEN resolution=3 THEN neighbor_effect_retention END) r3_neighbor,
          max(CASE WHEN resolution=5 THEN neighbor_effect_retention END) r5_neighbor,
          max(CASE WHEN resolution=10 THEN neighbor_effect_retention END) r10_neighbor,
          count(DISTINCT resolution) nres
        FROM read_parquet('{p}') GROUP BY pair_id,target_id
      )
      SELECT * FROM x WHERE nres=3
    """
    res["cross_resolution_summary"]=run_query(con, f"""
      WITH x AS ({cross_sql})
      SELECT count(*) triples,
        avg(sign(r3_edge)=sign(r5_edge) AND sign(r5_edge)=sign(r10_edge) AND sign(r3_edge)<>0) all_sign_agree_frac,
        avg(sign(r3_inter)=sign(r5_inter) AND sign(r5_inter)=sign(r10_inter) AND sign(r3_inter)<>0) all_inter_sign_agree_frac,
        avg(sign(r3_edge)=sign(r5_edge) AND sign(r5_edge)<>sign(r10_edge)) fine_flip_frac,
        approx_quantile(least(abs(r3_edge),abs(r5_edge),abs(r10_edge)),[0.5,0.9,0.95,0.99]) min_abs_edge_q
      FROM x
    """)
    res["cross_resolution_consistent"]=run_query(con, f"""
      WITH x AS ({cross_sql})
      SELECT *,least(abs(r3_edge),abs(r5_edge),abs(r10_edge)) min_abs_edge
      FROM x
      WHERE sign(r3_edge)=sign(r5_edge) AND sign(r5_edge)=sign(r10_edge) AND sign(r3_edge)<>0
        AND least(r3_n,r5_n,r10_n)>=250
      ORDER BY min_abs_edge DESC LIMIT 500
    """)
    res["cross_resolution_flips"]=run_query(con, f"""
      WITH x AS ({cross_sql})
      SELECT * FROM x
      WHERE least(r3_n,r5_n,r10_n)>=250
        AND ((sign(r3_edge)=sign(r5_edge) AND sign(r5_edge)<>sign(r10_edge))
          OR (sign(r3_edge)<>sign(r5_edge) AND sign(r5_edge)=sign(r10_edge)))
      ORDER BY greatest(abs(r3_edge),abs(r5_edge),abs(r10_edge)) DESC LIMIT 500
    """)
    con.close()
    return res

def generic_small_tables():
    out={}
    con=duckdb.connect()
    for name in ["feature_registry","target_registry","single_summary","trial_ledger","resolution_comparison",
                 "edge_families","edge_registry","candidate_summary","variant_summary",
                 "chronological_diagnostics","crossfit_diagnostics","time_of_day","coverage",
                 "regime_breakdown","tail_ladder","horizon_ladder","specialist_summary"]:
        p=DATA/f"{name}.parquet"
        if not p.exists():
            continue
        try:
            desc=con.execute("DESCRIBE SELECT * FROM read_parquet(?)",[str(p)]).fetchdf()
            cols=desc.column_name.tolist()
            n=con.execute("SELECT count(*) FROM read_parquet(?)",[str(p)]).fetchone()[0]
            item={"rows":int(n),"columns":cols}
            if name=="trial_ledger":
                if {"trial_family_id","status","work_units"}.issubset(cols):
                    item["coverage"]=con.execute("""
                        SELECT trial_family_id,status,count(*) rows,sum(work_units) work_units
                        FROM read_parquet(?) GROUP BY 1,2 ORDER BY 1,2
                    """,[str(p)]).fetchdf().to_dict("records")
                elif {"trial_family_id","status"}.issubset(cols):
                    item["coverage"]=con.execute("""
                        SELECT trial_family_id,status,count(*) rows
                        FROM read_parquet(?) GROUP BY 1,2 ORDER BY 1,2
                    """,[str(p)]).fetchdf().to_dict("records")
            elif name=="single_summary":
                numcols=[r.column_name for r in desc.itertuples() if any(x in str(r.column_type).upper() for x in ["INT","DOUBLE","FLOAT","DECIMAL"])]
                interesting=[c for c in numcols if any(tok in c.lower() for tok in ["bps","edge","return","frequency","n","interaction"])]
                q={}
                for c in interesting[:20]:
                    try:
                        q[c]=con.execute(f"SELECT approx_quantile({duckdb.escape_identifier(c)},[0.01,0.1,0.5,0.9,0.99]) FROM read_parquet(?)",[str(p)]).fetchone()[0]
                    except Exception:
                        pass
                item["numeric_quantiles"]=q
            out[name]=item
        except Exception as e:
            out[name]={"error":str(e)}
    con.close()
    return out

def combined_findings(df):
    if df.empty:
        return {}
    d=df.copy()
    for c in ["raw_edge_bps","active_n","interaction_lift_bps","frequency","se_bps",
              "cancellation_score","symbol_effect_dispersion_bps","positive_symbol_fraction",
              "negative_symbol_fraction","top_symbol_contribution_share","fold_positive_fraction",
              "fold_negative_fraction","median_fold_bps","fold_dispersion_bps","minimum_fold_n",
              "fold_sign_consistency"]:
        if c not in d: d[c]=np.nan
    d["abs_edge"]=d.raw_edge_bps.abs()
    d["abs_inter"]=d.interaction_lift_bps.abs()
    d["symbol_balance"]=2*np.minimum(d.positive_symbol_fraction,d.negative_symbol_fraction)
    d["stable"]=d.fold_sign_consistency>=0.8
    out={}
    def take(name,mask,sortcols,ascending=False,n=300):
        z=d.loc[mask].copy()
        if z.empty:
            out[name]=[]
            return
        z=z.sort_values(sortcols,ascending=ascending).head(n)
        out[name]=z.replace({np.nan:None}).to_dict("records")
    take("large_stable_edges",
         (d.active_n>=250)&(d.abs_edge>=1)&d.stable&(d.minimum_fold_n>=20),
         ["abs_edge","active_n"],ascending=False)
    take("large_stable_negative_edges",
         (d.active_n>=250)&(d.raw_edge_bps<0)&d.stable&(d.minimum_fold_n>=20),
         ["abs_edge","active_n"],ascending=False)
    take("interaction_dominant",
         (d.active_n>=250)&(d.abs_inter>=2)&(d.abs_inter>=d.abs_edge*1.25)&d.stable,
         ["abs_inter","abs_edge"],ascending=False)
    take("specialist_cancellation",
         (d.active_n>=250)&(d.symbol_balance>=0.5)&(d.symbol_effect_dispersion_bps>0)&
         np.isfinite(d.cancellation_score),
         ["symbol_effect_dispersion_bps","cancellation_score"],ascending=False)
    take("common_weighted",
         (d.active_n>=1000)&(d.abs_edge>=0.5),
         ["weighted_contribution_bps","active_n"],ascending=False)
    take("suspect_temporal",
         (d.active_n>=250)&(d.abs_edge>=2)&(d.fold_sign_consistency<=0.6),
         ["abs_edge","fold_dispersion_bps"],ascending=False)
    take("suspect_symbol_concentration",
         (d.active_n>=250)&(d.abs_edge>=2)&(d.top_symbol_contribution_share>=0.5),
         ["top_symbol_contribution_share","abs_edge"],ascending=False)
    return out

def main():
    download_assets()
    dual_files=sorted(DATA.glob("dual_summary_[0-9][0-9][0-9].parquet"))
    specialist_files=sorted(DATA.glob("specialist_[0-9][0-9][0-9].parquet"))
    temporal_files=sorted(DATA.glob("temporal_[0-9][0-9][0-9].parquet"))
    if not dual_files or not specialist_files or not temporal_files:
        raise RuntimeError(f"Missing canonical shards: dual={len(dual_files)} specialist={len(specialist_files)} temporal={len(temporal_files)}")

    integrity={
        "bundle_manifest":jload("bundle_manifest.json"),
        "evidence_complete":jload("EVIDENCE_COMPLETE.json"),
        "exhaustiveness_manifest":jload("exhaustiveness_manifest.json"),
        "status":jload("STATUS.json"),
        "manifest":jload("manifest.json"),
        "disk_before_analysis":subprocess.check_output(["df","-h",str(ROOT)],text=True),
        "dual_shards":[{"name":p.name,"size":p.stat().st_size} for p in dual_files],
        "specialist_shards":[{"name":p.name,"size":p.stat().st_size} for p in specialist_files],
        "temporal_shards":[{"name":p.name,"size":p.stat().st_size} for p in temporal_files],
    }
    (OUT/"integrity.json").write_text(json.dumps(integrity,indent=2,default=str),encoding="utf-8")

    schemas=parquet_schema(dual_files[:1]+specialist_files[:1]+temporal_files[:1]+
                           [p for p in [DATA/"single_summary.parquet",DATA/"feature_registry.parquet",
                                        DATA/"target_registry.parquet",DATA/"trial_ledger.parquet"] if p.exists()])
    (OUT/"schemas.json").write_text(json.dumps(schemas,indent=2),encoding="utf-8")

    print("Analyzing dual universe...",flush=True)
    dual_summary=analyze_dual(dual_files)
    (OUT/"dual_background.json").write_text(json.dumps(dual_summary,indent=2),encoding="utf-8")

    print("Analyzing specialist universe...",flush=True)
    specialist_summary=specialist_records(specialist_files)
    (OUT/"specialist_background.json").write_text(json.dumps(specialist_summary,indent=2),encoding="utf-8")

    print("Analyzing temporal universe...",flush=True)
    temporal_summary=temporal_records(temporal_files)
    (OUT/"temporal_background.json").write_text(json.dumps(temporal_summary,indent=2),encoding="utf-8")

    print("Enriching union of unusual/top cells...",flush=True)
    enriched=lookup_union(dual_files,specialist_files,temporal_files)
    combined=combined_findings(enriched)
    (OUT/"combined_findings.json").write_text(json.dumps(combined,indent=2,default=str),encoding="utf-8")

    print("Surface/cross-resolution analysis...",flush=True)
    surfaces=surface_analysis()
    (OUT/"surface_analysis.json").write_text(json.dumps(surfaces,indent=2,default=str),encoding="utf-8")

    small=generic_small_tables()
    (OUT/"small_tables.json").write_text(json.dumps(small,indent=2,default=str),encoding="utf-8")

    summary={
        "source_repo":REPO,"release_tag":TAG,
        "canonical_shards":{"dual":len(dual_files),"specialist":len(specialist_files),"temporal":len(temporal_files)},
        "dual_surface_rows":dual_summary["surface_rows"],
        "expanded_dual_cells":dual_summary["expanded_cell_count"],
        "specialist_surface_rows":specialist_summary["surface_rows"],
        "temporal_surface_rows":temporal_summary["surface_rows"],
        "union_top_cells":int(len(enriched)),
        "replication_or_holdout_loaded_by_this_script":False,
        "pipeline_rerun":False,
        "method":"Read-only scan of existing v3-discovery release Parquet evidence; exact counts/moments plus deterministic streaming samples for quantiles; top/unusual cells re-enriched across dual/specialist/temporal evidence.",
        "quantile_note":"Cell-level background quantiles are estimated from deterministic Bernoulli streaming samples; counts, signs, means, sums, and scan coverage are computed from the full cell universe.",
    }
    (OUT/"analysis_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")

    # Do not upload the large compact surface file; it is only an intermediate.
    try:
        (OUT/"surface_compact.parquet").unlink()
    except FileNotFoundError:
        pass

    print(json.dumps(summary,indent=2),flush=True)

if __name__=="__main__":
    main()
