"""Anti-split-brain guards and campaign operator dispatch helpers."""
from __future__ import annotations

from typing import Any, Mapping
from hl_observer.control_plane.phase_control import read_phase_state, AlinaPhaseState
from hl_observer.control_plane.resumable_campaign import CampaignManifest, verify_lease, ACTIVE_STATES


def verify_phase_epoch_guard(manifest: CampaignManifest, phase_state: AlinaPhaseState | None = None) -> bool:
    state = phase_state or read_phase_state()
    if manifest.phase_epoch is not None and manifest.phase_epoch != state.epoch:
        return False
    if state.phase == "COLLECT" and manifest.kind not in {
        "market_collection",
        "copy_vault_collection",
        "official_archive_collection",
        "event_intelligence_collection",
    }:
        return False
    if state.phase == "ANALYZE" and manifest.kind in {
        "market_collection",
        "copy_vault_collection",
        "official_archive_collection",
        "event_intelligence_collection",
    }:
        return False
    return True


def verify_single_owner_lease(
    manifest: CampaignManifest,
    worker_run_id: str,
    lease_token: str | None = None,
) -> bool:
    if manifest.status not in ACTIVE_STATES:
        return False
    if manifest.lease is None:
        return True
    if manifest.lease.get("owner_run_id") != str(worker_run_id):
        return False
    if lease_token and not verify_lease(manifest, lease_token):
        return False
    return True


def build_dispatch_receipt(
    manifest: CampaignManifest,
    operator_id: str = "alina_main_operator",
) -> dict[str, Any]:
    return {
        "campaign_id": manifest.campaign_id,
        "kind": manifest.kind,
        "code_sha": manifest.code_sha,
        "phase_epoch": manifest.phase_epoch,
        "operator_id": operator_id,
        "dispatched_at_utc": manifest.updated_at,
        "status": manifest.status,
    }
