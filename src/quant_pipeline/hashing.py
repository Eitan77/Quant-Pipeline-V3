from __future__ import annotations
import dataclasses, hashlib, json
from enum import Enum
from pathlib import Path
from typing import Any

def _canonicalize(value: Any) -> Any:
    if dataclasses.is_dataclass(value): value = dataclasses.asdict(value)
    if isinstance(value, Enum): return value.value
    if isinstance(value, Path): return value.as_posix()
    if isinstance(value, dict): return {str(k): _canonicalize(v) for k,v in sorted(value.items(), key=lambda x:str(x[0]))}
    if isinstance(value, (list, tuple)): return [_canonicalize(v) for v in value]
    if isinstance(value, set): return sorted(_canonicalize(v) for v in value)
    return value

def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(_canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def content_hash(value: Any) -> str: return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

