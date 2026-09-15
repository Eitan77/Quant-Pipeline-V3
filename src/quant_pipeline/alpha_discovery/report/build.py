from __future__ import annotations

from pathlib import Path
from typing import Any


REPORTS = ("RUN_SUMMARY.md",)


def build_reports(root: str | Path, context: dict[str, Any]) -> list[Path]:
    output = Path(root); output.mkdir(parents=True, exist_ok=True); paths = []
    for name in REPORTS:
        title = name.removesuffix(".md").replace("_", " ").title()
        body = [f"# {title}", ""] + [f"- {key}: {value}" for key, value in sorted(context.items())] + [""]
        path = output / name; path.write_text("\n".join(body), encoding="utf-8"); paths.append(path)
    return paths
