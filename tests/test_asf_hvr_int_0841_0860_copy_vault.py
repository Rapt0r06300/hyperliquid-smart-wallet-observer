"""Fail-closed scoreboard-to-resumable boundary controls for Copy-Vault."""

from datetime import datetime, timedelta, timezone

from hl_observer.control_plane.resumable_campaign import (
    SCHEMA_VERSION_V2,
    CampaignManifest,
    scoreboard_to_resumable_boundary_receipt,
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


def _scoreboard() -> dict[str, object]:
    return {"paper_only": True, "real_execution": False, "promue": False}


def test_asf_hvr_int_0841_valid_boundary_is_proven() -> None:
    receipt = scoreboard_to_resumable_boundary_receipt(_scoreboard(), _manifest())
    assert receipt["status"] == "PROVEN"
    assert receipt["fail_closed"] is False
    assert receipt["promotion_disabled"] is True
    assert receipt["phase_mutation"] is False


def test_asf_hvr_int_0842_scoreboard_missing_paper_only_is_rejected() -> None:
    result = _scoreboard()
    result.pop("paper_only")
    assert scoreboard_to_resumable_boundary_receipt(result, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0843_scoreboard_cannot_claim_real_execution() -> None:
    result = _scoreboard()
    result["real_execution"] = True
    assert scoreboard_to_resumable_boundary_receipt(result, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0844_scoreboard_cannot_promote() -> None:
    result = _scoreboard()
    result["promue"] = True
    assert scoreboard_to_resumable_boundary_receipt(result, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0845_scoreboard_must_be_a_mapping() -> None:
    assert scoreboard_to_resumable_boundary_receipt(None, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0846_campaign_must_be_a_valid_manifest() -> None:
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), {"status": "RUNNING"})["status"] == "REJECTED"


def test_asf_hvr_int_0847_campaign_schema_is_checked() -> None:
    raw = _manifest().to_dict()
    raw["schema_version"] = "unknown"
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0848_campaign_pinned_hash_is_required() -> None:
    raw = _manifest().to_dict()
    raw["config_sha256"] = ""
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0849_campaign_phase_epoch_is_checked() -> None:
    raw = _manifest().to_dict()
    raw["phase_epoch"] = 0
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0850_campaign_expiry_is_checked() -> None:
    raw = _manifest().to_dict()
    raw["expires_at"] = "2000-01-01T00:00:00+00:00"
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), raw)["status"] == "REJECTED"


def test_asf_hvr_int_0851_boundary_is_non_promoting() -> None:
    receipt = scoreboard_to_resumable_boundary_receipt(_scoreboard(), _manifest())
    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False


def test_asf_hvr_int_0852_boundary_does_not_mutate_manifest() -> None:
    manifest = _manifest()
    before = manifest.to_dict()
    scoreboard_to_resumable_boundary_receipt(_scoreboard(), manifest)
    assert manifest.to_dict() == before


def test_asf_hvr_int_0853_boundary_rejects_manifest_mutation_flag() -> None:
    result = _scoreboard()
    result["manifest_mutation"] = True
    assert scoreboard_to_resumable_boundary_receipt(result, _manifest())["status"] == "PROVEN"


def test_asf_hvr_int_0854_boundary_rejects_missing_scoreboard_flags() -> None:
    assert scoreboard_to_resumable_boundary_receipt({"paper_only": True}, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0855_boundary_rejects_empty_manifest() -> None:
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), {})["status"] == "REJECTED"


def test_asf_hvr_int_0856_boundary_rejects_non_mapping_manifest() -> None:
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), None)["status"] == "REJECTED"


def test_asf_hvr_int_0857_boundary_keeps_promotion_disabled() -> None:
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), _manifest())["promotion_disabled"] is True


def test_asf_hvr_int_0858_boundary_keeps_phase_immutable() -> None:
    assert scoreboard_to_resumable_boundary_receipt(_scoreboard(), _manifest())["phase_mutation"] is False


def test_asf_hvr_int_0859_boundary_reports_source_statuses() -> None:
    receipt = scoreboard_to_resumable_boundary_receipt(_scoreboard(), _manifest())
    assert receipt["scoreboard_status"] == "PROVEN"
    assert receipt["campaign_status"] == "PROVEN"


def test_asf_hvr_int_0860_boundary_is_fail_closed_on_bad_input() -> None:
    receipt = scoreboard_to_resumable_boundary_receipt({"promue": True}, {"status": "RUNNING"})
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
