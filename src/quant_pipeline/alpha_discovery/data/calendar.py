from __future__ import annotations

import exchange_calendars as xcals
import pandas as pd


def schedule(start: str, end: str, calendar_name: str = "XNYS") -> pd.DataFrame:
    calendar = xcals.get_calendar(calendar_name)
    sessions = calendar.sessions_in_range(start, end)
    return pd.DataFrame({
        "session_date": sessions.tz_localize(None),
        "market_open": [calendar.session_open(s) for s in sessions],
        "market_close": [calendar.session_close(s) for s in sessions],
    })
