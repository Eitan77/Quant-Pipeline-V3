"""Explicit discovery-state replay using governed target exits and raw opens."""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from quant_pipeline.alpha_discovery.execution.candidate_backtest import (
    ExecutionAssumptions, aggregate_returns, replay_candidate_signals)
from .diagnostics import prepare_state_events
from .evidence_identity import atomic_json, digest


def prepare_replay_inputs(root,reader_manifest,spec,*,cancelled=lambda:False):
    root=Path(root)
    if spec.get("direction") not in (-1,1):raise ValueError("Replay requires an explicit long/short direction")
    basis=spec.get("return_basis","raw")
    if basis not in {"raw","benchmark_adjusted","beta_residual"}:
        raise ValueError("Unsupported replay return basis")
    if basis!="raw" and f"__{basis}__" not in spec["target_id"]:
        raise ValueError("Requested return basis disagrees with target identity")
    events,event_id=prepare_state_events(root,reader_manifest,spec,cancelled=cancelled)
    ledger=root/"cache"/"targets"/f"{spec['grid']}.parquet"
    if not ledger.exists():return None,{"status":"unavailable","reason":"Exact governed target ledger is absent"}
    beta_column="t.beta_prior" if "beta_prior" in pq.read_schema(ledger).names else "CAST(NULL AS DOUBLE)"
    step=5 if spec["grid"]=="intraday_5m" else 1 if spec["grid"]=="intraday_1m" else None
    if step is None and spec["grid"] not in {"daily_close","preclose_1555"}:
        return None,{"status":"unavailable","reason":"Replay episode rule is undefined for this grid"}
    with duckdb.connect() as con:
        frame=con.execute(f"""SELECT e.observation_id,e.security_id,e.session_date,e.decision_ts,
            t.entry_ts governed_entry_ts,t.entry_price governed_entry_price,
            t.exit_ts,t.exit_price,{beta_column} beta_prior,t.target_basis
            FROM read_parquet(?) e LEFT JOIN read_parquet(?) t
              ON e.observation_id=t.observation_id AND t.target_id=?
            ORDER BY e.security_id,e.session_date,e.decision_ts""",
            [str(events),str(ledger),spec["target_id"]]).fetchdf()
    if frame.empty:return frame,{"status":"complete","event_id":event_id,"episodes":0}
    if frame.observation_id.duplicated().any():raise ValueError("Duplicate target ledger rows for a replay observation")
    if set(frame.target_basis.dropna())!={basis}:raise ValueError("Requested return basis disagrees with target ledger")
    if step is None:
        episode=pd.Series(True,index=frame.index)
    else:
        prior=frame.groupby(["security_id","session_date"],sort=False).decision_ts.shift()
        episode=(prior.isna() | (frame.decision_ts-prior != pd.Timedelta(minutes=step)))
    starts=frame.loc[episode].copy()
    starts=starts.sort_values(["decision_ts","security_id","observation_id"],kind="stable")
    # Exact exits define non-overlapping opportunities, including cross-session holds.
    next_allowed={};keep=[]
    for row in starts.itertuples():
        if cancelled():raise InterruptedError("Replay preparation cancelled")
        if pd.isna(row.exit_ts):
            keep.append(True)
            continue
        allowed=next_allowed.get(row.security_id)
        accepted=allowed is None or row.decision_ts>=allowed
        keep.append(accepted)
        if accepted:next_allowed[row.security_id]=row.exit_ts
    signals=starts.loc[keep].copy()
    master=Path(__file__).resolve().parents[3]/"reference"/"security_master.parquet"
    symbols=pd.read_parquet(master,columns=["security_id","symbol"]).drop_duplicates("security_id")
    signals=signals.merge(symbols,on="security_id",how="left",validate="many_to_one")
    if signals.symbol.isna().any():raise ValueError("PIT security has no governed raw-bar symbol mapping")
    signals["candidate_key"]=digest({"evidence":reader_manifest["evidence_id"],"spec":spec})
    signals["local_direction"]=int(spec["direction"])
    signals["return_basis"]=basis
    for column in ("benchmark_entry_ts","benchmark_exit_ts"):signals[column]=pd.NaT
    for column in ("benchmark_entry_price","benchmark_exit_price"):signals[column]=np.nan
    benchmark_id=None
    if basis!="raw":
        benchmark_symbol=spec.get("benchmark_symbol")
        if not benchmark_symbol:raise ValueError("Hedged replay requires the governed benchmark_symbol")
        benchmark=symbols.loc[symbols.symbol.eq(benchmark_symbol),"security_id"]
        if len(benchmark)!=1:raise ValueError("Benchmark symbol has no unique governed security ID")
        benchmark_id=benchmark.iloc[0]
        raw_target=spec["target_id"].replace(f"__{basis}__","__raw__")
        key="decision_ts" if spec["grid"].startswith("intraday") else "session_date"
        with duckdb.connect() as con:
            legs=con.execute(f"""SELECT {key},entry_ts benchmark_entry_ts,
                entry_price benchmark_entry_price,exit_ts benchmark_exit_ts,
                exit_price benchmark_exit_price FROM read_parquet(?)
                WHERE security_id=? AND target_id=?""",
                [str(ledger),benchmark_id,raw_target]).fetchdf()
        if legs[key].duplicated().any():raise ValueError("Duplicate governed benchmark target window")
        signals=signals.drop(columns=["benchmark_entry_ts","benchmark_entry_price",
                                      "benchmark_exit_ts","benchmark_exit_price"]).merge(
            legs,on=key,how="left",validate="many_to_one")
    signals["beta_prior"]=signals.beta_prior.astype(float)
    return signals,{"status":"complete","event_id":event_id,"episodes":len(starts),
                    "independent_opportunities":len(signals),"benchmark_security_id":benchmark_id}


