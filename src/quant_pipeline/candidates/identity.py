from quant_pipeline.contracts import CandidateDefinition
from quant_pipeline.hashing import content_hash
def make_candidate(*,feature_a,feature_b,target,grid,resolution,state_payload,state_definition,direction,source_snapshot_hash,selection_run_id,selection_trial_id):
    payload={"feature_a_definition_hash":feature_a.definition_hash,"feature_b_definition_hash":feature_b.definition_hash if feature_b else None,"target_definition_hash":target.definition_hash,"grid":grid,"resolution":resolution,"state_payload":state_payload,"direction":direction,"source_snapshot_hash":source_snapshot_hash,"return_basis":target.return_basis}
    h=content_hash(payload)
    return CandidateDefinition(f"cand_{h[:16]}",feature_a.feature_id,feature_b.feature_id if feature_b else None,target.target_id,grid,resolution,state_payload,state_definition,direction,source_snapshot_hash,selection_run_id,selection_trial_id,target.return_basis,h)

