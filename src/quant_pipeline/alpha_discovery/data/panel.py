from __future__ import annotations

import numpy as np
import pandas as pd


_MARKET_TZ = "America/New_York"


def regular_session_mask(frame: pd.DataFrame) -> pd.Series:
    """NYSE regular-session one-minute bars (09:30 inclusive, 16:00 exclusive)."""
    local_start = pd.to_datetime(frame.bar_start_ts_utc, utc=True).dt.tz_convert(_MARKET_TZ)
    minutes = local_start.dt.hour * 60 + local_start.dt.minute
    return minutes.ge(9 * 60 + 30) & minutes.lt(16 * 60)


def _regular_bars(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.loc[regular_session_mask(frame)].copy()
    if output.empty:
        raise ValueError("No regular-session bars remain after the 09:30-16:00 ET filter")
    return output


def _benchmark_session_close(frame: pd.DataFrame, benchmark_symbol: str) -> pd.DataFrame:
    benchmark = frame.loc[frame.symbol.eq(benchmark_symbol)]
    if benchmark.empty:
        raise ValueError(f"Benchmark {benchmark_symbol} is required to define canonical session closes")
    return (benchmark.groupby("session_date", observed=True).availability_ts_utc.max()
            .rename("canonical_close_ts").reset_index())


def _research_price_frame(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.copy()
    for name in ("open", "high", "low", "close"):
        research = f"research_{name}"
        if research not in frame:
            raise ValueError(f"Feature panel requires {research}")
        frame[f"execution_{name}"] = frame[name]
        frame[name] = frame[research].astype(float)
    if "vwap" in frame:
        factor = frame.get("split_factor", 1.0)
        frame["vwap"] = frame.vwap.astype(float) / pd.Series(factor, index=frame.index).replace(0, np.nan)
    return frame


def _session_metrics(group: pd.DataFrame) -> pd.Series:
    group = group.sort_values("bar_start_ts_utc", kind="mergesort")
    open_price = float(group.open.iloc[0]); close_price = float(group.close.iloc[-1])
    volume = group.volume.astype(float); typical = (group.high + group.low + group.close) / 3
    result: dict[str, float] = {
        "session_open": open_price, "session_close": close_price,
        "session_high": float(group.high.max()), "session_low": float(group.low.min()),
        "session_volume": float(volume.sum()),
        "session_trade_count": float(group.trade_count.sum()) if "trade_count" in group else np.nan,
        "session_vwap": float(np.average(group.vwap, weights=volume)) if "vwap" in group and volume.sum() > 0 else float(np.average(typical, weights=volume)),
        "largest_1m_volume_share_session": float(volume.max() / volume.sum()) if volume.sum() > 0 else np.nan,
    }
    five = np.add.reduceat(volume.to_numpy(), np.arange(0, len(volume), 5))
    result["largest_5m_volume_share_session"] = float(five.max() / volume.sum()) if volume.sum() > 0 else np.nan
    previous_sign = np.sign(group.close.to_numpy() - group.get("vwap", typical).to_numpy())
    result["vwap_cross_count"] = float(np.mean(previous_sign[1:] != previous_sign[:-1])) if len(previous_sign) > 1 else np.nan
    result["time_above_vwap"] = float(np.mean(previous_sign > 0))
    for horizon in (5, 10, 15, 30, 60):
        if len(group) >= horizon:
            opening = group.iloc[:horizon]
            result[f"opening_return_{horizon}m"] = float(opening.close.iloc[-1] / open_price - 1)
            result[f"opening_range_pct_{horizon}m"] = float((opening.high.max() - opening.low.min()) / open_price) if open_price else np.nan
            result[f"opening_volume_{horizon}m"] = float(opening.volume.sum())
            result[f"gap_fill_price_{horizon}m"] = float(opening.close.iloc[-1])
            anchor = float(group.close.iloc[-horizon - 1]) if len(group) > horizon else open_price
            result[f"closing_return_{horizon}m"] = float(close_price / anchor - 1) if anchor else np.nan
            result[f"closing_volume_share_{horizon}m"] = float(group.volume.iloc[-horizon:].sum() / volume.sum()) if volume.sum() > 0 else np.nan
    local_end = pd.to_datetime(group.bar_end_ts_utc, utc=True).dt.tz_convert("America/New_York")
    session_date = local_end.dt.date.iloc[0]
    midday = group.loc[local_end.le(pd.Timestamp(str(session_date) + " 12:00", tz="America/New_York"))]
    midday_price = float(midday.close.iloc[-1]) if not midday.empty else np.nan
    result["midday_price"] = midday_price
    result["open_to_midday_return"] = midday_price / open_price - 1 if open_price and np.isfinite(midday_price) else np.nan
    result["midday_to_close_return"] = close_price / midday_price - 1 if np.isfinite(midday_price) and midday_price else np.nan
    return pd.Series(result)


def build_calculation_panel(bars: pd.DataFrame, decision_grid: str, benchmark_symbol: str = "SPY") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return a causal calculation panel and its emitted decision observations."""
    frame = _research_price_frame(bars)
    frame["bar_start_ts_utc"] = pd.to_datetime(frame.bar_start_ts_utc, utc=True)
    frame["bar_end_ts_utc"] = pd.to_datetime(frame.bar_end_ts_utc, utc=True)
    frame["availability_ts_utc"] = pd.to_datetime(frame.availability_ts_utc, utc=True)
    frame = _regular_bars(frame).sort_values(["security_id", "session_date", "bar_start_ts_utc"], kind="mergesort")
    session_frame = frame
    session_schedule = _benchmark_session_close(session_frame, benchmark_symbol)
    if decision_grid.startswith("intraday"):
        calculation = frame.copy()
        session_groups = calculation.groupby(["security_id", "session_date"], sort=False, observed=True)
        calculation["session_open"] = session_groups.open.transform("first")
        if decision_grid == "intraday_5m":
            emit = calculation.availability_ts_utc.dt.minute.mod(5).eq(0)
        else:
            emit = pd.Series(True, index=calculation.index)
    else:
        if decision_grid == "preclose_1555":
            local = frame.availability_ts_utc.dt.tz_convert("America/New_York")
            frame = frame.loc[(local.dt.hour < 15) | ((local.dt.hour == 15) & (local.dt.minute <= 55))].copy()
        elif decision_grid != "daily_close":
            raise ValueError(f"Unknown decision grid: {decision_grid}")
        keys = ["security_id", "symbol", "session_date"]
        grouped = frame.groupby(keys, sort=False, observed=True)
        calculation = grouped.agg(
            bar_start_ts_utc=("bar_start_ts_utc", "first"), bar_end_ts_utc=("bar_end_ts_utc", "last"),
            availability_ts_utc=("availability_ts_utc", "last"), open=("open", "first"),
            high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
            trade_count=("trade_count", "sum"), split_factor=("split_factor", "last"),
        ).reset_index()
        metrics = grouped.apply(_session_metrics, include_groups=False).reset_index()
        if metrics.duplicated(keys).any():
            metric_columns=[column for column in metrics if column not in keys]
            conflicts=metrics.groupby(keys,observed=True)[metric_columns].nunique(dropna=False).gt(1).any(axis=1)
            if conflicts.any(): raise ValueError("Session metrics contain conflicting duplicate group keys")
            metrics=metrics.drop_duplicates(keys,keep="first")
        calculation = calculation.merge(metrics, on=keys, how="left", validate="one_to_one")
        calculation = calculation.merge(session_schedule, on="session_date", how="inner", validate="many_to_one")
        if decision_grid == "daily_close":
            calculation = calculation.loc[calculation.availability_ts_utc.eq(calculation.canonical_close_ts)].copy()
        else:
            local_decision = calculation.availability_ts_utc.dt.tz_convert(_MARKET_TZ)
            calculation = calculation.loc[local_decision.dt.strftime("%H:%M").eq("15:55")].copy()
        calculation = calculation.drop(columns="canonical_close_ts")
        calculation["vwap"] = calculation.session_vwap
        emit = pd.Series(True, index=calculation.index)
    session_closes = (session_frame.groupby(["security_id", "session_date"], sort=False, observed=True)
                      .agg(session_final_close=("close", "last"), availability_ts_utc=("availability_ts_utc", "last"))
                      .reset_index().merge(session_schedule, on="session_date", how="inner", validate="many_to_one"))
    complete_close = session_closes.availability_ts_utc.eq(session_closes.canonical_close_ts)
    session_closes.loc[~complete_close, "session_final_close"] = np.nan
    session_closes["prior_session_close"] = session_closes.groupby("security_id", sort=False).session_final_close.shift(1)
    calculation = calculation.merge(session_closes[["security_id", "session_date", "prior_session_close"]],
                                    on=["security_id", "session_date"], how="left", validate="many_to_one")
    calculation["decision_ts"] = calculation.availability_ts_utc
    calculation["decision_grid"] = decision_grid
    bucket_periods = 5 if decision_grid == "intraday_5m" else 1
    bucket_group = [calculation.security_id, calculation.session_date] if decision_grid.startswith("intraday") else calculation.security_id
    calculation["bucket_return"] = calculation.close / calculation.close.groupby(bucket_group, sort=False).shift(bucket_periods) - 1
    calculation["emit"] = emit.to_numpy(dtype=bool)
    calculation["observation_id"] = -1
    order = calculation.loc[calculation.emit].sort_values(["decision_ts", "security_id"], kind="mergesort").index
    calculation.loc[order, "observation_id"] = np.arange(len(order), dtype=np.int64)
    benchmark_columns = ["decision_ts", "close", "session_open", "prior_session_close", "bucket_return"]
    benchmark = calculation.loc[calculation.symbol.eq(benchmark_symbol), benchmark_columns].drop_duplicates("decision_ts")
    benchmark = benchmark.rename(columns={"close": "benchmark_close", "session_open": "benchmark_session_open",
                                          "prior_session_close": "benchmark_prior_session_close"})
    benchmark = benchmark.rename(columns={"bucket_return": "benchmark_bucket_return"})
    calculation = calculation.merge(benchmark, on="decision_ts", how="left", validate="many_to_one")
    observations = calculation.loc[calculation.emit].sort_values(["decision_ts", "security_id"], kind="mergesort").copy()
    return calculation.sort_values(["security_id", "decision_ts"], kind="mergesort").reset_index(drop=True), observations.reset_index(drop=True)


def build_decision_panel(bars: pd.DataFrame, decision_grid: str, benchmark_symbol: str = "SPY") -> pd.DataFrame:
    frame = bars.copy()
    frame["bar_start_ts_utc"] = pd.to_datetime(frame.bar_start_ts_utc, utc=True)
    frame["availability_ts_utc"] = pd.to_datetime(frame.availability_ts_utc, utc=True)
    frame = _regular_bars(frame)
    if decision_grid == "intraday_5m":
        use = frame.availability_ts_utc.dt.minute.mod(5).eq(0)
    elif decision_grid == "intraday_1m":
        use = pd.Series(True, index=frame.index)
    elif decision_grid == "preclose_1555":
        local = frame.availability_ts_utc.dt.tz_convert("America/New_York")
        use = local.dt.strftime("%H:%M").eq("15:55")
    elif decision_grid == "daily_close":
        schedule = _benchmark_session_close(frame, benchmark_symbol)
        frame = frame.merge(schedule, on="session_date", how="inner", validate="many_to_one")
        use = frame.availability_ts_utc.eq(frame.canonical_close_ts)
    else:
        raise ValueError(f"Unknown decision grid: {decision_grid}")
    output = frame.loc[use].copy()
    output["decision_ts"] = output.availability_ts_utc
    output["decision_grid"] = decision_grid
    output = output.sort_values(["decision_ts", "security_id"], kind="mergesort").reset_index(drop=True)
    output.insert(0, "observation_id", np.arange(len(output), dtype=np.int64))
    if output.decision_ts.lt(output.availability_ts_utc).any():
        raise AssertionError("Decision precedes feature availability")
    return output
