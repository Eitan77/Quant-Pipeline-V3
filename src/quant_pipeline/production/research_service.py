"""Local research façade over committed evidence and durable jobs."""
from __future__ import annotations

import json
from pathlib import Path

from .evidence_identity import atomic_json,digest
from .evidence_query import group_cells,open_catalog
from .research_jobs import JobStore


class ResearchService:
    def __init__(self,machine,run_id):
        self.machine=machine
        self.root=(Path(machine["run_root"])/run_id).resolve()
        if not self.root.is_dir(): raise FileNotFoundError(self.root)
        self.run_id=run_id

    def _json(self,relative):
        path=self.root/relative
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def describe(self,include_definitions=False):
        reader=self._json("evidence/reader.json")
        coverage=self._json("evidence/coverage_status.json")
        catalog=self._json("evidence/catalog.json")
        scope=reader.get("scope") if reader else self._json("resolved_research_scope.json")
        scope_summary=({"discovery":scope.get("discovery"),"grids":scope.get("grids"),
                        "feature_count":len(scope.get("features",[])),"target_count":len(scope.get("targets",[])),
                        "definitions_path":"evidence/reader.json" if reader else "resolved_research_scope.json"}
                       if scope else None)
        return {"run_id":self.run_id,"evidence_id":reader.get("evidence_id") if reader else None,
                "scope":scope if include_definitions else scope_summary,
                "coverage":coverage or {"status":"legacy_summary_only"},
                "storage":self._json("evidence/storage_plan.json"),
                "tables":list(catalog.get("tables",{})) if catalog else [],
                "available":bool(reader and catalog)}

    def _catalog(self):
        catalog=self._json("evidence/catalog.json")
        if not catalog: raise RuntimeError("No committed subgroup catalog; inspect coverage status")
        memory=max(1,min(24,int(self.machine.get("duckdb_memory_limit_gb",4))))
        threads=self.machine.get("duckdb_threads",2)
        if threads=="auto": threads=2
        return open_catalog(self.root,"evidence/catalog.json",memory_gib=memory,threads=int(threads))

    def query(self,spec):
        required={"grid","grouping","state_kind","pair_id","target_id","resolution","group_id"}
        if required-set(spec): raise ValueError(f"Missing query fields: {sorted(required-set(spec))}")
        if spec["state_kind"] not in {"single","dual"}: raise ValueError("Invalid state kind")
        reader=self._json("evidence/reader.json")
        if not reader or spec["grid"] not in reader["grids"]: raise ValueError("Unknown evidence grid")
        grid=reader["grids"][spec["grid"]]
        if spec["target_id"] not in grid["targets"]: raise ValueError("Target outside evidence scope")
        if spec["grouping"] not in grid["groups"] or not 0<=int(spec["group_id"])<grid["groups"][spec["grouping"]]["groups"]:
            raise ValueError("Group outside evidence scope")
        from .coverage import _members
        pairs,_=_members(self.root,spec["grid"],grid,spec["state_kind"])
        if spec["pair_id"] not in set(pairs): raise ValueError("Pair outside evidence scope")
        table=f"{spec['grid']}_{spec['grouping']}_{spec['state_kind']}"
        con,manifest=self._catalog()
        try:
            if table not in manifest["tables"]:
                page={"status":"absent_requires_coverage_check","rows":[],"next_cell":None}
            else:
                page=group_cells(con,table=table,pair_id=spec["pair_id"],target_id=spec["target_id"],
                                 resolution=int(spec["resolution"]),group_id=int(spec["group_id"]),
                                 after_cell=int(spec.get("after_cell",-1)),limit=int(spec.get("limit",100)))
        finally: con.close()
        coverage=self._json("evidence/coverage_status.json") or {}
        if page["status"]=="absent_requires_coverage_check" and coverage.get("mandatory_coverage_complete"):
            page["status"]="computed_empty"
        return {**page,"run_id":self.run_id,"evidence_id":manifest["evidence_id"],
                "snapshot_id":digest(manifest),"requested_scope":spec,
                "coverage_status":coverage.get("status","complete" if coverage.get("mandatory_coverage_complete") else "partial"),
                "units":{"sum_y":"decimal_return","raw_mean_bps":"basis_points","frequency":"fraction"}}

    def search(self,spec,cancelled=lambda:False):
        coverage=self._json("evidence/coverage_status.json") or {}
        if not coverage.get("mandatory_coverage_complete"):
            return {"status":"unavailable","reason":"Mandatory subgroup coverage is incomplete","coverage":coverage}
        grid=spec.get("grid"); grouping=spec.get("grouping"); state_kind=spec.get("state_kind","dual")
        if not grid or not grouping or state_kind not in {"single","dual"}: raise ValueError("Search needs grid, grouping and state_kind")
        table=f"{grid}_{grouping}_{state_kind}"
        con,manifest=self._catalog()
        try:
            if table not in manifest["tables"]: raise ValueError(f"Unpublished table {table}")
            if cancelled(): raise InterruptedError("Search cancelled")
            where=[]; params=[]
            for field in ("pair_id","target_id","group_id","resolution"):
                if field in spec:
                    where.append(f"{field}=?"); params.append(spec[field])
            predicate=" WHERE "+" AND ".join(where) if where else ""
            limit=int(spec.get("limit",100))
            if not 1<=limit<=1000: raise ValueError("Search limit must be 1..1000")
            minimum=int(spec.get("min_n",1))
            if minimum<0: raise ValueError("min_n must be nonnegative")
            sql=f'''WITH base AS (SELECT * FROM "{table}"{predicate}), cells AS (
                SELECT pair_id,target_id,resolution,group_id,cell_index,
                       list_extract(counts,cell_index+1) n,
                       list_extract(sums,cell_index+1) sum_y,
                       list_extract(sumsq,cell_index+1) sum_y2
                FROM base, UNNEST(range(0,len(counts))) c(cell_index))
                SELECT *,10000.0*sum_y/nullif(n,0) raw_mean_bps
                FROM cells WHERE n>=? ORDER BY abs(raw_mean_bps) DESC NULLS LAST,
                pair_id,target_id,resolution,group_id,cell_index LIMIT ?'''
            cursor=con.execute(sql,params+[minimum,limit])
            names=[item[0] for item in cursor.description]
            rows=[dict(zip(names,row)) for row in cursor.fetchall()]
        finally: con.close()
        result={"status":"complete","run_id":self.run_id,"evidence_id":manifest["evidence_id"],
                "snapshot_id":digest(manifest),"requested_scope":spec,"evaluated_scope":"all stored rows matching filters",
                "coverage":coverage,"units":{"sum_y":"decimal_return","raw_mean_bps":"basis_points"},"rows":rows}
        path=self.root/"research"/"results"/f"{digest({'evidence':manifest['evidence_id'],'spec':spec})}.json"
        atomic_json(path,result)
        return {"status":"complete","result":path.relative_to(self.root).as_posix(),"rows":len(rows),
                "evidence_id":manifest["evidence_id"],"evaluated_scope":result["evaluated_scope"]}

    def inspect(self,spec,cancelled=lambda:False):
        kind=spec.get("kind")
        if kind not in {"symbol","time","month","fold"}:
            return {"status":"unavailable","reason":f"Diagnostic {kind!r} needs a separate verified adapter"}
        grouping={"symbol":"security","time":"time_bucket","month":"month","fold":"fold"}[kind]
        query={**spec,"grouping":grouping}
        query.pop("kind",None)
        if "group_id" in query:
            return self.query(query)
        return self.search(query,cancelled)

    def experiment(self,spec,cancelled=lambda:False):
        return {"status":"unavailable","reason":"Neighbor and replay adapters are not yet integrated with verified signals"}

    def job_status(self,job_id):
        store=JobStore(self.root/"research"/"jobs.sqlite")
        try: return store.get(job_id)
        finally: store.close()

    def job_results(self,job_id):
        job=self.job_status(job_id)
        result=json.loads(job["result"]) if job["result"] else None
        if result and result.get("result"):
            result=json.loads((self.root/result["result"]).read_text(encoding="utf-8"))
        return {"job":job,"result":result}

    def cancel(self,job_id):
        store=JobStore(self.root/"research"/"jobs.sqlite")
        try: store.cancel(job_id); return store.get(job_id)
        finally: store.close()
