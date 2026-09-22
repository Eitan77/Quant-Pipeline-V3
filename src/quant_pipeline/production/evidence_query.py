from __future__ import annotations

import json
import re

import duckdb

from .evidence_identity import inside


def open_catalog(root, manifest_path, *, memory_gib=4, threads=2):
    """Manifest is a committed snapshot listing exact files, never wildcard directories."""
    if not 1 <= memory_gib <= 24 or not 1 <= threads <= 16:
        raise ValueError("Query resource limits out of range")
    manifest = json.loads(inside(root, manifest_path).read_text(encoding="utf-8"))
    con = duckdb.connect()
    try:
        con.execute(f"SET memory_limit='{int(memory_gib)}GiB'")
        con.execute(f"SET threads={int(threads)}")
        for name, entry in manifest["tables"].items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise ValueError("Invalid catalog name")
            if not entry["files"]:
                raise ValueError("Use a typed empty Parquet file for an empty published table")
            paths = [str(inside(root, p)) for p in entry["files"]]
            con.read_parquet(paths, union_by_name=True).create_view(name)
        return con, manifest
    except Exception:
        con.close()
        raise


def group_cells(con, *, table, pair_id, target_id, resolution, group_id,
                after_cell=-1, limit=100):
    """Exact stored subgroup lookup; caller supplies coverage if the row is absent."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", table):
        raise ValueError("Invalid table")
    if resolution not in (3, 5, 10) or not 1 <= limit <= 1000 or after_cell < -1:
        raise ValueError("Invalid page request")
    parameters = [pair_id, target_id, resolution, group_id]
    where = "pair_id=? AND target_id=? AND resolution=? AND group_id=?"
    matches = con.execute(f'SELECT count(*) FROM "{table}" WHERE {where}', parameters).fetchone()[0]
    if matches > 1:
        raise ValueError("Duplicate authoritative subgroup rows")
    if not matches:
        return {"status": "absent_requires_coverage_check", "rows": [], "next_cell": None}
    sql = f'''WITH selected AS (
        SELECT * FROM "{table}" WHERE {where}
    ), expanded AS (
        SELECT cell_index, list_extract(counts, cell_index+1) AS n,
               list_extract(sums, cell_index+1) AS sum_y,
               list_extract(sumsq, cell_index+1) AS sum_y2,
               list_sum(counts) AS eligible_n
        FROM selected, UNNEST(range(0, len(counts))) AS cells(cell_index)
    ) SELECT *, 10000.0*sum_y/nullif(n,0) AS raw_mean_bps,
                  n::DOUBLE/nullif(eligible_n,0) AS frequency
      FROM expanded WHERE cell_index>? ORDER BY cell_index LIMIT ?'''
    cursor = con.execute(sql, parameters + [after_cell, limit + 1])
    names = [x[0] for x in cursor.description]
    rows = [dict(zip(names, values)) for values in cursor.fetchall()]
    more = len(rows) > limit
    rows = rows[:limit]
    return {"status": "available", "rows": rows,
            "next_cell": rows[-1]["cell_index"] if more else None}
