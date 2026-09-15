from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
from math import log1p
from pathlib import Path
from typing import Any
import numpy as np
from .dual_pairs import pair_id


def canonical_concept_features(specs: list[Any], anchors: dict[str, str] | None = None) -> tuple[list[Any], dict[str, str]]:
    """Choose one deterministic raw, anchor-scale feature per concept and grid."""
    anchors = anchors or {"intraday_5m": "30m", "daily_close": "20d", "preclose_1555": "20d"}
    selected: list[Any] = []; excluded: dict[str, str] = {}
    for concept in sorted({item.concept_id for item in specs}):
        candidates = [item for item in specs if item.concept_id == concept]
        configured=anchors.get(candidates[0].decision_grid,"20d")
        labels=[configured] if isinstance(configured,str) else configured
        if not labels: raise ValueError("At least one anchor is required")
        kept=[]
        for anchor in labels:
            if not isinstance(anchor,str) or anchor[-1:] not in ('m','d') or not anchor[:-1].isdigit():
                raise ValueError("Anchors must be positive minute/session labels")
            anchor_kind="minutes" if anchor.endswith("m") else "sessions"; anchor_value=int(anchor[:-1])
            if anchor_value<1: raise ValueError("Anchor must be positive")
            def key(item):
                value=item.scale.value if item.scale.value is not None else anchor_value*100
                return (item.representation!="raw",item.scale.kind!=anchor_kind,abs(log1p(max(int(value),0))-log1p(anchor_value)),item.minimum_history,item.feature_id)
            canonical=min(candidates,key=key)
            if canonical.feature_id not in {item.feature_id for item in kept}: kept.append(canonical)
        selected.extend(kept); ids={item.feature_id for item in kept}
        excluded.update({item.feature_id:kept[0].feature_id for item in candidates if item.feature_id not in ids})
    return selected, excluded


@dataclass(frozen=True)
class PairPlan:
    feature_ids: tuple[str, ...]
    left: np.ndarray
    right: np.ndarray
    pair_ids: tuple[str, ...]
    alias_of: dict[str, str]

    @classmethod
    def compile(cls, feature_ids: list[str], alias_hashes: dict[str, str] | None = None) -> "PairPlan":
        canonical, alias_of, kept = {}, {}, []
        for feature_id in feature_ids:
            key = (alias_hashes or {}).get(feature_id, feature_id)
            if key in canonical: alias_of[feature_id] = canonical[key]
            else: canonical[key] = feature_id; kept.append(feature_id)
        left, right = np.triu_indices(len(kept), 1)
        ids = tuple(pair_id(kept[a], kept[b]) for a, b in zip(left, right))
        return cls(tuple(kept), left.astype(np.int32), right.astype(np.int32), ids, alias_of)

    @property
    def definition_hash(self) -> str:
        payload = {"features": self.feature_ids, "left": self.left.tolist(), "right": self.right.tolist(), "aliases": self.alias_of}
        return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def write(self, path: str | Path) -> None:
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(target, left=self.left, right=self.right, feature_ids=np.asarray(self.feature_ids), pair_ids=np.asarray(self.pair_ids))
        target.with_suffix(".json").write_text(json.dumps({"hash": self.definition_hash, "alias_of": self.alias_of, "pair_count": len(self.left)}, indent=2), encoding="utf-8")
