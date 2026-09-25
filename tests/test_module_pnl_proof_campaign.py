import pytest
from hl_observer.control_plane.module_pnl_proof import prove_module

def test_proof_is_safe_only_and_net_of_costs():
 r=prove_module("lead_lag",[{"quality_status":"SAFE","replay_compatible":True,"gross_pnl":10,"fees":2,"slippage":1,"funding_financing":1}]); assert r["net_pnl"]==6 and r["threshold_met"]
def test_rejects_partial():
 with pytest.raises(ValueError): prove_module("lead_lag",[{"quality_status":"PARTIAL","replay_compatible":True}])
