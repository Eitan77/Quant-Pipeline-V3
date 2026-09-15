from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import duckdb
import pandas as pd

from ..governance.access import AccessGate


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value


@dataclass(frozen=True)
class DuckDBSource:
    path: Path
    gate: AccessGate

    def read_table(self, table: str, columns: tuple[str, ...], timestamp_column: str = "session_date", where: str | None = None) -> pd.DataFrame:
        table_sql = _identifier(table)
        selected = list(columns)
        added_timestamp = timestamp_column not in selected
        if added_timestamp:
            selected.append(timestamp_column)
        column_sql = ", ".join(_identifier(column) for column in selected)
        predicates = [self.gate.sql_predicate(_identifier(timestamp_column))]
        if where:
            if ";" in where:
                raise ValueError("SQL predicate may not contain a statement separator")
            predicates.append(f"({where})")
        query = f"SELECT {column_sql} FROM {table_sql} WHERE {' AND '.join(predicates)}"
        with duckdb.connect(str(self.path), read_only=True) as connection:
            frame = connection.execute(query).fetchdf()
        self.gate.assert_frame(frame, timestamp_column)
        if added_timestamp:
            frame = frame.drop(columns=[timestamp_column])
        return frame

    def table_columns(self, table: str) -> set[str]:
        with duckdb.connect(str(self.path), read_only=True) as connection:
            rows = connection.execute(f"DESCRIBE {_identifier(table)}").fetchall()
        return {row[0] for row in rows}

    def read_dimension(self, table: str, columns: tuple[str, ...]) -> pd.DataFrame:
        """Read a non-temporal reference table after identifier validation."""
        table_sql = _identifier(table)
        column_sql = ", ".join(_identifier(column) for column in columns)
        with duckdb.connect(str(self.path), read_only=True) as connection:
            return connection.execute(f"SELECT {column_sql} FROM {table_sql}").fetchdf()
