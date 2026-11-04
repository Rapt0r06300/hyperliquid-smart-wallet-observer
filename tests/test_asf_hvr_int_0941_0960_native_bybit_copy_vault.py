"""Fail-closed Bybit-to-resumable-campaign boundary coverage."""

from datetime import datetime, timedelta, timezone

from hl_observer.control_plane.resumable_campaign import (
    SCHEMA_VERSION_V2, CampaignManifest, native_venue_to_campaign_boundary_receipt,
)
from hl_observer.venues.bybit import capacites, venue_capability_safety_receipt


def _manifest() -> CampaignManifest:
    now = datetime.now(timezone.utc)
    return CampaignManifest(
        "c1", "market_collection", "Rapt0r06300/hyperliquid-smart-wallet-observer", "a" * 40,
        "Rapt0r06300/hyperliquid-smart-wallet-observer", "g1", "b" * 64, "c" * 64,
        (now + timedelta(days=1)).isoformat(), schema_version=SCHEMA_VERSION_V2,
        created_at=now.isoformat(), creation_phase="COLLECT", phase_epoch=1,
    )


def test_asf_hvr_int_0941_positive_boundary() -> None:
    assert native_venue_to_campaign_boundary_receipt(capacites(), _manifest())["status"] == "PROVEN"


def test_asf_hvr_int_0942_wrong_venue_rejected() -> None:
    row = capacites(); row["venue"] = "other"
    assert native_venue_to_campaign_boundary_receipt(row, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0943_missing_book_rejected() -> None:
    row = capacites(); row["flux"] = tuple(x for x in row["flux"] if x != "book")
    assert native_venue_to_campaign_boundary_receipt(row, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0944_orders_forbidden() -> None:
    row = capacites(); row["flux"] = (*row["flux"], "orders")
    assert native_venue_to_campaign_boundary_receipt(row, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0945_offline_adapter_required() -> None:
    row = capacites(); row["adaptateur"] = "LIVE"
    assert native_venue_to_campaign_boundary_receipt(row, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0946_network_gate_required() -> None:
    row = capacites(); row["pull_live"] = "ENABLED"
    assert native_venue_to_campaign_boundary_receipt(row, _manifest())["status"] == "REJECTED"


def test_asf_hvr_int_0947_manifest_required() -> None:
    assert native_venue_to_campaign_boundary_receipt(capacites(), {})["status"] == "REJECTED"


def test_asf_hvr_int_0948_manifest_hash_checked() -> None:
    row = _manifest().to_dict(); row["config_sha256"] = ""
    assert native_venue_to_campaign_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0949_manifest_schema_checked() -> None:
    row = _manifest().to_dict(); row["schema_version"] = "invalid"
    assert native_venue_to_campaign_boundary_receipt(capacites(), row)["status"] == "REJECTED"


def test_asf_hvr_int_0950_paper_only() -> None:
    out = native_venue_to_campaign_boundary_receipt(capacites(), _manifest())
    assert out["paper_read_only"] is True and out["real_execution"] is False


def test_asf_hvr_int_0951_network_disabled() -> None:
    assert native_venue_to_campaign_boundary_receipt(capacites(), _manifest())["network_execution"] is False


def test_asf_hvr_int_0952_manifest_mutation_disabled() -> None:
    assert native_venue_to_campaign_boundary_receipt(capacites(), _manifest())["manifest_mutation"] is False


def test_asf_hvr_int_0953_promotion_disabled() -> None:
    assert native_venue_to_campaign_boundary_receipt(capacites(), _manifest())["promotion_disabled"] is True


def test_asf_hvr_int_0954_venue_receipt_safe() -> None:
    assert venue_capability_safety_receipt(capacites())["status"] == "PROVEN"


def test_asf_hvr_int_0955_venue_receipt_rejects_none() -> None:
    assert venue_capability_safety_receipt(None)["status"] == "REJECTED"


def test_asf_hvr_int_0956_bad_flux_rejected() -> None:
    row = capacites(); row["flux"] = None
    assert venue_capability_safety_receipt(row)["status"] == "REJECTED"


def test_asf_hvr_int_0957_bad_boundary_fails_closed() -> None:
    assert native_venue_to_campaign_boundary_receipt(None, None)["fail_closed"] is True


def test_asf_hvr_int_0958_manifest_unchanged() -> None:
    manifest = _manifest(); before = manifest.to_dict()
    native_venue_to_campaign_boundary_receipt(capacites(), manifest)
    assert manifest.to_dict() == before


def test_asf_hvr_int_0959_statuses_reported() -> None:
    out = native_venue_to_campaign_boundary_receipt(capacites(), _manifest())
    assert out["venue_status"] == "PROVEN" and out["campaign_status"] == "PROVEN"


def test_asf_hvr_int_0960_fail_closed_is_false_only_when_valid() -> None:
    assert native_venue_to_campaign_boundary_receipt(capacites(), _manifest())["fail_closed"] is False
