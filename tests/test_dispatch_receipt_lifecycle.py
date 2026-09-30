from __future__ import annotations

import pytest

from hl_observer.control_plane.dispatch_receipt import (
    DispatchReceipt,
    validate_dispatch_receipt,
)


def _base(**overrides):
    row = {
        "request_id": "request-1",
        "campaign_id": "campaign-1",
        "main_code_sha": "a" * 40,
        "dataset_repo_sha": "b" * 40,
        "creation_phase": "COLLECT",
        "phase_epoch": 1,
        "source_collection_epoch": None,
        "workflow_run_id": "run-1",
        "dispatched_at_utc": "2026-09-27T00:00:00Z",
    }
    row.update(overrides)
    return DispatchReceipt(**row)


def test_non_terminal_dispatch_is_explicitly_dispatched():
    receipt = _base()
    validate_dispatch_receipt(receipt)
    assert receipt.status == "DISPATCHED"
    assert receipt.terminal_at_utc is None


def test_complete_dispatch_requires_terminal_evidence():
    with pytest.raises(ValueError, match="terminal evidence"):
        validate_dispatch_receipt(
            _base(status="COMPLETE", terminal_at_utc="2026-09-27T00:01:00Z")
        )


def test_failed_dispatch_requires_failure_code():
    with pytest.raises(ValueError, match="failure_code"):
        validate_dispatch_receipt(
            _base(status="FAILED", terminal_at_utc="2026-09-27T00:01:00Z")
        )


def test_terminal_dispatch_cannot_look_running():
    with pytest.raises(ValueError, match="terminal_at_utc"):
        validate_dispatch_receipt(_base(status="RUNNING", terminal_at_utc="2026-09-27T00:01:00Z"))


def test_v1_complete_receipt_upgrades_to_terminal_state():
    raw = _base(terminal_evidence_digest="c" * 64).to_dict()
    raw.pop("status")
    raw.pop("terminal_at_utc")
    upgraded = DispatchReceipt.from_dict(raw)
    validate_dispatch_receipt(upgraded)
    assert upgraded.status == "COMPLETE"
    assert upgraded.terminal_at_utc == upgraded.dispatched_at_utc
