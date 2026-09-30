"""Unit tests for Campaign Manifest Schema V2 and Dispatch Receipts (Block 3 & 4 of spec)."""
import json
import pytest

from hl_observer.control_plane.resumable_campaign import (
    CampaignManifest,
    validate_manifest,
    acquire_lease,
    select_due_campaigns,
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
)
from tools.resumable_campaign import save

from hl_observer.control_plane.dispatch_receipt import (
    generate_request_id,
    DispatchReceipt,
)


def test_v1_manifest_backwards_compatibility():
    raw_v1 = {
        "campaign_id": "c1",
        "kind": "market_collection",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "a" * 40,
        "dataset_repo": "Rapt0r06300/alina-smartflow-datasets-v2",
        "dataset_generation": "gen-1",
        "config_sha256": "b" * 64,
        "work_plan_sha256": "c" * 64,
        "expires_at": "2026-12-31T23:59:59Z",
        "schema_version": SCHEMA_VERSION_V1,
    }
    m = CampaignManifest.from_dict(raw_v1)
    assert m.schema_version == SCHEMA_VERSION_V1
    assert m.campaign_id == "c1"


def test_v2_manifest_validation():
    raw_v2_invalid = {
        "campaign_id": "c2",
        "kind": "market_collection",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "a" * 40,
        "dataset_repo": "Rapt0r06300/alina-smartflow-datasets-v2",
        "dataset_generation": "gen-1",
        "config_sha256": "b" * 64,
        "work_plan_sha256": "c" * 64,
        "expires_at": "2026-12-31T23:59:59Z",
        "schema_version": SCHEMA_VERSION_V2,
        # Missing creation_phase and phase_epoch
    }
    with pytest.raises(ValueError, match="V2 manifest must specify valid creation_phase"):
        CampaignManifest.from_dict(raw_v2_invalid)

    raw_v2_valid = {
        **raw_v2_invalid,
        "creation_phase": "COLLECT",
        "phase_epoch": 2,
    }
    m = CampaignManifest.from_dict(raw_v2_valid)
    assert m.schema_version == SCHEMA_VERSION_V2
    assert m.creation_phase == "COLLECT"
    assert m.phase_epoch == 2


def test_v2_analyze_manifest_requires_cutoff_and_selection():
    raw_analyze = {
        "campaign_id": "c3",
        "kind": "replay",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "a" * 40,
        "dataset_repo": "Rapt0r06300/alina-smartflow-datasets-v2",
        "dataset_generation": "gen-1",
        "config_sha256": "b" * 64,
        "work_plan_sha256": "c" * 64,
        "expires_at": "2026-12-31T23:59:59Z",
        "schema_version": SCHEMA_VERSION_V2,
        "creation_phase": "ANALYZE",
        "phase_epoch": 3,
        # Missing source_collection_epoch, cutoff, selection_id
    }
    with pytest.raises(ValueError, match="V2 ANALYZE manifest requires positive integer source_collection_epoch"):
        CampaignManifest.from_dict(raw_analyze)

    raw_analyze_valid = {
        **raw_analyze,
        "source_collection_epoch": 2,
        "collection_cutoff_at_utc": "2026-09-27T02:00:00Z",
        "dataset_selection_id": "sel-123",
    }
    m = CampaignManifest.from_dict(raw_analyze_valid)
    assert m.creation_phase == "ANALYZE"
    assert m.dataset_selection_id == "sel-123"


def test_v2_lease_and_selection_epoch_enforcement():
    raw_v2 = {
        "campaign_id": "c4",
        "kind": "market_collection",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "a" * 40,
        "dataset_repo": "Rapt0r06300/alina-smartflow-datasets-v2",
        "dataset_generation": "gen-1",
        "config_sha256": "b" * 64,
        "work_plan_sha256": "c" * 64,
        "expires_at": "2026-12-31T23:59:59Z",
        "schema_version": SCHEMA_VERSION_V2,
        "creation_phase": "COLLECT",
        "phase_epoch": 5,
    }
    m = CampaignManifest.from_dict(raw_v2)

    # Stale epoch lease acquisition rejected
    with pytest.raises(ValueError, match="Stale phase epoch"):
        acquire_lease(m, "run-1", ttl_s=300, expected_phase="COLLECT", expected_epoch=4)

    # Valid phase and epoch acquire lease
    token = acquire_lease(m, "run-1", ttl_s=300, expected_phase="COLLECT", expected_epoch=5)
    assert token is not None

    # Due campaign selection filter by phase and epoch
    items = [m]
    due_stale = select_due_campaigns(items, current_phase="COLLECT", current_epoch=4)
    assert len(due_stale) == 0

    due_current = select_due_campaigns(items, current_phase="COLLECT", current_epoch=5)
    # lease is currently active so 0 due
    assert len(due_current) == 0


