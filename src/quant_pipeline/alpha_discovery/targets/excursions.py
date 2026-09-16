from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


def trade_path_diagnostics(path_prices: pd.Series, entry_price: float) -> dict[str, float]:
    returns = path_prices.astype(float) / float(entry_price) - 1.0
    if returns.empty or not np.isfinite(entry_price) or entry_price <= 0:
        return {name: np.nan for name in ("mfe", "mae", "time_to_mfe", "time_to_mae", "terminal_return", "mfe_minus_terminal", "recovery_after_mae")}
    mfe_index, mae_index = int(np.nanargmax(returns)), int(np.nanargmin(returns))
    terminal = float(returns.iloc[-1])
    return {"mfe": float(returns.iloc[mfe_index]), "mae": float(returns.iloc[mae_index]),
            "time_to_mfe": mfe_index + 1, "time_to_mae": mae_index + 1, "terminal_return": terminal,
            "mfe_minus_terminal": float(returns.iloc[mfe_index] - terminal),
            "recovery_after_mae": float(terminal - returns.iloc[mae_index])}


def actual_trade_path_diagnostics(windows: pd.DataFrame, *, duckdb_path: str,
                                  bars_table: str, discovery_end: str,
                                  temp_directory: Path, memory_limit: str = "512MB") -> pd.DataFrame:
    """Compute exact reference-window paths; shared by legacy and V3 dossiers."""
    entry_ts=pd.to_datetime(windows.entry_ts,utc=True,errors="coerce"); exit_ts=pd.to_datetime(windows.exit_ts,utc=True,errors="coerce")
    if len(windows) and ((exit_ts-entry_ts)<=pd.Timedelta(minutes=1)).fillna(False).all():
        entry=pd.to_numeric(windows.entry_price,errors="coerce").to_numpy(float); exit_price=pd.to_numeric(windows.exit_price,errors="coerce").to_numpy(float)
        valid=np.isfinite(entry)&(entry>0)&np.isfinite(exit_price); maximum=np.maximum(entry,exit_price); minimum=np.minimum(entry,exit_price)
        return pd.DataFrame({"path_count":np.where(valid,2,1),"mfe":np.where(valid,maximum/entry-1,np.nan),
            "mae":np.where(valid,minimum/entry-1,np.nan),"time_to_mfe":np.where(valid,np.where(exit_price>entry,2,1),np.nan),
            "time_to_mae":np.where(valid,np.where(exit_price<entry,2,1),np.nan),"terminal_return":np.where(valid,exit_price/entry-1,np.nan),
            "mfe_minus_terminal":np.where(valid,(maximum-exit_price)/entry,np.nan),"recovery_after_mae":np.where(valid,(exit_price-minimum)/entry,np.nan)},index=windows.index)
    import duckdb
    query_windows=windows.reset_index(drop=True).copy(); query_windows["window_id"]=np.arange(len(query_windows),dtype=np.int64)
    temp_directory=Path(temp_directory); temp_directory.mkdir(parents=True,exist_ok=True)
    with duckdb.connect(duckdb_path,read_only=True) as connection:
        connection.execute(f"SET temp_directory='{temp_directory.as_posix().replace(chr(39),chr(39)*2)}'"); connection.execute(f"SET memory_limit='{memory_limit}'")
        connection.register("candidate_windows",query_windows[["window_id","security_id","entry_ts","exit_ts"]]); connection.register("window_prices",query_windows[["window_id","entry_price","exit_price"]])
        result=connection.execute(f"""WITH bar_points AS (
          SELECT w.window_id,row_number() OVER(PARTITION BY w.window_id ORDER BY b.bar_start_ts_utc) seq,b.bar_start_ts_utc,b.close::DOUBLE price
          FROM candidate_windows w JOIN {bars_table} b ON b.security_id=w.security_id AND b.bar_start_ts_utc>=w.entry_ts AND b.bar_start_ts_utc<w.exit_ts
          WHERE b.session_date<=DATE '{discovery_end}'), bar_stats AS (
          SELECT window_id,count(*) bar_count,arg_max(price,bar_start_ts_utc) last_price FROM bar_points GROUP BY window_id), path_points AS (
          SELECT window_id,0::BIGINT seq,entry_price::DOUBLE price FROM window_prices UNION ALL SELECT window_id,seq,price FROM bar_points UNION ALL
          SELECT w.window_id,coalesce(s.bar_count,0)+1,w.exit_price::DOUBLE FROM window_prices w LEFT JOIN bar_stats s USING(window_id)
          WHERE isfinite(w.exit_price) AND (coalesce(s.bar_count,0)=0 OR s.last_price IS DISTINCT FROM w.exit_price)), extrema AS (
          SELECT *,max(price) OVER(PARTITION BY window_id) max_price,min(price) OVER(PARTITION BY window_id) min_price FROM path_points), reduced AS (
          SELECT window_id,count(*) path_count,max(max_price) max_price,min(min_price) min_price,min(seq) FILTER(WHERE price=max_price)+1 time_to_mfe,
          min(seq) FILTER(WHERE price=min_price)+1 time_to_mae,arg_max(price,seq) terminal_price FROM extrema GROUP BY window_id)
          SELECT w.window_id,r.path_count,CASE WHEN isfinite(w.entry_price) AND w.entry_price>0 THEN r.max_price/w.entry_price-1 END mfe,
          CASE WHEN isfinite(w.entry_price) AND w.entry_price>0 THEN r.min_price/w.entry_price-1 END mae,r.time_to_mfe,r.time_to_mae,
          CASE WHEN isfinite(w.entry_price) AND w.entry_price>0 THEN r.terminal_price/w.entry_price-1 END terminal_return,
          CASE WHEN isfinite(w.entry_price) AND w.entry_price>0 THEN (r.max_price-r.terminal_price)/w.entry_price END mfe_minus_terminal,
          CASE WHEN isfinite(w.entry_price) AND w.entry_price>0 THEN (r.terminal_price-r.min_price)/w.entry_price END recovery_after_mae
          FROM window_prices w LEFT JOIN reduced r USING(window_id) ORDER BY w.window_id""").fetchdf()
    return result.drop(columns="window_id").set_axis(windows.index)
