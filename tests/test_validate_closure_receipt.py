from __future__ import annotations

import pytest

from tools.validate_closure_receipt import validate_economic_scope_statuses


def _statuses() -> dict[str, str]:
    return {
        "copy_vault_status": "MORE_DATA",
        "lead_lag_status": "DISABLED_BY_SCOPE",
        "cross_venue_status": "DISABLED_BY_SCOPE",
        "oos_status": "MORE_DATA",
        "forward_status": "MORE_DATA",
        "two_segment_resume_status": "PROVEN",
    }


def test_validator_accepts_copy_vault_only_scope() -> None:
    validate_economic_scope_statuses(_statuses())


@pytest.mark.parametrize("field", ["lead_lag_status", "cross_venue_status"])
def test_validator_rejects_out_of_scope_family_status(field: str) -> None:
    receipt = _statuses()
    receipt[field] = "PROVEN"
    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        validate_economic_scope_statuses(receipt)


def test_validator_rejects_invalid_copy_vault_status() -> None:
    receipt = _statuses()
    receipt["copy_vault_status"] = "DISABLED_BY_SCOPE"
    with pytest.raises(ValueError, match="copy_vault_status"):
        validate_economic_scope_statuses(receipt)
