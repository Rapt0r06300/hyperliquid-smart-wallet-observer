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

def test_wall_clock_and_failure_limits_stop_campaign():
    old=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    m=manifest()
    m.created_at=old
    m.status="RUNNING"
    m.limits={**m.limits,"max_wall_clock_s":1}
    out=mark_continuation(m,"chunk",progressed=True)
    assert out.status=="FAILED"
    assert out.status_reason=="stop_limit_reached"

def test_consecutive_failure_limit_is_enforced():
    m=manifest()
    m.status="RUNNING"
    m.consecutive_failures=3
    m.limits={**m.limits,"max_consecutive_failures":4}
    out=mark_continuation(m,"temporary_failure",progressed=False,failure=True)
    assert out.status=="FAILED"
    assert out.consecutive_failures==4

def test_successful_progress_resets_failure_counter():
    m=manifest()
    m.status="RUNNING"
    m.consecutive_failures=2
    out=mark_continuation(m,"chunk",progressed=True,failure=False)
    assert out.status=="CONTINUATION_REQUIRED"
    assert out.consecutive_failures==0
