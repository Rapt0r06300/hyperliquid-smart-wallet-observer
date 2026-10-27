from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from hl_observer.control_plane.resumable_campaign import (
    SCHEMA_VERSION_V2,
    CampaignManifest,
    acquire_lease,
    select_due_campaigns,
)
from tools import resumable_campaign as campaign_cli


def _analysis_campaign(family: str | None, *, status: str = "PENDING") -> CampaignManifest:
    cursor = {"strategy_family": family} if family is not None else {}
    return CampaignManifest(
        campaign_id=f"analysis-{family or 'missing'}",
        kind="replay",
        code_repo="Rapt0r06300/hyperliquid-smart-wallet-observer",
        code_sha="a" * 40,
        dataset_repo="Rapt0r06300/hyperliquid-smart-wallet-observer",
        dataset_generation="V2_FRESH",
        config_sha256="b" * 64,
        work_plan_sha256="c" * 64,
        expires_at="2026-12-31T00:00:00Z",
        schema_version=SCHEMA_VERSION_V2,
        status=status,
        creation_phase="ANALYZE",
        phase_epoch=4,
        source_collection_epoch=3,
        collection_cutoff_at_utc="2026-10-26T00:00:00Z",
        dataset_selection_id="d" * 64,
        analysis_stage="REPLAY",
        cursor=cursor,
    )


@pytest.mark.parametrize("family", [None, "lead_lag", "all"])
def test_v2_economic_campaign_without_canonical_family_cannot_claim(family: str | None) -> None:
    manifest = _analysis_campaign(family)

    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        acquire_lease(manifest, "worker-1", 300)

    assert manifest.lease is None


def test_v2_copy_vault_campaign_can_claim() -> None:
    manifest = _analysis_campaign("copy_vault")

    token = acquire_lease(manifest, "worker-1", 300)

    assert token
    assert manifest.lease is not None


def test_analysis_campaign_creation_requires_explicit_active_family(
    tmp_path: Path, monkeypatch
) -> None:
    manifest_path = tmp_path / "new-analysis.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resumable_campaign.py",
            "create",
            str(manifest_path),
            "--campaign-id",
            "new-analysis",
            "--kind",
            "replay",
            "--code-sha",
            "a" * 40,
            "--creation-phase",
            "ANALYZE",
            "--phase-epoch",
            "4",
            "--source-collection-epoch",
            "3",
            "--collection-cutoff-at-utc",
            "2026-10-26T00:00:00Z",
            "--dataset-selection-id",
            "d" * 64,
        ],
    )

    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE:.*missing_strategy_family"):
        campaign_cli.main()

    assert not manifest_path.exists()


def test_due_selection_excludes_unsafe_analysis_but_keeps_collection_all(caplog) -> None:
    unsafe = _analysis_campaign("lead_lag")
    safe = _analysis_campaign("copy_vault")

    selected = select_due_campaigns(
        [unsafe, safe],
        current_phase="ANALYZE",
        current_epoch=4,
        current_analysis_stage="REPLAY",
        now="2026-10-26T12:00:00Z",
    )

    assert selected == [safe]
    assert "DISABLED_BY_SCOPE" in caplog.text


def test_retry_cli_refuses_unsafe_campaign_without_mutating_manifest(tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "unsafe.json"
    raw = _analysis_campaign("lead_lag", status="STUCK").to_dict()
    manifest_path.write_text(json.dumps(raw, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    before = manifest_path.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        ["resumable_campaign.py", "retry", str(manifest_path), "--reason", "operator_retry"],
    )

    with pytest.raises((ValueError, SystemExit), match="DISABLED_BY_SCOPE"):
        campaign_cli.main()

    assert manifest_path.read_bytes() == before


def test_retry_cli_refuses_active_lease_without_mutating_manifest(tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "leased.json"
    raw = _analysis_campaign("copy_vault", status="STUCK").to_dict()
    raw["lease"] = {
        "owner_run_id": "worker-1",
        "lease_token_sha256": "1" * 64,
        "acquired_at": "2026-10-26T11:00:00Z",
        "expires_at": "2026-12-31T00:00:00Z",
    }
    manifest_path.write_text(json.dumps(raw, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    before = manifest_path.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        ["resumable_campaign.py", "retry", str(manifest_path), "--reason", "operator-retry"],
    )

    with pytest.raises(SystemExit, match="active campaign lease prevents operator retry"):
        campaign_cli.main()

    assert manifest_path.read_bytes() == before


def test_scheduled_campaign_creator_pins_family_before_hashing_cursor() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "create-resumable-campaigns.yml"
    ).read_text(encoding="utf-8")

    normalize_at = workflow.index('CURSOR="$(python - "$PHASE" "$CURSOR"')
    hash_at = workflow.index('CFG_SHA="$(printf', normalize_at)
    assert "normalize_operator_family(\"replay\", selector, cursor)" in workflow[
        normalize_at:hash_at
    ]

