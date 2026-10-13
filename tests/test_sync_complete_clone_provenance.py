"""A completed restore must be bound to the clone's CURRENT catalog index."""
from __future__ import annotations

import json

from tools.sync_complete_clone import _read_restore_status, REPOSITORY

SOURCE = "a" * 64
OLD = "b" * 64


def report(tmp_path, *, bound=SOURCE):
    path = tmp_path / "RESTORE_REPORT.json"
    path.write_text(json.dumps({
        "schema": "alina.restore_report.v1",
        "repository": REPOSITORY,
        "profile": "replay-ready",
        "status": "REPLAY_READY_COMPLETE",
        "source_inventory_sha256": "c" * 64,
        "catalog_verification": {"source_index_sha256": bound},
    }))
    return path


def test_matching_sha_binds_restore_to_exact_clone_index(tmp_path):
    path = report(tmp_path)
    assert _read_restore_status(path, expected_catalog_sha256=SOURCE) == (
        "REPLAY_READY_COMPLETE", "c" * 64, None,
    )


def test_old_success_receipt_is_not_a_current_restore_certificate(tmp_path):
    path = report(tmp_path, bound=OLD)
    status, inventory, reason = _read_restore_status(
        path, expected_catalog_sha256=SOURCE
    )
    assert status == "RESTORE_INCOMPLETE"
    assert inventory == "c" * 64
    assert "current canonical DATA_INDEX" in reason
    assert path.exists()


def test_missing_catalog_verification_fails_closed(tmp_path):
    path = report(tmp_path)
    data = json.loads(path.read_text())
    data.pop("catalog_verification")
    path.write_text(json.dumps(data))
    status, _, reason = _read_restore_status(path, expected_catalog_sha256=SOURCE)
    assert status == "RESTORE_INCOMPLETE"
    assert "not bound" in reason


def test_foreign_restore_report_does_not_certify_clone(tmp_path):
    path = report(tmp_path)
    data = json.loads(path.read_text())
    data["repository"] = "foreign/repository"
    path.write_text(json.dumps(data))
    status, _, reason = _read_restore_status(path, expected_catalog_sha256=SOURCE)
    assert status == "RESTORE_INCOMPLETE"
    assert "repository mismatch" in reason
