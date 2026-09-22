from __future__ import annotations
from pathlib import Path
import numpy as np,pandas as pd,pyarrow.dataset as ds
from quant_pipeline.alpha_discovery.cache.rank_store import build_percentile_ranks,unpack_bins
from quant_pipeline.production.evidence_store import ByteLRU

DUAL_TREES={3:"dual_coarse_results",5:"dual_fine_results",10:"dual_exact_results"}

def load_duals(run_root:Path,resolutions=(3,5,10))->pd.DataFrame:
    frames=[]
    for resolution in resolutions:
        files=list((Path(run_root)/DUAL_TREES[int(resolution)]).rglob("*.parquet"))
        if not files: raise RuntimeError(f"Missing dual output for r{resolution}")
        frame=pd.concat((pd.read_parquet(path) for path in files),ignore_index=True); frame["v3_resolution"]=int(resolution)
        if not frame.resolution.eq(int(resolution)).all(): raise RuntimeError(f"Resolution integrity failure for r{resolution}")
        frames.append(frame)
    return pd.concat(frames,ignore_index=True)

def iter_dual_batches(path:Path,*,columns:list[str]|None=None,batch_size:int=16_384):
    dataset=ds.dataset(str(path),format="parquet"); scanner=dataset.scanner(columns=columns,batch_size=batch_size,use_threads=True)
    yield from scanner.to_batches()

class ProductionData:
    def __init__(self,legacy_run,*,target_cache_bytes=536870912,rank_cache_bytes=536870912):
        self.run=legacy_run; self.bundle=legacy_run.compile_registry(); self.features={x.feature_id:x for x in self.bundle.features}; self.targets={x.target_id:x for x in self.bundle.targets}; self._grids={}; self._bin_mappings={}; self._bin_sources={}; self._targets=ByteLRU(target_cache_bytes); self._ranks=ByteLRU(rank_cache_bytes)
    def grid(self,feature_id): return self.features[feature_id].decision_grid
    def observations(self,grid):
        if grid not in self._grids:self._grids[grid]=pd.read_parquet(self.run.root/"cache"/"features"/grid/"observations.parquet")
        return self._grids[grid]
    def bin_source(self,grid,feature_id):
        key=(grid,feature_id)
        if key not in self._bin_sources:
            if grid not in self._bin_mappings:self._bin_mappings[grid],_=self.run._ensure_bin_cache(grid,self.observations(grid))
            mapping=self._bin_mappings[grid]
            if feature_id not in mapping: raise KeyError(f"Packed bins missing for {feature_id}")
            path,column=mapping[feature_id]; self._bin_sources[key]=(np.load(path,mmap_mode="r",allow_pickle=False),int(column))
        return self._bin_sources[key]
    def bins_slice(self,grid,feature_id,resolution,start,end):
        packed,column=self.bin_source(grid,feature_id); return unpack_bins(packed[start:end,column],resolution)
    def bins(self,grid,feature_id,resolution):
        packed,column=self.bin_source(grid,feature_id); return unpack_bins(packed[:,column],resolution)
    def target(self,grid,target_id):
        key=(grid,target_id)
        return self._targets.get_or_load(key,lambda:np.asarray(self.run._target_ids_and_vector(grid,self.observations(grid),target_id),dtype=float))
    def percentile_rank(self,grid,feature_id):
        def load():
            obs,values=self.run._load_features(grid,[feature_id]); expected=self.observations(grid)
            if not np.array_equal(obs.observation_id.to_numpy(),expected.observation_id.to_numpy()):
                raise RuntimeError("Feature/observation alignment mismatch")
            codes=pd.factorize(obs.decision_ts,sort=True)[0]
            return build_percentile_ranks(np.asarray(values),codes)[:,0]
        return self._ranks.get_or_load((grid,feature_id),load)
    def selected(self,row):
        resolution=int(row["v3_resolution"] if "v3_resolution" in row else row["resolution"]); grid=self.grid(row["feature_a"]); cell=int(row["selected_cell"]); a_cell,b_cell=divmod(cell,resolution); a=self.bins(grid,row["feature_a"],resolution); b=self.bins(grid,row["feature_b"],resolution); y=self.target(grid,row["target_id"]); mask=(a==a_cell)&(b==b_cell)&np.isfinite(y)
        return grid,self.observations(grid),a,b,y,mask,a_cell,b_cell
