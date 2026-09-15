from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd


RAW_COLUMNS = {
    "security_id", "symbol", "bar_start_ts_utc", "bar_end_ts_utc", "availability_ts_utc",
    "session_date", "open", "high", "low", "close", "volume", "feed", "adjustment", "ingest_batch_id",
}
RESEARCH_COLUMNS = {"security_id", "bar_start_ts_utc", "research_open", "research_high", "research_low", "research_close", "split_factor", "price_basis"}


@dataclass(frozen=True)
class SnapshotValidation:
    rows: int
    symbols: int
    sessions: int
    minimum_date: str
    maximum_date: str
    duplicate_keys: int
    feed_values: tuple[str, ...]
    adjustment_values: tuple[str, ...]
    fingerprint: str

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def _frame_fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame.sort_values(columns, kind="mergesort")
    hashes = pd.util.hash_pandas_object(ordered[columns], index=False).values.tobytes()
    return sha256(hashes).hexdigest()


def validate_snapshot(raw: pd.DataFrame, research: pd.DataFrame | None = None, required_feed: str = "sip", required_adjustment: str = "raw") -> SnapshotValidation:
    missing = RAW_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError(f"Raw snapshot missing columns: {sorted(missing)}")
    if set(raw.feed.dropna().str.lower()) != {required_feed.lower()}:
        raise ValueError("Production raw snapshot is not exclusively the required feed")
    if set(raw.adjustment.dropna().str.lower()) != {required_adjustment.lower()}:
        raise ValueError("Raw execution snapshot adjustment must be explicit and raw")
    start = pd.to_datetime(raw.bar_start_ts_utc, utc=True)
    end = pd.to_datetime(raw.bar_end_ts_utc, utc=True)
    available = pd.to_datetime(raw.availability_ts_utc, utc=True)
    if not ((end - start) == pd.Timedelta(minutes=1)).all() or not available.eq(end).all():
        raise ValueError("Invalid 1m left-edge/end/availability timestamp contract")
    key = ["security_id", "bar_start_ts_utc"]
    duplicates = int(raw.duplicated(key).sum())
    if duplicates:
        raise ValueError(f"Raw snapshot has {duplicates} duplicate natural keys")
    if research is not None:
        missing_research = RESEARCH_COLUMNS - set(research.columns)
        if missing_research:
            raise ValueError(f"Research snapshot missing columns: {sorted(missing_research)}")
        raw_keys = raw[key].sort_values(key).reset_index(drop=True)
        research_keys = research[key].sort_values(key).reset_index(drop=True)
        if not raw_keys.equals(research_keys):
            raise ValueError("Raw and research price views do not share identical keys")
    dates = pd.to_datetime(raw.session_date)
    return SnapshotValidation(
        rows=len(raw), symbols=raw.security_id.nunique(), sessions=dates.nunique(),
        minimum_date=str(dates.min().date()), maximum_date=str(dates.max().date()), duplicate_keys=duplicates,
        feed_values=tuple(sorted(raw.feed.unique())), adjustment_values=tuple(sorted(raw.adjustment.unique())),
        fingerprint=_frame_fingerprint(raw, key + ["open", "high", "low", "close", "volume", "feed", "adjustment"]),
    )
