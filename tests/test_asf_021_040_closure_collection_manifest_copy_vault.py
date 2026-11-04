"""Fail-closed closure, collector and SAFE-manifest boundaries for ASF-021..040."""

from tools.build_closure_report import closure_boundary_safety_receipt
from tools.manifest_policy import manifest_safety_receipt
from hl_observer.collection.collector import CollectionPlan, collection_scope_safety_receipt


def _plan() -> CollectionPlan:
    return CollectionPlan(fetch=False, dry_run=True, store_raw=True, coins=["BTC"])


def _manifest() -> dict[str, object]:
    return {
        "dataset_id":"copy-vault-btc", "family":"l2", "venue":"bybit", "symbol":"BTCUSDT",
        "start_ts_ms":1000, "end_ts_ms":2000, "sha256":"a"*64, "bytes":123, "event_count":2,
        "collector_version":"v1", "source":"bybit_public_ws", "quality_status":"SAFE",
        "asset_verified":True, "replay_compatible":True, "replay_schema_version":"alina.replay.v1",
        "replay_reason":"SAFE_REPLAY", "provenance":{"public_data_only":True,"authenticated":False,"real_execution":False,"transports":["websocket"]},
        "integrity":{"gap_count":0,"regression_count":0,"missing_timestamp_count":0,"missing_monotonic_count":0,"desync_count":0,"duplicate_count":0,"duplicates_deduped":True},
        "reconciliation":{"status":"SOURCE_CONTINUITY_VERIFIED"}, "required_channels":["l2Book"], "observed_channels":["l2Book"],
    }


def _report() -> dict[str, object]:
    return {"status":"PROVEN","paper_read_only":True,"real_execution":False,"evidence_digest":"a"*64,"task_status_mutation":False}


def test_asf_021_closure_positive() -> None:
    assert closure_boundary_safety_receipt(_report())["status"] == "PROVEN"


def test_asf_022_closure_requires_digest() -> None:
    row = _report(); row["evidence_digest"] = "bad"
    assert closure_boundary_safety_receipt(row)["status"] == "REJECTED"


def test_asf_023_closure_requires_paper() -> None:
    row = _report(); row["paper_read_only"] = False
    assert closure_boundary_safety_receipt(row)["status"] == "REJECTED"


def test_asf_024_closure_rejects_mutation() -> None:
    row = _report(); row["task_status_mutation"] = True
    assert closure_boundary_safety_receipt(row)["status"] == "REJECTED"


def test_asf_025_closure_rejects_none() -> None:
    assert closure_boundary_safety_receipt(None)["fail_closed"] is True


def test_asf_026_collection_plan_positive() -> None:
    assert collection_scope_safety_receipt(_plan())["status"] == "PROVEN"


def test_asf_027_collection_requires_plan_type() -> None:
    assert collection_scope_safety_receipt({})["status"] == "REJECTED"


def test_asf_028_collection_rejects_execution_marker() -> None:
    assert collection_scope_safety_receipt({"execution_requested": True})["status"] == "REJECTED"


def test_asf_029_collection_is_read_only() -> None:
    out = collection_scope_safety_receipt(_plan())
    assert out["paper_read_only"] is True and out["real_execution"] is False


def test_asf_030_collection_network_execution_disabled() -> None:
    assert collection_scope_safety_receipt(_plan())["network_execution"] is False


def test_asf_031_collection_mutation_disabled() -> None:
    assert collection_scope_safety_receipt(_plan())["collection_mutation"] is False


def test_asf_032_collection_fail_closed_on_none() -> None:
    assert collection_scope_safety_receipt(None)["fail_closed"] is True


def test_asf_033_manifest_positive() -> None:
    assert manifest_safety_receipt(_manifest())["status"] == "PROVEN"


def test_asf_034_manifest_requires_safe_quality() -> None:
    row = _manifest(); row["quality_status"] = "PARTIAL"
    assert manifest_safety_receipt(row)["status"] == "REJECTED"


def test_asf_035_manifest_requires_verified_asset() -> None:
    row = _manifest(); row["asset_verified"] = False
    assert manifest_safety_receipt(row)["status"] == "REJECTED"


def test_asf_036_manifest_requires_replay_compatibility() -> None:
    row = _manifest(); row["replay_compatible"] = False
    assert manifest_safety_receipt(row)["status"] == "REJECTED"


def test_asf_037_manifest_requires_public_read_only_provenance() -> None:
    row = _manifest(); row["provenance"]["real_execution"] = True
    assert manifest_safety_receipt(row)["status"] == "REJECTED"


def test_asf_038_manifest_rejects_invalid_input() -> None:
    assert manifest_safety_receipt(None)["fail_closed"] is True


def test_asf_039_manifest_never_mutates_input() -> None:
    row = _manifest(); before = dict(row)
    manifest_safety_receipt(row)
    assert row == before


def test_asf_040_boundaries_report_fail_closed_contracts() -> None:
    assert closure_boundary_safety_receipt(_report())["closure_allowed"] is False
    assert manifest_safety_receipt(_manifest())["manifest_mutation"] is False
