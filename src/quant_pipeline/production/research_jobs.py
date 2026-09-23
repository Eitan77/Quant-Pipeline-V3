from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .evidence_identity import digest


class JobStore:
    """Durable local queue. Worker lifetime must be protected by worker_lock()."""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0, cancel INTEGER NOT NULL DEFAULT 0,
            result TEXT, error TEXT)''')
        self.con.execute('''CREATE TABLE IF NOT EXISTS journal (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
            event TEXT NOT NULL, spec TEXT, outcome TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    def submit(self, spec):
        # Caller validates kind, discovery scope, definitions and resource limits first.
        job_id = digest(spec)
        self.con.execute("INSERT OR IGNORE INTO jobs(id,spec,status) VALUES(?,?,'queued')",
                         (job_id, json.dumps(spec, sort_keys=True, allow_nan=False)))
        self.con.execute("INSERT INTO journal(job_id,event,spec) VALUES(?,'submitted',?)",
                         (job_id,json.dumps(spec,sort_keys=True,allow_nan=False)))
        return job_id

    def claim(self):
        self.con.execute("BEGIN IMMEDIATE")
        try:
            row = self.con.execute("SELECT * FROM jobs WHERE status='queued' AND cancel=0 ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                self.con.execute("COMMIT")
                return None
            self.con.execute("UPDATE jobs SET status='running',attempt=attempt+1 WHERE id=?", (row["id"],))
            self.con.execute("COMMIT")
            return row["id"], row["attempt"] + 1, json.loads(row["spec"])
        except Exception:
            self.con.execute("ROLLBACK")
            raise

    def cancelled(self, job_id):
        return bool(self.con.execute("SELECT cancel FROM jobs WHERE id=?", (job_id,)).fetchone()[0])

    def cancel(self, job_id):
        changed=self.con.execute("UPDATE jobs SET cancel=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE id=?", (job_id,)).rowcount
        if changed:self.con.execute("INSERT INTO journal(job_id,event) VALUES(?,'cancel_requested')",(job_id,))

    def finish(self, job_id, attempt, *, result=None, error=None):
        outcome=result.get("status") if isinstance(result,dict) else None
        status = "cancelled" if self.cancelled(job_id) else "failed" if error else outcome if outcome in {"blocked_storage","blocked_memory","unavailable"} else "complete"
        changed = self.con.execute(
            "UPDATE jobs SET status=?,result=?,error=? WHERE id=? AND attempt=? AND status='running'",
            (status, json.dumps(result, allow_nan=False), error, job_id, attempt),
        ).rowcount
        if changed != 1:
            raise RuntimeError("Stale completion or invalid job state")
        self.con.execute("INSERT INTO journal(job_id,event,outcome) VALUES(?,'finished',?)",
                         (job_id,json.dumps({"status":status,"attempt":attempt,"result":result,"error":error},allow_nan=False)))

    def recover_after_lock(self):
        # Only call after obtaining the exclusive OS worker lock, never by timeout alone.
        self.con.execute("UPDATE jobs SET status=CASE WHEN cancel=1 THEN 'cancelled' ELSE 'queued' END WHERE status='running'")

    def retry(self, job_id):
        changed=self.con.execute("UPDATE jobs SET status='queued',cancel=0,error=NULL,result=NULL WHERE id=? AND status IN ('failed','cancelled','blocked_storage','blocked_memory','unavailable')", (job_id,)).rowcount
        if changed:self.con.execute("INSERT INTO journal(job_id,event) VALUES(?,'retried')",(job_id,))

    def journal(self, limit=100):
        if not 1<=limit<=1000:raise ValueError("Journal limit out of range")
        return [dict(row) for row in self.con.execute("SELECT * FROM journal ORDER BY event_id DESC LIMIT ?",(limit,))]

    def get(self, job_id):
        row = self.con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def close(self):
        self.con.close()


def worker_lock(path):
    """Context manager with Windows and POSIX exclusion; OS releases it on exit."""
    from contextlib import contextmanager
    import os

    @contextmanager
    def acquire():
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with path_obj.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return acquire()


def run_one(store, handlers):
    claimed = store.claim()
    if claimed is None:
        return False
    job_id, attempt, spec = claimed
    try:
        result = handlers[spec["kind"]](spec, lambda: store.cancelled(job_id))
    except Exception as error:
        store.finish(job_id, attempt, error=f"{type(error).__name__}: {error}")
    else:
        store.finish(job_id, attempt, result=result)
    return True