def test_dispatch_receipt_generation():
    req_id1 = generate_request_id(
        operator_intent="start_collection",
        main_code_sha="a" * 40,
        requested_phase_epoch=1,
        campaign_kind="market_collection",
        normalized_config={"symbols": ["BTC", "ETH"]},
    )
    req_id2 = generate_request_id(
        operator_intent="start_collection",
        main_code_sha="a" * 40,
        requested_phase_epoch=1,
        campaign_kind="market_collection",
        normalized_config={"symbols": ["BTC", "ETH"]},
    )
    assert req_id1 == req_id2

    receipt = DispatchReceipt(
        request_id=req_id1,
        campaign_id="c1",
        main_code_sha="a" * 40,
        dataset_repo_sha="d" * 40,
        creation_phase="COLLECT",
        phase_epoch=1,
        source_collection_epoch=None,
        workflow_run_id="run-99",
        dispatched_at_utc="2026-09-27T00:00:00Z",
    )
    assert receipt.request_id == req_id1
    assert receipt.content_digest() is not None


def test_v2_analysis_manifest_can_supersede_prior_terminal_campaign():
    raw = {
        "campaign_id": "analysis-e3-pnl-proof-v3",
        "kind": "module_pnl_proof",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "d" * 40,
        "dataset_repo": "Rapt0r06300/alina-smartflow-datasets-v2",
        "dataset_generation": "V2_FRESH",
        "config_sha256": "e" * 64,
        "work_plan_sha256": "f" * 64,
        "expires_at": "2026-12-31T23:59:59Z",
        "schema_version": SCHEMA_VERSION_V2,
        "creation_phase": "ANALYZE",
        "phase_epoch": 3,
        "source_collection_epoch": 2,
        "collection_cutoff_at_utc": "2026-09-29T10:56:59Z",
        "dataset_selection_id": "selection-3",
        "analysis_stage": "PNL_PROOF",
        "supersedes": "analysis-e3-pnl-proof-v2",
    }
    manifest = CampaignManifest.from_dict(raw)
    assert manifest.supersedes == "analysis-e3-pnl-proof-v2"
    assert manifest.to_dict()["supersedes"] == "analysis-e3-pnl-proof-v2"


def test_v2_manifest_refuses_self_supersession():
    raw = {
        "campaign_id": "same-id",
        "kind": "replay",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "a" * 40,
        "dataset_repo": "Rapt0r06300/alina-smartflow-datasets-v2",
        "dataset_generation": "V2_FRESH",
        "config_sha256": "b" * 64,
        "work_plan_sha256": "c" * 64,
        "expires_at": "2026-12-31T23:59:59Z",
        "schema_version": SCHEMA_VERSION_V2,
        "creation_phase": "ANALYZE",
        "phase_epoch": 3,
        "source_collection_epoch": 2,
        "collection_cutoff_at_utc": "2026-09-29T10:56:59Z",
        "dataset_selection_id": "selection-3",
        "analysis_stage": "REPLAY",
        "supersedes": "same-id",
    }
    with pytest.raises(ValueError, match="cannot supersede itself"):
        CampaignManifest.from_dict(raw)

def test_save_expected_digest_normalizes_new_optional_fields(tmp_path):
    path = tmp_path / "campaign.json"
    raw = {
        "campaign_id": "legacy-shape",
        "kind": "market_collection",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "a" * 40,
        "dataset_repo": "Rapt0r06300/alina-smartflow-datasets-v2",
        "dataset_generation": "V2_FRESH",
        "config_sha256": "b" * 64,
        "work_plan_sha256": "c" * 64,
        "expires_at": "2026-12-31T23:59:59Z",
        "schema_version": SCHEMA_VERSION_V2,
        "creation_phase": "COLLECT",
        "phase_epoch": 3,
    }
    # Simulate a durable manifest written before the optional supersedes field
    # existed in the schema.
    path.write_text(json.dumps(raw), encoding="utf-8")
    manifest = CampaignManifest.from_dict(raw)
    expected = __import__(
        "hl_observer.control_plane.resumable_campaign",
        fromlist=["sha256_json"],
    ).sha256_json(manifest.to_dict())

    save(path, manifest, expected)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "supersedes" in persisted
    assert persisted["supersedes"] is None

