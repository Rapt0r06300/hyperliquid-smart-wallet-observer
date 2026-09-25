from datetime import datetime,timezone,timedelta
import pytest
from hl_observer.control_plane.resumable_campaign import *

def manifest():
 now=datetime.now(timezone.utc); return CampaignManifest("c1","replay","Rapt0r06300/hyperliquid-smart-wallet-observer","abc","Rapt0r06300/alina-smartflow-datasets-v2","g1","cfg","plan",(now+timedelta(days=1)).isoformat(),created_at=now.isoformat())
def test_safety_and_transition():
 m=manifest(); validate_manifest(m); transition(m,"RUNNING","go"); assert m.status=="RUNNING"
 m.real_execution=True
 with pytest.raises(ValueError): validate_manifest(m)
def test_idempotent_unit_and_collision():
 m=manifest(); u=work_unit_id(m,{"x":1}); assert complete_work_unit(m,u,"a",{}) is True; assert complete_work_unit(m,u,"a",{}) is False
 with pytest.raises(ValueError): complete_work_unit(m,u,"b",{})
def test_lease_is_hashed_and_stale_rejected():
 m=manifest(); token=acquire_lease(m,"1",600); assert token not in str(m.to_dict()); assert verify_lease(m,token); assert not verify_lease(m,"bad")
def test_safe_requires_replay_compatibility():
 m=manifest(); m.outputs=[{"quality_status":"SAFE","evidence_status":"SAFE","replay_compatible":False}]
 with pytest.raises(ValueError): validate_manifest(m)
