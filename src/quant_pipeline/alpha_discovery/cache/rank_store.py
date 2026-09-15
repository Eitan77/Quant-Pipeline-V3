from __future__ import annotations

from hashlib import sha256
import numpy as np
import pandas as pd


def decision_group_bounds(decision_codes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    codes = np.asarray(decision_codes)
    if codes.ndim != 1: raise ValueError("decision codes must be one-dimensional")
    if len(codes) == 0: return np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    changes = np.flatnonzero(codes[1:] != codes[:-1]) + 1
    return np.r_[0, changes].astype(np.int64), np.r_[changes, len(codes)].astype(np.int64)


def build_percentile_ranks(values: np.ndarray, decision_codes: np.ndarray) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 2 or len(array) != len(decision_codes): raise ValueError("rank values and decision codes disagree")
    ranked = np.full(array.shape, np.nan, dtype=np.float32)
    starts,ends=decision_group_bounds(decision_codes); group=0
    while group<len(starts):
        first=int(starts[group]); last=group+1
        while last<len(starts) and int(ends[last]) - first <= 1_000_000: last+=1
        stop=int(ends[last-1]); frame=pd.DataFrame(array[first:stop])
        codes=pd.Series(np.asarray(decision_codes)[first:stop])
        ranked[first:stop]=frame.groupby(codes,sort=False).rank(method="average",pct=True).to_numpy(dtype=np.float32)
        group=last
    return ranked


def bins_from_ranks(ranked: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray]:
    if bins < 2 or bins > 127: raise ValueError("bins must be in [2, 127]")
    valid = np.isfinite(ranked); labels = np.full(ranked.shape, -1, dtype=np.int8)
    labels[valid] = np.minimum((ranked[valid] * bins).astype(np.int16), bins - 1).astype(np.int8)
    return labels, valid.astype(np.uint8)


def build_rank_bins(values: np.ndarray, decision_codes: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray]:
    return bins_from_ranks(build_percentile_ranks(values, decision_codes), bins)


def build_multi_bins(values: np.ndarray, decision_codes: np.ndarray, resolutions: tuple[int, ...] = (3, 5, 10)) -> dict[int, np.ndarray]:
    ranks = build_percentile_ranks(values, decision_codes)
    return {bins: bins_from_ranks(ranks, bins)[0] for bins in resolutions}


def pack_multi_bins(columns_by_resolution: dict[int, np.ndarray]) -> np.ndarray:
    """Losslessly encode the required 3/5/10 labels in one uint8 value."""
    if set(columns_by_resolution) != {3, 5, 10}:
        raise ValueError("Packed bins require exactly the 3, 5, and 10 resolutions")
    three, five, ten = (np.asarray(columns_by_resolution[n], dtype=np.int16) for n in (3, 5, 10))
    if three.shape != five.shape or three.shape != ten.shape:
        raise ValueError("Bin resolutions must have identical shapes")
    valid = (three >= 0) & (five >= 0) & (ten >= 0)
    packed = np.full(three.shape, 255, dtype=np.uint8)
    packed[valid] = (three[valid] + 3 * five[valid] + 15 * ten[valid]).astype(np.uint8)
    return packed


def unpack_bins(packed: np.ndarray, bins: int) -> np.ndarray:
    """Decode one resolution without allocating the other two."""
    values = np.asarray(packed, dtype=np.uint8)
    if bins == 3: decoded = values % 3
    elif bins == 5: decoded = (values // 3) % 5
    elif bins == 10: decoded = values // 15
    else: raise ValueError("Packed bins support only 3, 5, and 10")
    decoded = decoded.astype(np.int8, copy=False)
    decoded[values == 255] = -1
    return decoded


def build_packed_bins(values: np.ndarray, decision_codes: np.ndarray) -> np.ndarray:
    ranks = build_percentile_ranks(values, decision_codes)
    packed = np.full(ranks.shape, 255, dtype=np.uint8)
    for start in range(0, len(ranks), 1_000_000):
        block = ranks[start:start + 1_000_000]; valid = np.isfinite(block)
        three = np.minimum((block[valid] * 3).astype(np.int16), 2)
        five = np.minimum((block[valid] * 5).astype(np.int16), 4)
        ten = np.minimum((block[valid] * 10).astype(np.int16), 9)
        target = packed[start:start + len(block)]
        target[valid] = (three + 3 * five + 15 * ten).astype(np.uint8)
    return packed


def realized_alias_hash(columns_by_resolution: dict[int, np.ndarray], column: int) -> str:
    digest = sha256()
    for bins in sorted(columns_by_resolution):
        digest.update(int(bins).to_bytes(2, "little"))
        digest.update(np.ascontiguousarray(columns_by_resolution[bins][:, column], dtype=np.int8).tobytes())
    return digest.hexdigest()
