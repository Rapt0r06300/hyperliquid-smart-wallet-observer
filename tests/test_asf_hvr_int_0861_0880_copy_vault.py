"""Fail-closed dispatch-to-campaign boundary controls for Copy-Vault."""

from datetime import datetime, timedelta, timezone

from hl_observer.control_plane.dispatch_receipt import (
    DispatchReceipt,
    dispatch_to_campaign_boundary_receipt,
)
from hl_observer.control_plane.resumable_campaign import SCHEMA_VERSION_V2, CampaignManifest


def _dispatch() -> DispatchReceipt:
    return DispatchReceipt(
        request_id="r1",
        campaign_id="c1",
        main_code_sha="a" * 40,
        dataset_repo_sha="b" * 40,
        creation_phase="COLLECT",
        phase_epoch=1,
        source_collection_epoch=None,
        workflow_run_id=None,
        dispatched_at_utc="2026-01-01T00:00:00Z",
    )


def _manifest() -> CampaignManifest:
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


def test_asf_hvr_int_0861_valid_boundary_is_proven() -> None:
    receipt = dispatch_to_campaign_boundary_receipt(_dispatch(), _manifest())
    assert receipt["status"] == "PROVEN"
    assert receipt["fail_closed"] is False


def test_asf_hvr_int_0862_dispatch_mapping_is_validated() -> None:
    assert dispatch_to_campaign_boundary_receipt({}, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0863_dispatch_identity_is_required() -> None:
    raw = _dispatch().to_dict()
    raw["request_id"] = ""
    assert dispatch_to_campaign_boundary_receipt(raw, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0864_dispatch_code_sha_is_required() -> None:
    raw = _dispatch().to_dict()
    raw["main_code_sha"] = "bad"
    assert dispatch_to_campaign_boundary_receipt(raw, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0865_dispatch_phase_epoch_is_required() -> None:
    raw = _dispatch().to_dict()
    raw["phase_epoch"] = 0
    assert dispatch_to_campaign_boundary_receipt(raw, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0866_dispatch_phase_is_required() -> None:
    raw = _dispatch().to_dict()
    raw["creation_phase"] = "UNKNOWN"
    assert dispatch_to_campaign_boundary_receipt(raw, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0867_dispatch_rejects_invalid_timestamp() -> None:
    raw = _dispatch().to_dict()
    raw["dispatched_at_utc"] = "not-a-timestamp"
    assert dispatch_to_campaign_boundary_receipt(raw, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0868_campaign_is_validated() -> None:
    assert dispatch_to_campaign_boundary_receipt(_dispatch(), {"status": "RUNNING"})["status"] == "REJECTED"


def test_asf_hvr_int_0869_campaign_schema_is_required() -> None:
    raw = _manifest().to_dict()
    raw["schema_version"] = "unknown"
    assert dispatch_to_campaign_boundary_receipt(_dispatch(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0870_campaign_hash_is_required() -> None:
    raw = _manifest().to_dict()
    raw["work_plan_sha256"] = ""
    assert dispatch_to_campaign_boundary_receipt(_dispatch(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0871_boundary_is_paper_only() -> None:
    receipt = dispatch_to_campaign_boundary_receipt(_dispatch(), _manifest())
    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False


def test_asf_hvr_int_0872_boundary_does_not_dispatch() -> None:
    assert dispatch_to_campaign_boundary_receipt(_dispatch(), _manifest())["dispatch_mutation"] is False


def test_asf_hvr_int_0873_boundary_does_not_mutate_manifest() -> None:
    manifest = _manifest()
    before = manifest.to_dict()
    dispatch_to_campaign_boundary_receipt(_dispatch(), manifest)
    assert manifest.to_dict() == before


def test_asf_hvr_int_0874_boundary_keeps_phase_immutable() -> None:
    assert dispatch_to_campaign_boundary_receipt(_dispatch(), _manifest())["phase_mutation"] is False


def test_asf_hvr_int_0875_boundary_reports_dispatch_status() -> None:
    assert dispatch_to_campaign_boundary_receipt(_dispatch(), _manifest())["dispatch_status"] == "PROVEN"


def test_asf_hvr_int_0876_boundary_reports_campaign_status() -> None:
    assert dispatch_to_campaign_boundary_receipt(_dispatch(), _manifest())["campaign_status"] == "PROVEN"


def test_asf_hvr_int_0877_terminal_dispatch_requires_evidence() -> None:
    raw = _dispatch().to_dict()
    raw["status"] = "COMPLETE"
    raw["terminal_at_utc"] = "2026-01-01T00:00:00Z"
    assert dispatch_to_campaign_boundary_receipt(raw, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0878_boundary_rejects_non_mapping_campaign() -> None:
    assert dispatch_to_campaign_boundary_receipt(_dispatch(), None)["status"] == "REJECTED"


def test_asf_hvr_int_0879_boundary_is_fail_closed_on_bad_inputs() -> None:
    receipt = dispatch_to_campaign_boundary_receipt(None, None)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True


def test_asf_hvr_int_0880_boundary_is_non_promoting() -> None:
    receipt = dispatch_to_campaign_boundary_receipt(_dispatch(), _manifest())
    assert receipt["promotion"] == "DISABLED_UNTIL_REVIEW"
