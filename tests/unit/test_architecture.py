import pytest
from quant_pipeline.orchestration.dag import DEPENDENCIES
from quant_pipeline.orchestration.runner import DagRunner
from quant_pipeline.discovery.trials import TrialLedger,TrialRecord
def test_authoritative_dag_orders_dependencies():
    stages={x:None for x in DEPENDENCIES}; order=DagRunner(stages=stages,dependencies=DEPENDENCIES).ordered_stages(("analysis_bundle",)); assert order.index("canonical_duals")<order.index("forensics")<order.index("analysis_bundle")
def test_trial_ledger_refuses_unexplained_gap():
    x=TrialLedger();x.put(TrialRecord("a","f","r","dual","executed"))
    with pytest.raises(ValueError,match="gap"):x.reconcile({"a","b"})

