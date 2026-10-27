from datetime import datetime, timedelta, timezone

import pytest

from hl_observer.control_plane.resumable_campaign import (
    COLLECT_CAMPAIGN_KINDS,
    SCHEMA_VERSION_V2,
    CampaignManifest,
    acquire_lease,
    complete_work_unit,
    mark_continuation,
    select_due_campaigns,
    transition,
    validate_manifest,
    verify_lease,
    work_unit_id,
)


def manifest():
    now = datetime.now(timezone.utc)
    return CampaignManifest(
        "c1",
        "market_collection",
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "a" * 40,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "g1",
        "b" * 64,
        "c" * 64,
        (now + timedelta(days=1)).isoformat(),
        schema_version=SCHEMA_VERSION_V2,
        created_at=now.isoformat(),
        creation_phase="COLLECT",
        phase_epoch=1,
    )


def test_safety_and_transition():
    campaign = manifest()
    validate_manifest(campaign)
    transition(campaign, "RUNNING", "go")
    assert campaign.status == "RUNNING"

    campaign.real_execution = True
    with pytest.raises(ValueError):
        validate_manifest(campaign)


def test_idempotent_unit_and_collision():
    campaign = manifest()
    unit_id = work_unit_id(campaign, {"x": 1})
    assert complete_work_unit(campaign, unit_id, "a", {}) is True
    assert complete_work_unit(campaign, unit_id, "a", {}) is False

    with pytest.raises(ValueError):
        complete_work_unit(campaign, unit_id, "b", {})


def test_lease_is_hashed_and_stale_rejected():
    campaign = manifest()
    token = acquire_lease(campaign, "1", 600)
    assert token not in str(campaign.to_dict())
    assert verify_lease(campaign, token)
    assert not verify_lease(campaign, "bad")


def test_safe_requires_replay_compatibility():
    campaign = manifest()
    campaign.outputs = [
        {
            "quality_status": "SAFE",
            "evidence_status": "SAFE",
            "replay_compatible": False,
        }
    ]
    with pytest.raises(ValueError):
        validate_manifest(campaign)


def test_wall_clock_and_failure_limits_stop_campaign():
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    campaign = manifest()
    campaign.created_at = old
    campaign.status = "RUNNING"
    campaign.limits = {**campaign.limits, "max_wall_clock_s": 1}

    result = mark_continuation(campaign, "chunk", progressed=True)

    assert result.status == "FAILED"
    assert result.status_reason == "stop_limit_reached"


def test_consecutive_failure_limit_is_enforced():
    campaign = manifest()
    campaign.status = "RUNNING"
    campaign.consecutive_failures = 3
    campaign.limits = {**campaign.limits, "max_consecutive_failures": 4}

    result = mark_continuation(
        campaign,
        "temporary_failure",
        progressed=False,
        failure=True,
    )

    assert result.status == "STUCK"
    assert result.consecutive_failures == 4
    assert result.next_due_at is not None


def test_successful_progress_resets_failure_counter():
    campaign = manifest()
    campaign.status = "RUNNING"
    campaign.consecutive_failures = 2

    result = mark_continuation(
        campaign,
        "chunk",
        progressed=True,
        failure=False,
    )

    assert result.status == "CONTINUATION_REQUIRED"
    assert result.consecutive_failures == 0


def test_due_selection_round_robins_campaign_kinds_before_repeating():
    now = datetime.now(timezone.utc)

    def make(campaign_id, kind):
        phase = "COLLECT" if kind in COLLECT_CAMPAIGN_KINDS else "ANALYZE"
        return CampaignManifest(
            campaign_id,
            kind,
            "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "a" * 40,
            "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "g1",
            "b" * 64,
            "c" * 64,
            (now + timedelta(days=1)).isoformat(),
            schema_version=SCHEMA_VERSION_V2,
            created_at=now.isoformat(),
            creation_phase=phase,
            phase_epoch=1,
            source_collection_epoch=1 if phase == "ANALYZE" else None,
            collection_cutoff_at_utc=now.isoformat() if phase == "ANALYZE" else None,
            dataset_selection_id="selection-1" if phase == "ANALYZE" else None,
            cursor={"strategy_family": "copy_vault"} if phase == "ANALYZE" else {},
        )

    items = [
        make(f"copy-vault-{index:03d}", "copy_vault_collection")
        for index in range(20)
    ]
    items += [
        make("market-1", "market_collection"),
        make("event-1", "event_intelligence_collection"),
        make("replay-1", "replay"),
        make("backtest-1", "backtest"),
        make("pnl-1", "module_pnl_proof"),
        make("archive-1", "official_archive_collection"),
    ]

    selected = select_due_campaigns(
        items,
        current_epoch=1,
        now=now.isoformat(),
    )
    first_kinds = [campaign.kind for campaign in selected[:7]]

    assert len(first_kinds) == len(set(first_kinds)) == 7
    assert set(first_kinds) == {campaign.kind for campaign in items}


def test_v2_foreign_code_or_dataset_repository_is_rejected():
    campaign = manifest()
    campaign.dataset_repo = "Rapt0r06300/alina-smartflow-datasets-v2"
    with pytest.raises(ValueError, match="canonical Alina repository"):
        validate_manifest(campaign)

    campaign = manifest()
    campaign.code_repo = "someone/other"
    with pytest.raises(ValueError, match="canonical Alina repository"):
        validate_manifest(campaign)
