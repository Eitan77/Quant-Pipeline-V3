from __future__ import annotations

import numpy as np


def encode_groups(frame, columns):
    """Encode once for the complete observation grid, never separately per chunk."""
    import pandas as pd
    if not columns or len(set(columns)) != len(columns):
        raise ValueError("Group columns must be nonempty and unique")
    values = frame.loc[:, list(columns)]
    present = values.notna().all(axis=1).to_numpy()
    codes = np.full(len(frame), -1, dtype=np.int64)
    index = pd.MultiIndex.from_frame(values.loc[present])
    valid_codes, keys = pd.factorize(index, sort=True)
    codes[present] = valid_codes
    labels = keys.to_frame(index=False)
    labels.columns = list(columns)
    labels.insert(0, "group_id", np.arange(len(labels), dtype=np.int64))
    return codes, labels


class SegmentedMoments:
    """One bounded (target, pair, group, cell) tile. CPU reference + Torch backend."""

    def __init__(self, *, pairs, targets, groups, resolution, singles=False,
                 device="cpu", max_state_bytes):
        if resolution not in (3, 5, 10) or min(pairs, targets, groups) < 1:
            raise ValueError("Invalid tile axes")
        self.resolution, self.singles = resolution, singles
        self.cells = resolution if singles else resolution * resolution
        self.shape = (targets, pairs, groups, self.cells)
        if 24 * targets * pairs * groups * self.cells > max_state_bytes:
            raise MemoryError("Split logical work into smaller accumulator tiles")
        self.torch = None
        if device != "cpu":
            import torch
            self.torch = torch
            self.device = torch.device(device)
            self.n = torch.zeros(self.shape, dtype=torch.int64, device=self.device)
            self.s = torch.zeros(self.shape, dtype=torch.float64, device=self.device)
            self.q = torch.zeros_like(self.s)
        else:
            self.n = np.zeros(self.shape, np.int64)
            self.s = np.zeros(self.shape, np.float64)
            self.q = np.zeros(self.shape, np.float64)

    def update(self, packed, left, right, y, group_codes):
        packed = np.asarray(packed)
        left = np.asarray(left, np.int64)
        right = None if right is None else np.asarray(right, np.int64)
        y = np.asarray(y)
        y = y[:, None] if y.ndim == 1 else y
        groups = np.asarray(group_codes, np.int64)
        targets, pairs, group_count, cells = self.shape
        if packed.ndim != 2 or packed.dtype != np.uint8:
            raise ValueError("Expected packed uint8 matrix")
        if np.any((packed >= 150) & (packed != 255)):
            raise ValueError("Invalid packed feature code")
        if y.shape != (len(packed), targets) or groups.shape != (len(packed),):
            raise ValueError("Observation/target/group alignment mismatch")
        if len(left) != pairs or (not self.singles and (right is None or len(right) != pairs)):
            raise ValueError("Pair axis mismatch")
        for indices in (left,) if self.singles else (left, right):
            if np.any(indices < 0) or np.any(indices >= packed.shape[1]):
                raise ValueError("Feature index out of range")
        if np.any(groups < -1) or np.any(groups >= group_count):
            raise ValueError("Codes must be local to this group partition; -1 means excluded")
        prepared = prepare_tile(packed, y, self.device if self.torch is not None else "cpu")
        self.update_prepared(prepared, left, right, groups)

    def update_prepared(self, prepared, left, right, group_codes):
        """Accumulate a tile already staged once for several grouping families."""
        packed, y = prepared
        left = np.asarray(left, np.int64)
        right = None if right is None else np.asarray(right, np.int64)
        groups = np.asarray(group_codes, np.int64)
        targets, pairs, group_count, cells = self.shape
        if tuple(packed.shape)[1] <= int(max(left.max(initial=-1), -1 if right is None else right.max(initial=-1))):
            raise ValueError("Feature index out of range")
        if tuple(y.shape) != (len(packed), targets) or groups.shape != (len(packed),):
            raise ValueError("Prepared observation axes disagree")
        if np.any(groups < -1) or np.any(groups >= group_count):
            raise ValueError("Codes must be local to this group partition")
        active = np.flatnonzero(groups >= 0)
        if not len(active):
            return
        if len(active) != len(groups):
            groups = groups[active]
            if self.torch is None:
                packed, y = packed[active], y[active]
            else:
                indices = self.torch.as_tensor(active, device=self.device)
                packed, y = packed.index_select(0, indices), y.index_select(0, indices)
        r = self.resolution
        if self.torch is None:
            pa = packed[:, left]
            pb = None if self.singles else packed[:, right]
            decode = lambda x: x % 3 if r == 3 else (x // 3) % 5 if r == 5 else x // 15
            valid = pa != 255
            cell = decode(pa).astype(np.int64)
            if pb is not None:
                valid &= pb != 255
                cell = cell * r + decode(pb)
            valid &= groups[:, None] >= 0
            keys = ((np.arange(pairs)[None, :] * group_count + groups[:, None]) * cells + cell)
            for target in range(targets):
                keep = valid & np.isfinite(y[:, target, None])
                indices = keys[keep]
                values = np.broadcast_to(y[:, target, None], keep.shape)[keep].astype(np.float64)
                np.add.at(self.n[target].reshape(-1), indices, 1)
                np.add.at(self.s[target].reshape(-1), indices, values)
                np.add.at(self.q[target].reshape(-1), indices, values * values)
        else:
            t = self.torch
            raw = packed
            pa = raw.index_select(1, t.as_tensor(left, device=self.device)).to(t.int64)
            pb = None if self.singles else raw.index_select(1, t.as_tensor(right, device=self.device)).to(t.int64)
            decode = lambda x: x.remainder(3) if r == 3 else x.div(3, rounding_mode="floor").remainder(5) if r == 5 else x.div(15, rounding_mode="floor")
            cell, valid = decode(pa), pa != 255
            if pb is not None:
                cell = cell * r + decode(pb)
                valid &= pb != 255
            g = t.as_tensor(groups, device=self.device)
            valid &= g[:, None] >= 0
            keys = ((t.arange(pairs, device=self.device)[None, :] * group_count + g[:, None]) * cells + cell)
            values_y = y
            for target in range(targets):
                keep = valid & t.isfinite(values_y[:, target, None])
                indices = keys[keep]
                values = values_y[:, target, None].expand(-1, pairs)[keep]
                self.n[target].view(-1).scatter_add_(0, indices, t.ones_like(indices))
                self.s[target].view(-1).scatter_add_(0, indices, values)
                self.q[target].view(-1).scatter_add_(0, indices, values.square())

    def numpy(self):
        if self.torch is None:
            return self.n, self.s, self.q
        return tuple(x.detach().cpu().numpy() for x in (self.n, self.s, self.q))


def prepare_tile(packed, y, device="cpu"):
    """Validate and stage shared inputs once per observation chunk."""
    packed = np.asarray(packed)
    y = np.asarray(y)
    y = y[:, None] if y.ndim == 1 else y
    if packed.ndim != 2 or packed.dtype != np.uint8 or y.ndim != 2 or len(y) != len(packed):
        raise ValueError("Invalid packed/target tile")
    if np.any((packed >= 150) & (packed != 255)):
        raise ValueError("Invalid packed feature code")
    if device == "cpu":
        return packed, y
    import torch
    return (torch.as_tensor(packed, dtype=torch.uint8, device=device),
            torch.as_tensor(y, dtype=torch.float64, device=device))


def local_group_codes(global_codes, start, stop):
    values = np.asarray(global_codes, np.int64)
    return np.where((values >= start) & (values < stop), values - start, -1)
