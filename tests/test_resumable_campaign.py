from datetime import datetime,timezone,timedelta
import pytest
from hl_observer.control_plane.resumable_campaign import *

def manifest():
 now=datetime.now(timezone.utc); return CampaignManifest("c1","market_collection","Rapt0r06300/hyperliquid-smart-wallet-observer","a"*40,"Rapt0r06300/hyperliquid-smart-wallet-observer","g1","b"*64,"c"*64,(now+timedelta(days=1)).isoformat(),schema_version=SCHEMA_VERSION_V2,created_at=now.isoformat(),creation_phase="COLLECT",phase_epoch=1)
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
    assert out.status=="STUCK"
    assert out.consecutive_failures==4
    assert out.next_due_at is not None

def test_successful_progress_resets_failure_counter():
    m=manifest()
    m.status="RUNNING"
    m.consecutive_failures=2
    out=mark_continuation(m,"chunk",progressed=True,failure=False)
    assert out.status=="CONTINUATION_REQUIRED"
    assert out.consecutive_failures==0


def test_due_selection_round_robins_campaign_kinds_before_repeating():
    now=datetime.now(timezone.utc)
    def make(cid, kind):
        phase = "COLLECT" if kind in COLLECT_CAMPAIGN_KINDS else "ANALYZE"
        return CampaignManifest(
            cid,
            kind,
            "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "a"*40,
            "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "g1",
            "b"*64,
            "c"*64,
            (now+timedelta(days=1)).isoformat(),
            schema_version=SCHEMA_VERSION_V2,
            created_at=now.isoformat(),
            creation_phase=phase,
            phase_epoch=1,
            source_collection_epoch=1 if phase == "ANALYZE" else None,
            collection_cutoff_at_utc=now.isoformat() if phase == "ANALYZE" else None,
            dataset_selection_id="selection-1" if phase == "ANALYZE" else None,
        )
    items=[make(f"copy-vault-{i:03d}","copy_vault_collection") for i in range(20)]
    items += [
        make("market-1","market_collection"),
        make("event-1","event_intelligence_collection"),
        make("replay-1","replay"),
        make("backtest-1","backtest"),
        make("pnl-1","module_pnl_proof"),
        make("archive-1","official_archive_collection"),
    ]
    selected=select_due_campaigns(items, current_epoch=1, now=now.isoformat())
    first_kinds=[m.kind for m in selected[:7]]
    assert len(first_kinds)==len(set(first_kinds))==7
    assert set(first_kinds)=={m.kind for m in items}


def test_v2_foreign_code_or_dataset_repository_is_rejected():
    m = manifest()
    m.dataset_repo = "Rapt0r06300/alina-smartflow-datasets-v2"
    with pytest.raises(ValueError, match="canonical Alina repository"):
        validate_manifest(m)
    m = manifest()
    m.code_repo = "someone/other"
    with pytest.raises(ValueError, match="canonical Alina repository"):
        validate_manifest(m)
