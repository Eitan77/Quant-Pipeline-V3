"""Optional acquisition boundary.

Research stages never import or call this module. A deployment-specific adapter
may use it to write an immutable, explicitly raw, SIP snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import dotenv_values


def require_explicit_contract(feed: str, adjustment: str) -> None:
    if feed.lower() != "sip" or adjustment.lower() != "raw":
        raise ValueError("V2 production ingestion requires feed='sip' and adjustment='raw'")


@dataclass
class AlpacaHistoricalClient:
    api_key: str
    api_secret: str
    base_url: str = "https://data.alpaca.markets"
    max_retries: int = 8
    requests_per_minute: int = 180

    @classmethod
    def from_env(cls, path: str | Path | None = None) -> "AlpacaHistoricalClient":
        values = dict(dotenv_values(path)) if path else {}
        key = values.get("APCA_API_KEY_ID") or os.getenv("APCA_API_KEY_ID")
        secret = values.get("APCA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
        if not key or not secret: raise RuntimeError("Missing Alpaca API credentials")
        return cls(str(key), str(secret))

    def _paged_json(self, endpoint: str, params: dict) -> tuple[list[dict], list[dict]]:
        pages, records, token = [], [], None
        while True:
            query = dict(params)
            if token: query["page_token"] = token
            request = Request(self.base_url + endpoint + "?" + urlencode(query), headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret})
            for attempt in range(self.max_retries):
                try:
                    with urlopen(request, timeout=60) as response: payload = json.loads(response.read())
                    break
                except Exception:
                    if attempt + 1 == self.max_retries: raise
                    time.sleep(min(30, 2 ** attempt))
            pages.append(payload)
            for value in payload.values():
                if isinstance(value, dict):
                    for rows in value.values():
                        if isinstance(rows, list): records.extend(rows)
                elif isinstance(value, list): records.extend(value)
            token = payload.get("next_page_token")
            if not token: return pages, records
            time.sleep(60 / max(self.requests_per_minute, 1))
