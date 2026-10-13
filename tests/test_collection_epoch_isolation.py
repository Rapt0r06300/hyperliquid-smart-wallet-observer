"""Prevent old collection epochs from restarting and inflating the replay corpus."""

from datetime import datetime, timezone

import pytest

from hl_observer.control_plane.resumable_campaign import (
    CampaignManifest,
    acquire_lease,
    select_due_campaigns,
)


REPO = "Rapt0r06300/hyperliquid-smart-wallet-observer"
NOW = "2026-10-13T17:00:00Z"


def campaign(epoch: int, status: str = "PENDING") -> CampaignManifest:
    return CampaignManifest(
        campaign_id=f"market-e{epoch}-{status.lower()}",
        kind="market_collection",
        code_repo=REPO,
        code_sha="a" * 40,
        dataset_repo=REPO,
        dataset_generation="V2_FRESH",
        config_sha256="b" * 64,
        work_plan_sha256="c" * 64,
        created_at="2026-10-12T00:00:00Z",
        updated_at="2026-10-12T00:00:00Z",
        expires_at="2026-10-20T00:00:00Z",
        schema_version="alina.resumable_campaign.v2",
        creation_phase="COLLECT",
        phase_epoch=epoch,
        status=status,
    )


@pytest.mark.parametrize("status", ["PENDING", "CONTINUATION_REQUIRED", "STUCK"])
def test_prior_collect_epoch_never_selected_for_new_epoch(status):
    old = campaign(7, status)
    current = campaign(8, status)
    due = select_due_campaigns(
        [old, current], current_phase="COLLECT", current_epoch=8,
        now=NOW,
    )
    assert [row.campaign_id for row in due] == [current.campaign_id]


def test_collect_epoch_mismatch_refuses_new_lease_but_current_epoch_runs():
    stale = campaign(7, "STUCK")
    with pytest.raises(ValueError, match="Stale phase epoch"):
        acquire_lease(
            stale, "github-hosted-old", ttl_s=120,
            expected_phase="COLLECT", expected_epoch=8, now=NOW,
        )
    assert stale.lease is None
    live = campaign(8)
    token = acquire_lease(
        live, "github-hosted-current", ttl_s=120,
        expected_phase="COLLECT", expected_epoch=8, now=NOW,
    )
    assert token and live.lease and live.lease["owner_run_id"] == "github-hosted-current"
