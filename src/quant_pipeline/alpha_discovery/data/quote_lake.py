from __future__ import annotations

from pathlib import Path
import duckdb
import numpy as np
import pandas as pd


DEFAULT_ROOT = Path("D:/AlgoResearch/data/raw/alpaca/market/stocks/quotes_sip/schema_v1")


def quote_window_coverage(requests: pd.DataFrame, lake_root: str | Path = DEFAULT_ROOT, window_seconds: int = 10) -> pd.Series:
    result = pd.Series(False, index=requests.index, dtype=bool); catalog = Path(lake_root) / "quote_lake.duckdb"
    if requests.empty or not catalog.exists(): return result
    req = requests[["session_date", "symbol", "request_ts"]].copy(); req["request_row"] = np.arange(len(req)); req["session_date"] = pd.to_datetime(req.session_date).dt.date
    req["symbol"] = req.symbol.astype(str).str.upper(); req["request_ts"] = pd.to_datetime(req.request_ts, utc=True); req["window_end_ts"] = req.request_ts + pd.Timedelta(seconds=window_seconds)
    with duckdb.connect(str(catalog), read_only=True) as connection:
        connection.register("requested_windows", req)
        covered = connection.execute("""SELECT r.request_row FROM requested_windows r WHERE EXISTS (SELECT 1 FROM sip_quote_coverage c WHERE c.session_date=r.session_date AND c.symbol=r.symbol AND c.feed='sip' AND c.download_complete AND c.window_start_ts<=r.request_ts AND c.window_end_ts>=r.window_end_ts)""").fetchnumpy()["request_row"]
    result.iloc[covered] = True; return result


def load_quote_windows(requests: pd.DataFrame, lake_root: str | Path = DEFAULT_ROOT, window_seconds: int = 10) -> pd.DataFrame | None:
    coverage = quote_window_coverage(requests, lake_root, window_seconds)
    if not coverage.all(): return None
    req = requests[["session_date", "symbol", "request_ts"]].drop_duplicates().copy(); req["session_date"] = pd.to_datetime(req.session_date).dt.date
    req["symbol"] = req.symbol.astype(str).str.upper(); req["request_ts"] = pd.to_datetime(req.request_ts, utc=True); req["window_end_ts"] = req.request_ts + pd.Timedelta(seconds=window_seconds)
    with duckdb.connect(str(Path(lake_root) / "quote_lake.duckdb"), read_only=True) as connection:
        connection.register("requested_windows", req)
        frame = connection.execute("""SELECT r.request_ts,q.symbol,q.quote_ts,q.bid_price,q.ask_price,q.bid_size,q.ask_size FROM requested_windows r JOIN sip_quotes q ON q.session_date=r.session_date AND q.symbol=r.symbol AND q.quote_ts>=r.request_ts AND q.quote_ts<r.window_end_ts ORDER BY r.request_ts,q.symbol,q.quote_ts""").fetchdf()
    return frame
