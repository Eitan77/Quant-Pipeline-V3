"""Bounded materialization ledger and catalog reader pins."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
import psutil

from .evidence_identity import atomic_json, inside


class EvidenceCache:
    def __init__(self, root):
        self.root = Path(root)
        path = self.root / "evidence" / "cache.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("""CREATE TABLE IF NOT EXISTS blocks (
            task_id TEXT PRIMARY KEY, stage_id TEXT NOT NULL, task_json TEXT NOT NULL, grid TEXT NOT NULL,
            table_name TEXT NOT NULL, compute_status TEXT NOT NULL,
            materialization_status TEXT NOT NULL, artifact TEXT, bytes INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT, populated_groups INTEGER NOT NULL DEFAULT 0,
            rows_evaluated INTEGER NOT NULL DEFAULT 0, last_used INTEGER NOT NULL DEFAULT 0)""")
        self.con.execute("""CREATE TABLE IF NOT EXISTS pins (
            id TEXT PRIMARY KEY, pid INTEGER NOT NULL, process_start REAL NOT NULL,
            created INTEGER NOT NULL, scope_type TEXT NOT NULL DEFAULT 'all', scope_key TEXT)""")
        columns={row[1] for row in self.con.execute("PRAGMA table_info(pins)")}
        if "scope_type" not in columns:
            self.con.execute("ALTER TABLE pins ADD COLUMN scope_type TEXT NOT NULL DEFAULT 'all'")
        if "scope_key" not in columns:
            self.con.execute("ALTER TABLE pins ADD COLUMN scope_key TEXT")

    def close(self):
        self.con.close()

    def get(self, task_id):
        row = self.con.execute("SELECT * FROM blocks WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def completed_task_ids(self, stage_id):
        rows = self.con.execute(
            "SELECT task_id FROM blocks "
            "WHERE stage_id=? AND compute_status='complete'",
            (stage_id,),
        )
        return {row[0] for row in rows}

    def record(self, grid, task, manifest, rows_evaluated):
        table = f"{grid}_{task['grouping_id']}_{task['state_kind']}"
        self.con.execute("""INSERT INTO blocks
            (task_id,stage_id,task_json,grid,table_name,compute_status,materialization_status,
             artifact,bytes,sha256,populated_groups,rows_evaluated,last_used)
            VALUES(?,?,?,?,?, 'complete',?,?,?,?,?,?,unixepoch())
            ON CONFLICT(task_id) DO UPDATE SET compute_status='complete',
            materialization_status=excluded.materialization_status,artifact=excluded.artifact,bytes=excluded.bytes,
            sha256=excluded.sha256,populated_groups=excluded.populated_groups,
            rows_evaluated=excluded.rows_evaluated,last_used=unixepoch()""",
            (task["task_id"], task["stage_id"], json.dumps(task, sort_keys=True), grid, table,
             "recomputable" if manifest.get("materialization_status")=="recomputable" else "stored",
             manifest["artifact"], manifest["bytes"], manifest["sha256"],
             manifest["populated_groups"], rows_evaluated))

    def touch(self, task_id):
        self.con.execute("UPDATE blocks SET last_used=unixepoch() WHERE task_id=?", (task_id,))

    def stored_bytes(self, stage_id):
        return int(self.con.execute("SELECT coalesce(sum(bytes),0) FROM blocks WHERE stage_id=? AND materialization_status='stored'",(stage_id,)).fetchone()[0])

    def status(self, planned, stage_id):
        completed = self.con.execute("SELECT count(*) FROM blocks WHERE stage_id=? AND compute_status='complete'",(stage_id,)).fetchone()[0]
        stored = self.con.execute("SELECT count(*) FROM blocks WHERE stage_id=? AND materialization_status='stored'",(stage_id,)).fetchone()[0]
        return {"core_complete": True, "mandatory_coverage_complete": completed == planned,
                "materialization_complete_for_policy": completed == planned,
                "completed_tasks": completed, "stored_tasks": stored,
                "recomputable_tasks": completed-stored, "planned_tasks": planned,
                "status": "complete" if completed == planned else "partial"}

    def publish_catalog(self, evidence_id, stage_id):
        tables = {}
        for row in self.con.execute("SELECT table_name,artifact FROM blocks WHERE stage_id=? AND materialization_status='stored' ORDER BY table_name,task_id",(stage_id,)):
            tables.setdefault(row["table_name"], {"files": []})["files"].append(row["artifact"])
        atomic_json(self.root / "evidence" / "catalog.json",
                    {"evidence_id": evidence_id, "tables": tables})

    def pin(self, pin_id, scope_type="all", scope_key=None):
        if scope_type not in {"all","table","task"} or (scope_type!="all" and not scope_key):
            raise ValueError("Invalid query pin scope")
        self.con.execute("""INSERT INTO pins(id,pid,process_start,created,scope_type,scope_key)
            VALUES(?,?,?,unixepoch(),?,?)""",
            (pin_id,os.getpid(),psutil.Process().create_time(),scope_type,scope_key))

    def unpin(self, pin_id):
        self.con.execute("DELETE FROM pins WHERE id=?", (pin_id,))

    def evict_to_budget(self, cache_bytes, evidence_id, stage_id):
        """Publish a new snapshot before deleting least-recently-used cache blocks."""
        self.con.execute("BEGIN IMMEDIATE")
        try:
            for row in self.con.execute("SELECT id,pid,process_start FROM pins"):
                try: live=abs(psutil.Process(row["pid"]).create_time()-row["process_start"])<1
                except psutil.Error: live=False
                if not live:self.con.execute("DELETE FROM pins WHERE id=?",(row["id"],))
            active_pins=[(row["scope_type"],row["scope_key"]) for row in
                         self.con.execute("SELECT scope_type,scope_key FROM pins")]
            total = self.con.execute("SELECT coalesce(sum(bytes),0) FROM blocks WHERE stage_id=? AND materialization_status='stored'",(stage_id,)).fetchone()[0]
            victims = []
            for row in self.con.execute("SELECT task_id,table_name,artifact,bytes FROM blocks WHERE stage_id=? AND materialization_status='stored' ORDER BY CASE WHEN table_name LIKE '%_security_dual' OR table_name LIKE '%_fold_dual' THEN 1 ELSE 0 END,last_used,task_id",(stage_id,)):
                if total <= cache_bytes:
                    break
                if any(kind=="all" or kind=="table" and key==row["table_name"] or
                       kind=="task" and key==row["task_id"] for kind,key in active_pins):
                    continue
                victims.append(dict(row))
                total -= row["bytes"]
            for row in victims:
                self.con.execute("UPDATE blocks SET materialization_status='recomputable',artifact=NULL,bytes=0 WHERE task_id=?", (row["task_id"],))
            if victims:
                self.publish_catalog(evidence_id,stage_id)
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        for row in victims:
            inside(self.root, row["artifact"]).unlink(missing_ok=True)
        return len(victims)
