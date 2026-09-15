from dataclasses import dataclass
@dataclass(frozen=True,slots=True)
class VariantExpansionRequest: parent_pair_id:str;reason_codes:tuple[str,...];feature_a_variants:tuple[str,...];feature_b_variants:tuple[str,...];target_ids:tuple[str,...];trial_family_id:str
def plan_variant_expansion(parent_pair,reason_codes,feature_registry,trial_family_id):
    items=feature_registry.all();a=tuple(x.feature_id for x in items if x.concept_id==parent_pair.feature_a.concept_id);b=tuple(x.feature_id for x in items if x.concept_id==parent_pair.feature_b.concept_id);return VariantExpansionRequest(parent_pair.pair_id,tuple(reason_codes),a,b,tuple(parent_pair.target_ids),trial_family_id)

