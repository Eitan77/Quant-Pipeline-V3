from __future__ import annotations

import numpy as np


def build_tail_mask(*, rank_a, rank_b, state_a, state_b, selected_a: int,
                    selected_b: int, resolution: int, tail_fraction: float):
    """Build a feature-state tail mask; target outcomes are deliberately absent."""
    if not 0 < tail_fraction <= 0.5:
        raise ValueError("tail_fraction must be in (0, 0.5]")
    if selected_a not in (0, resolution - 1) and selected_b not in (0, resolution - 1):
        return np.zeros(len(state_a), dtype=bool), False, "selected_state_has_no_outer_tail"
    mask = np.ones(len(state_a), dtype=bool)
    for rank, state, selected in ((rank_a, state_a, selected_a), (rank_b, state_b, selected_b)):
        rank = np.asarray(rank, float); state = np.asarray(state)
        if selected == 0:
            mask &= np.isfinite(rank) & (rank < tail_fraction)
        elif selected == resolution - 1:
            mask &= np.isfinite(rank) & (rank >= 1.0 - tail_fraction)
        else:
            mask &= state == selected
    return mask, True, None
