"""Local research façade over committed evidence and durable jobs."""
from __future__ import annotations

import json
import uuid
import base64
from pathlib import Path

from .evidence_identity import atomic_json,digest
from .evidence_query import group_cells,open_catalog
from .research_jobs import JobStore
from .evidence_cache import EvidenceCache
from .evidence_artifacts import load_tile,committed_tile
from .evidence_reducer import consume_block
from .segmented_task import execute_segmented_task
from .evidence_store import EvidenceReader
from .resource_policy import ResourcePolicy


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
                "materialization":{"stored_tasks":(coverage or {}).get("stored_tasks"),
                                   "recomputable_tasks":(coverage or {}).get("recomputable_tasks"),
                                   "unavailable_groupings":(coverage or {}).get("unavailable_groupings",[])},
                "diagnostics":{"symbol":"on_request" if reader else "unavailable",
                               "time":"on_request" if reader else "unavailable",
                               "opportunities":"requires_exact_target_ledger",
                               "fine_tails":"requires_raw_feature_rank_dependency"},
                "journal":"research/jobs.sqlite" if (self.root/"research"/"jobs.sqlite").exists() else None,
                "available":bool(reader and catalog)}

    def _catalog(self):
        catalog=self._json("evidence/catalog.json")
        if not catalog: raise RuntimeError("No committed subgroup catalog; inspect coverage status")
        memory=ResourcePolicy(self.machine).duckdb_gib()
        threads=self.machine.get("duckdb_threads",2)
        if threads=="auto": threads=2
        return open_catalog(self.root,"evidence/catalog.json",memory_gib=memory,threads=int(threads))

    def _matching_tasks(self,spec):
        plan=self._json("evidence/coverage_plan.json")
        if not plan: raise RuntimeError("No declared subgroup coverage plan")
        with (self.root/plan["path"]).open(encoding="utf-8") as stream:
            for line in stream:
                row=json.loads(line); task=row["task"]
                if row["grid"]!=spec.get("grid") or task["grouping_id"]!=spec.get("grouping") or task["state_kind"]!=spec.get("state_kind","dual"):
                    continue
                if "resolution" in spec and task["resolution"]!=int(spec["resolution"]): continue
                if "pair_id" in spec and spec["pair_id"] not in task["pair_ids"]: continue
                if "target_id" in spec and spec["target_id"] not in task["target_ids"]: continue
                if "group_id" in spec and not task["group_start"]<=int(spec["group_id"])<task["group_stop"]: continue
                yield row

    def _ensure_tile(self,row,cache,cancelled):
        task=row["task"]
        moments=load_tile(self.root,task)
        if moments is not None:
            record=cache.get(task["task_id"])
            if record is None or record["materialization_status"]!="stored":
                manifest=committed_tile(self.root,task)
                cache.record(row["grid"],task,manifest,
                             self._json("evidence/reader.json")["grids"][row["grid"]]["rows"])
                cache.publish_catalog(self._json("evidence/reader.json")["evidence_id"],task["stage_id"])
            else:cache.touch(task["task_id"])
            return moments
        if cancelled(): raise InterruptedError("Research job cancelled")
        reader=EvidenceReader(self.root,"evidence/reader.json",row["grid"])
        machine=self.machine
        device=machine.get("gpu_device","cpu")
        if device!="cpu":
            try:
                import torch
                if not torch.cuda.is_available(): device="cpu"
            except ImportError: device="cpu"
        result=execute_segmented_task(root=self.root,task=task,reader=reader,
            pair_definitions=row["pairs"],observation_id=reader.grid["observation_id"],
            row_chunk=int(machine.get("evidence_row_chunk",250000)),max_state_bytes=ResourcePolicy(machine).state_budget(device),
            device=device,cancelled=cancelled)
        moments=load_tile(self.root,task)
        if cache.get(task["task_id"]) is None:
            consume_block({"journal":self.root/"evidence"/"sweep_summary.jsonl"},moments,
                          {"task":task,"rows_evaluated":reader.rows})
        cache.record(row["grid"],task,result,reader.rows)
        reader_manifest=self._json("evidence/reader.json")
        cache.publish_catalog(reader_manifest["evidence_id"],task["stage_id"])
        return moments

    def _trim_cache(self,cache,stage_id,evidence_id):
        storage=self._json("evidence/storage_plan.json") or {}
        budget=storage.get("cache_bytes",2*(1<<30))
        cache.evict_to_budget(budget,evidence_id,stage_id)

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
        matches=list(self._matching_tasks(spec))
        if len(matches)!=1: raise ValueError("Exact query does not resolve to one declared task")
        task=matches[0]["task"]
        query_key=digest({"task":task["task_id"],"pair":spec["pair_id"],"target":spec["target_id"],
                          "group":int(spec["group_id"]),"evidence":reader["evidence_id"]})
        after_cell=int(spec.get("after_cell",-1))
        if "cursor" in spec:
            token=json.loads(base64.urlsafe_b64decode(spec["cursor"]+"="*(-len(spec["cursor"])%4)))
            if token.get("query")!=query_key: raise ValueError("Cursor belongs to another evidence query")
            after_cell=int(token["after_cell"])
        cache=EvidenceCache(self.root); pin_id=uuid.uuid4().hex; cache.pin(pin_id)
        try:
            moments=self._ensure_tile(matches[0],cache,lambda:False)
            table=f"{spec['grid']}_{spec['grouping']}_{spec['state_kind']}"
            if "cell_union" in spec:
                cells=list(map(int,spec["cell_union"]))
                maximum=int(spec["resolution"]) if spec["state_kind"]=="single" else int(spec["resolution"])**2
                if not cells or len(set(cells))!=len(cells) or min(cells)<0 or max(cells)>=maximum:
                    raise ValueError("Cell union must contain distinct cells in one resolution")
                counts,sums,sumsq=moments.numpy()
                t=task["target_ids"].index(spec["target_id"])
                p=task["pair_ids"].index(spec["pair_id"])
                g=int(spec["group_id"])-task["group_start"]
                total=int(counts[t,p,g].sum()); n=int(counts[t,p,g,cells].sum())
                sum_y=float(sums[t,p,g,cells].sum()); sum_y2=float(sumsq[t,p,g,cells].sum())
                row={"cell_union":cells,"n":n,"sum_y":sum_y,"sum_y2":sum_y2,
                     "raw_mean_bps":sum_y/n*10000 if n else None,
                     "frequency":n/total if total else None,
                     "independent_opportunities":"requires_exact_diagnostic"}
                if spec.get("include_distinct_sessions"):
                    from .diagnostics import prepare_state_events
                    import duckdb
                    event_spec={"grid":spec["grid"],"state_kind":spec["state_kind"],"pair_id":spec["pair_id"],
                                "target_id":spec["target_id"],"resolution":spec["resolution"],"cells":cells,
                                "grouping":spec["grouping"],"group_ids":[int(spec["group_id"])]}
                    event_path,_=prepare_state_events(self.root,reader,event_spec)
                    with duckdb.connect() as diagnostic_con:
                        sessions,security_sessions=diagnostic_con.execute(
                            "SELECT count(DISTINCT session_date),count(DISTINCT (security_id,session_date)) FROM read_parquet(?)",
                            [str(event_path)]).fetchone()
                    row["distinct_sessions"]=int(sessions)
                    row["distinct_security_sessions"]=int(security_sessions)
                page={"status":"available" if n else "computed_empty","rows":[row],"next_cell":None}
                manifest={"evidence_id":reader["evidence_id"],"task_id":task["task_id"]}
            else:
                cache.publish_catalog(reader["evidence_id"],task["stage_id"])
                con,manifest=self._catalog()
                try:
                    page=group_cells(con,table=table,pair_id=spec["pair_id"],target_id=spec["target_id"],
                                     resolution=int(spec["resolution"]),group_id=int(spec["group_id"]),
                                     after_cell=after_cell,limit=int(spec.get("limit",100)))
                finally: con.close()
            if page["status"]=="absent_requires_coverage_check":
                page["status"]="computed_empty"
        finally:
            cache.unpin(pin_id)
            self._trim_cache(cache,task["stage_id"],reader["evidence_id"])
            cache.close()
        coverage=self._json("evidence/coverage_status.json") or {}
        next_cursor=None
        if page["next_cell"] is not None:
            raw=json.dumps({"query":query_key,"after_cell":page["next_cell"]},sort_keys=True).encode()
            next_cursor=base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return {**page,"run_id":self.run_id,"evidence_id":manifest["evidence_id"],
                "snapshot_id":digest(manifest),"requested_scope":spec,
                "next_cursor":next_cursor,"evaluated_scope":{"task_id":task["task_id"],"group_id":int(spec["group_id"])},
                "total_rows":None,
                "coverage_status":coverage.get("status","complete" if coverage.get("mandatory_coverage_complete") else "partial"),
                "units":{"sum_y":"decimal_return","raw_mean_bps":"basis_points","frequency":"fraction"}}

    def search(self,spec,cancelled=lambda:False):
        coverage=self._json("evidence/coverage_status.json") or {}
        grid=spec.get("grid"); grouping=spec.get("grouping"); state_kind=spec.get("state_kind","dual")
        if not grid or not grouping or state_kind not in {"single","dual"}: raise ValueError("Search needs grid, grouping and state_kind")
        limit=int(spec.get("limit",100))
        if not 1<=limit<=1000: raise ValueError("Search limit must be 1..1000")
        if int(spec.get("min_n",1))<0: raise ValueError("min_n must be nonnegative")
        reader=self._json("evidence/reader.json")
        state={"spec":spec,"top_k":limit,"tasks_evaluated":0,"cells_evaluated":0}
        cache=EvidenceCache(self.root)
        plan=self._json("evidence/coverage_plan.json")
        scope=(plan or {}).get("scope_counts",{}).get(f"{grid}/{grouping}/{state_kind}")
        if scope and scope["outcome"]=="unavailable":
            cache.close();return {"status":"unavailable","reason":"Grouping input unavailable","scope":scope}
        if scope and scope["outcome"]=="empty":
            cache.close();return {"status":"complete","rows":0,"evaluated_scope":{"tasks":0,"cells":0},
                                  "reason":"Declared grouping has no valid groups"}
        try:
            for row in self._matching_tasks(spec):
                if cancelled(): raise InterruptedError("Search cancelled")
                pin_id=uuid.uuid4().hex;cache.pin(pin_id)
                try:
                    moments=self._ensure_tile(row,cache,cancelled)
                    consume_block(state,moments,{"task":row["task"],"rows_evaluated":reader["grids"][grid]["rows"]})
                finally:
                    cache.unpin(pin_id)
                self._trim_cache(cache,row["task"]["stage_id"],reader["evidence_id"])
            top=state.get("top",[])
            top.sort(key=lambda item:(-abs(item["raw_mean_bps"]),item["pair_id"],item["target_id"],item["resolution"],item["group_id"],item["cell_index"]))
            top=top[:limit]
        finally:cache.close()
        if state["tasks_evaluated"]==0: raise ValueError("Search matches no declared subgroup tasks")
        result={"status":"complete","run_id":self.run_id,"evidence_id":reader["evidence_id"],
                "snapshot_id":digest({"plan":plan["stage_id"],"spec":spec}),"requested_scope":spec,
                "evaluated_scope":{"tasks":state["tasks_evaluated"],"cells":state["cells_evaluated"]},
                "coverage":coverage,"units":{"sum_y":"decimal_return","raw_mean_bps":"basis_points"},"rows":top}
        path=self.root/"research"/"results"/f"{digest({'evidence':reader['evidence_id'],'spec':spec})}.json"
        atomic_json(path,result)
        return {"status":"complete","result":path.relative_to(self.root).as_posix(),"rows":len(top),
                "evidence_id":reader["evidence_id"],"evaluated_scope":result["evaluated_scope"]}

    def inspect(self,spec,cancelled=lambda:False):
        kind=spec.get("kind")
        if "cells" in spec and kind in {"symbol","time","opportunities"}:
            from .diagnostics import inspect_state
            reader=self._json("evidence/reader.json")
            if not reader:return {"status":"unavailable","reason":"Verified evidence reader is absent"}
            return inspect_state(self.root,reader,spec,cancelled=cancelled)
        if kind not in {"symbol","time","month","fold"}:
            return {"status":"unavailable","reason":f"Diagnostic {kind!r} needs a separate verified adapter"}
        grouping={"symbol":"security","time":"time_bucket","month":"month","fold":"fold"}[kind]
        query={**spec,"grouping":grouping}
        query.pop("kind",None)
        if "group_id" in query:
            return self.query(query)
        return self.search(query,cancelled)

    def experiment(self,spec,cancelled=lambda:False):
        if spec.get("kind")=="backtest":
            from .replay import run_backtest
            reader=self._json("evidence/reader.json")
            if not reader:return {"status":"unavailable","reason":"Verified evidence reader is absent"}
            return run_backtest(self.root,reader,self.machine,spec,cancelled=cancelled)
        if spec.get("kind")=="neighbor":
            from .coverage import _members
            reader=self._json("evidence/reader.json")
            grid=spec["grid"]
            if not reader or grid not in reader["grids"]:raise ValueError("Unknown evidence grid")
            state_kind=spec.get("state_kind","dual")
            valid,_=_members(self.root,grid,reader["grids"][grid],state_kind)
            requested=spec.get("pair_ids",[])
            if not requested or len(set(requested))!=len(requested):raise ValueError("Neighbor pair_ids must be nonempty and unique")
            missing=sorted(set(requested)-set(valid))
            if missing:return {"status":"unavailable","reason":"Neighbor features require verified bin dependency",
                               "missing_pair_ids":missing}
            children=[]
            for pair in requested:
                if cancelled():raise InterruptedError("Neighbor scan cancelled")
                child={"grid":grid,"grouping":spec["grouping"],"state_kind":state_kind,
                       "pair_id":pair,"target_id":spec["target_id"],"limit":int(spec.get("limit",100)),
                       "min_n":int(spec.get("min_n",1))}
                if "resolution" in spec:child["resolution"]=int(spec["resolution"])
                children.append({"pair_id":pair,**self.search(child,cancelled)})
            identity=digest({"evidence":reader["evidence_id"],"neighbor":spec})
            path=self.root/"research"/"neighbors"/f"{identity}.json"
            atomic_json(path,{"status":"complete","evidence_id":reader["evidence_id"],
                              "requested_scope":spec,"children":children})
            return {"status":"complete","result":path.relative_to(self.root).as_posix(),"children":len(children)}
        return {"status":"unavailable","reason":"Unsupported experiment kind"}

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
