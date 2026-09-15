from __future__ import annotations
from dataclasses import dataclass
from itertools import combinations

@dataclass(frozen=True)
class Pair: pair_id:str; feature_a_id:str; feature_b_id:str
def canonical_pair_id(a,b): x,y=sorted((a,b)); return f"{x}__X__{y}"
def plan_pairs(features,compatible=lambda a,b:a.grid==b.grid):
    canonical=sorted((x for x in features if x.canonical),key=lambda x:x.feature_id)
    return [Pair(canonical_pair_id(a.feature_id,b.feature_id),a.feature_id,b.feature_id) for a,b in combinations(canonical,2) if compatible(a,b)]