def _raw_opens(machine,signals,*,root=None,cancelled=lambda:False):
    """Read only symbol/date/windows that the governed signals can enter."""
    catalog=Path(machine["source_catalog"])
    if not catalog.exists():raise FileNotFoundError(catalog)
    eligible=signals[signals.governed_entry_ts.notna() & signals.exit_ts.notna()]
    windows=eligible[["security_id","symbol","governed_entry_ts","exit_ts"]].copy()
    if signals.attrs.get("benchmark_security_id") is not None:
        bench=eligible[["benchmark_entry_ts","benchmark_exit_ts"]].copy()
        bench["security_id"]=signals.attrs["benchmark_security_id"]
        bench["symbol"]=signals.attrs["benchmark_symbol"]
        windows=pd.concat([windows,bench.rename(columns={"benchmark_entry_ts":"governed_entry_ts",
                                                      "benchmark_exit_ts":"exit_ts"})],ignore_index=True)
    windows=windows[windows.governed_entry_ts.notna() & windows.exit_ts.notna()]
    if windows.empty:return {}
    windows["entry_date"]=windows.governed_entry_ts.dt.date
    windows=windows.groupby(["security_id","symbol","entry_date"],as_index=False,sort=False).agg(
        lower=("governed_entry_ts","min"),upper=("exit_ts","max"))
    windows["exit_date"]=windows.upper.dt.date
    if cancelled():raise InterruptedError("Replay raw-window acquisition cancelled")
    snapshot=Path(root)/"snapshot"/"bars_1m_raw.parquet" if root is not None else None
    with duckdb.connect(str(catalog),read_only=True) as con:
        con.register("requested_windows",windows)
        if snapshot is not None and snapshot.exists():
            rows=con.execute("""SELECT DISTINCT w.security_id,
                CAST(b.bar_start_ts_utc AS VARCHAR),b.open
                FROM read_parquet(?) b JOIN requested_windows w
                  ON b.security_id=w.security_id
                 AND CAST(b.session_date AS DATE) BETWEEN w.entry_date AND w.exit_date
                 AND b.bar_start_ts_utc>=w.lower AND b.bar_start_ts_utc<w.upper
                WHERE lower(b.feed)='sip' AND lower(b.adjustment)='raw'
                ORDER BY w.security_id,2""",[str(snapshot)]).fetchall()
        else:
            rows=con.execute("""SELECT DISTINCT w.security_id,b.timestamp,b.open
                FROM bars_1m b JOIN requested_windows w
                  ON b.symbol=w.symbol AND b.date BETWEEN w.entry_date AND w.exit_date
                 AND try_cast(b.timestamp AS TIMESTAMPTZ)>=w.lower
                 AND try_cast(b.timestamp AS TIMESTAMPTZ)<w.upper
                WHERE lower(b.feed)='sip' AND lower(b.adjustment)='raw'
                ORDER BY w.security_id,b.timestamp""").fetchall()
    if cancelled():raise InterruptedError("Replay raw-window acquisition cancelled")
    prices={}
    for security,stamp,price in rows:
        prices.setdefault(str(security),[]).append((stamp,float(price)))
    return {security:pd.Series([value for _,value in parts],
                               index=pd.to_datetime([stamp for stamp,_ in parts],utc=True))
            for security,parts in prices.items()}


def run_backtest(root,reader_manifest,machine,spec,*,cancelled=lambda:False):
    root=Path(root)
    signals,preparation=prepare_replay_inputs(root,reader_manifest,spec,cancelled=cancelled)
    if preparation["status"]!="complete":return preparation
    assumptions=ExecutionAssumptions(
        cost_bps_per_side=float(spec.get("cost_bps_per_side",5)),
        slippage_bps_per_side=float(spec.get("slippage_bps_per_side",2)),
        additional_entry_delay_minutes=int(spec.get("additional_entry_delay_minutes",1)))
    signals.attrs["benchmark_security_id"]=preparation.get("benchmark_security_id")
    signals.attrs["benchmark_symbol"]=spec.get("benchmark_symbol")
    prices=_raw_opens(machine,signals,root=root,cancelled=cancelled) if len(signals) else {}
    trades,rejected=replay_candidate_signals(signals,prices,assumptions,
        benchmark_security_id=preparation.get("benchmark_security_id"))
    if cancelled():raise InterruptedError("Replay cancelled before publication")
    identity=digest({"evidence":reader_manifest["evidence_id"],"spec":spec,"replay_schema":1})
    directory=root/"research"/"experiments"/identity
    directory.mkdir(parents=True,exist_ok=True)
    trades.to_parquet(directory/"trades.parquet",index=False)
    rejected.to_parquet(directory/"rejected.parquet",index=False)
    aggregate=aggregate_returns(trades,"net_trade_return")
    aggregate={key:(float(value) if len(trades) and np.isfinite(value) else None)
               for key,value in aggregate.items()}
    summary={"status":"complete","experiment_id":identity,"evidence_id":reader_manifest["evidence_id"],
             "preparation":preparation,"signals":len(signals),"executed_trades":len(trades),
             "rejected_signals":len(rejected),"isolated_candidate_diagnostic":aggregate,
             "rejection_reasons":{str(key):int(value) for key,value in
                                  rejected.rejection_reason.value_counts().items()} if len(rejected) else {},
             "assumptions":assumptions.__dict__,"portfolio_return_claim":False,
             "trades":"trades.parquet","rejections":"rejected.parquet"}
    atomic_json(directory/"summary.json",summary)
    return {"status":"complete","result":(directory/"summary.json").relative_to(root).as_posix()}
