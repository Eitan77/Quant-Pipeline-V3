from pathlib import Path

import duckdb

from quant_pipeline.production.outputs import DUAL_TREES


def build_resolution_diagnostics(*, run_root: Path, research: dict) -> Path:
    """Union the canonical resolution trees without materializing them in RAM."""
    run_root = Path(run_root)
    out = run_root / "v3_diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    destination = out / "dual_resolution_summary.parquet"
    queries = []
    for resolution in research["resolutions"]:
        tree = run_root / DUAL_TREES[int(resolution)]
        if not list(tree.rglob("*.parquet")):
            raise RuntimeError(f"Missing dual output for r{resolution}: {tree}")
        source = str(tree / "**" / "*.parquet").replace("'", "''")
        queries.append(
            f"SELECT *, {int(resolution)}::INTEGER AS v3_resolution "
            f"FROM read_parquet('{source}', union_by_name=true)"
        )
    sql = " UNION ALL ".join(queries)
    with duckdb.connect() as con:
        con.execute(
            f"COPY ({sql}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(destination)],
        )
        found = {
            int(row[0])
            for row in con.execute(
                "SELECT DISTINCT v3_resolution FROM read_parquet(?)", [str(destination)]
            ).fetchall()
        }
    expected = {int(value) for value in research["resolutions"]}
    if found != expected:
        raise RuntimeError(f"Resolution integrity failure: expected {expected}, got {found}")
    return destination
