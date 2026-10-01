"""One-minute-bar screen for a small frozen set of conditional overnight exits."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(r"D:\AlgoResearch\Quant-Pipeline-V3\runs\v3_comprehensive_20260923")
BASE = ROOT / "research" / "fresh_strategy_competition_20260928" / "quote_replay"
OUT = BASE / "conditional_exit_screen"
BARS = Path(r"D:\AlgoResearch\data\raw\alpaca\market\stocks\bars_1m\feed=sip")
TRAIL_BPS = (25, 50, 100)
TAKE_PROFIT_BPS = (50, 100, 200)
HARD_EXIT_MINUTES = (29, 59)


def cohort() -> tuple[pd.DataFrame, pd.DataFrame]:
    signals = pd.read_parquet(BASE / "signals.parquet")
    detail = pd.read_parquet(BASE / "forced_exit_detail.parquet")
    detail = detail[detail.bps == 5].copy()
    all_attempts = signals.merge(
        detail[["trade_id", "entry_filled", "portfolio_return"]], on="trade_id", how="left"
    )
    all_attempts["symbol"] = all_attempts.symbol.replace({"FB": "META", "CDAY": "DAY"})
    filled = all_attempts[all_attempts.entry_filled].copy()
    filled["entry_execution"] = filled.governed_entry_price.astype(float) * 1.0005
    if len(all_attempts) != 751 or len(filled) != 734:
        raise RuntimeError(f"Unexpected cohort: {len(all_attempts)} / {len(filled)}")
    return all_attempts, filled


def load_bars(filled: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    frames, errors = [], []
    con = duckdb.connect()
    for index, (timestamp, group) in enumerate(filled.groupby("exit_ts", sort=True), 1):
        timestamp = pd.Timestamp(timestamp)
        day = timestamp.strftime("%Y-%m-%d")
        path = BARS / f"year={timestamp.year}" / f"month={timestamp.month:02d}" / f"date={day}" / "*.parquet"
        symbols = pd.DataFrame({"symbol": sorted(group.symbol.unique())})
        try:
            con.register("wanted", symbols)
            frame = con.execute(
                """select b.symbol, cast(b.timestamp as timestamptz) bar_ts,
                          b.open, b.high, b.low, b.close
                   from read_parquet(?) b join wanted using(symbol)
                   where cast(b.timestamp as timestamptz) >= ?
                     and cast(b.timestamp as timestamptz) <= ?
                   order by b.symbol, bar_ts""",
                [str(path), timestamp, timestamp + pd.Timedelta(minutes=59)],
            ).df()
            frame["path_start"] = timestamp
            frames.append(frame)
        except Exception as exc:
            errors.append({"timestamp": timestamp.isoformat(), "error": type(exc).__name__})
        if index % 25 == 0 or index == filled.exit_ts.nunique():
            print(f"BARS {index}/{filled.exit_ts.nunique()} errors={len(errors)}", flush=True)
    con.close()
    return pd.concat(frames, ignore_index=True), errors


def simulate(entry: float, bars: pd.DataFrame, start: pd.Timestamp, gate: str,
             trail: int | None, target_bps: int | None, hard: int) -> tuple:
    b = bars.sort_values("bar_ts").reset_index(drop=True)
    first = b.iloc[0]
    if gate == "overnight_positive":
        qualifies = float(first.open) > entry
        active_index = 0
        if not qualifies:
            return np.nan, "baseline_exit", pd.NaT, np.nan, False
    else:
        decision_cutoff = start + pd.Timedelta(minutes=4)
        before = b[b.bar_ts <= decision_cutoff]
        if before.empty:
            return np.nan, "missing_gate", pd.NaT, np.nan, False
        decision = before.iloc[-1]
        qualifies = float(decision.close) > float(first.open) and float(decision.close) > entry
        active_index = int(before.index[-1]) + 1
        if not qualifies:
            return float(decision.close) / entry - 1, "gate_exit", decision.bar_ts, float(decision.close), False
    active = b.iloc[active_index:]
    active = active[active.bar_ts <= start + pd.Timedelta(minutes=hard)]
    if active.empty:
        return np.nan, "missing_path", pd.NaT, np.nan, True
    target = entry * (1 + target_bps / 10000) if target_bps else np.inf
    highwater = float(active.iloc[0].open)
    for row in active.itertuples():
        stop = highwater * (1 - trail / 10000) if trail else -np.inf
        if trail and float(row.low) <= stop:
            price = min(float(row.open), stop)
            return price / entry - 1, "trailing_stop", row.bar_ts, price, True
        if target_bps and float(row.high) >= target:
            return target / entry - 1, "take_profit", row.bar_ts, target, True
        highwater = max(highwater, float(row.high))
    row = active.iloc[-1]
    return float(row.close) / entry - 1, "hard_exit", row.bar_ts, float(row.close), True


def summarize(frame: pd.DataFrame, attempts_by_day: pd.Series, config: tuple) -> dict:
    gate, style, trail, target, hard = config
    daily = frame.groupby("session_date").strategy_return.sum().div(attempts_by_day).fillna(0)
    cumulative = daily.cumsum()
    monthly = daily.groupby(pd.to_datetime(daily.index).strftime("%Y-%m")).sum()
    late = frame[frame.session_date.astype(str) >= "2025-11-01"]
    return {"gate": gate, "exit_style": style, "trail_bps": trail,
            "take_profit_bps": target, "hard_exit_minutes": hard,
            "mean_filled_trade_bps": frame.strategy_return.mean()*10000,
            "additive_return": daily.sum(), "compounded_return": (1+daily).prod()-1,
            "max_additive_drawdown": (cumulative-cumulative.cummax()).min(),
            "positive_months": int((monthly>0).sum()),
            "late_mean_filled_bps": late.strategy_return.mean()*10000,
            "continued": int(frame.continued.sum()),
            "trailing_stops": int((frame.exit_reason=="trailing_stop").sum()),
            "take_profits": int((frame.exit_reason=="take_profit").sum()),
            "hard_exits": int((frame.exit_reason=="hard_exit").sum())}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    attempts, filled = cohort()
    bars, errors = load_bars(filled)
    bars.to_parquet(OUT / "bars.parquet", index=False)
    paths = {(ts, symbol): g for (ts, symbol), g in bars.groupby(["path_start", "symbol"], sort=False)}
    configs = []
    for gate in ("overnight_positive", "first5_positive"):
        for hard in HARD_EXIT_MINUTES:
            configs.extend((gate, "trail", value, None, hard) for value in TRAIL_BPS)
            configs.extend((gate, "take_profit", None, value, hard) for value in TAKE_PROFIT_BPS)
    attempts_by_day = attempts.groupby("session_date").size()
    details, summaries = [], []
    for config in configs:
        gate, style, trail, target, hard = config
        rows = []
        for row in filled.itertuples():
            path = paths.get((row.exit_ts, row.symbol))
            if path is None or path.empty:
                ret, reason, ts, price, continued = np.nan, "missing_path", pd.NaT, np.nan, False
            else:
                ret, reason, ts, price, continued = simulate(
                    row.entry_execution, path, row.exit_ts, gate, trail, target, hard
                )
            if reason == "baseline_exit":
                ret = float(row.portfolio_return)
            rows.append({"trade_id": row.trade_id, "symbol": row.symbol,
                         "session_date": row.session_date, "strategy_return": ret,
                         "exit_reason": reason, "candidate_exit_ts": ts,
                         "bar_exit_price": price, "continued": continued,
                         "gate": gate, "exit_style": style, "trail_bps": trail,
                         "take_profit_bps": target, "hard_exit_minutes": hard})
        frame = pd.DataFrame(rows)
        details.append(frame)
        summaries.append(summarize(frame, attempts_by_day, config))
    detail = pd.concat(details, ignore_index=True)
    summary = pd.DataFrame(summaries)
    baseline = pd.read_parquet(BASE / "forced_exit_summary.parquet").query("bps == 5").iloc[0]
    summary["delta_additive_vs_baseline"] = summary.additive_return - baseline.additive_daily_return
    detail.to_parquet(OUT / "detail.parquet", index=False)
    summary.to_parquet(OUT / "summary.parquet", index=False)
    manifest = {"status": "complete" if not errors else "partial", "errors": errors,
                "attempts": len(attempts), "filled_entries": len(filled),
                "baseline_additive_return": float(baseline.additive_daily_return),
                "configurations": len(configs), "sealed_periods_accessed": False}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(summary.sort_values("additive_return", ascending=False).to_string(index=False), flush=True)
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
