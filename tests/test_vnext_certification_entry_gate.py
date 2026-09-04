import pytest

from hl_observer.simulation import vnext_promotion_protocol as protocol


_REQUIRED_ECONOMIC_PROOFS = (
    "costs_complete",
    "liquidability_complete",
    "provenance_complete",
    "positions_flat",
    "economic_reconciliation_ok",
)

_REQUIRED_TEMPORAL_PROOFS = (
    "validation_without_recalibration",
    "temporal_disjointness_ok",
    "forward_post_freeze_complete",
    "placebo_complete",
)


def _candidate(status: str) -> dict[str, object]:
    return {
        "certification_status": status,
        "freeze_hash": "a" * 64,
        "post_freeze_oos_consumed": True,
        "paper_read_only": True,
        "real_execution": False,
        **{field: True for field in _REQUIRED_ECONOMIC_PROOFS},
        **{field: True for field in _REQUIRED_TEMPORAL_PROOFS},
    }


def test_train_only_candidate_is_rejected_from_certified_namespace() -> None:
    gate = getattr(protocol, "validate_certification_entry", None)
    assert callable(gate), "certification namespace gate must exist"
    with pytest.raises(ValueError, match="TRAIN_ONLY_NOT_CERTIFIED"):
        gate(_candidate("TRAIN_ONLY_NOT_CERTIFIED"))


def test_only_explicit_ready_candidate_with_consumed_oos_is_eligible() -> None:
    gate = getattr(protocol, "validate_certification_entry", None)
    assert callable(gate), "certification namespace gate must exist"
    assert gate(_candidate("CERTIFICATION_READY")) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("freeze_hash", None),
        ("post_freeze_oos_consumed", False),
        ("paper_read_only", False),
        ("real_execution", True),
    ],
)
def test_certification_entry_fails_closed_when_proof_or_safety_is_incomplete(
    field: str,
    value: object,
) -> None:
    gate = getattr(protocol, "validate_certification_entry", None)
    assert callable(gate), "certification namespace gate must exist"
    candidate = _candidate("CERTIFICATION_READY")
    candidate[field] = value
    with pytest.raises(ValueError):
        gate(candidate)


@pytest.mark.parametrize("field", _REQUIRED_ECONOMIC_PROOFS)
def test_certification_entry_rejects_incomplete_economic_proof(field: str) -> None:
    candidate = _candidate("CERTIFICATION_READY")
    candidate[field] = False
    with pytest.raises(ValueError, match=field):
        protocol.validate_certification_entry(candidate)


@pytest.mark.parametrize("field", _REQUIRED_ECONOMIC_PROOFS)
def test_certification_entry_rejects_missing_economic_proof(field: str) -> None:
    candidate = _candidate("CERTIFICATION_READY")
    candidate.pop(field)
    with pytest.raises(ValueError, match=field):
        protocol.validate_certification_entry(candidate)


@pytest.mark.parametrize("field", _REQUIRED_TEMPORAL_PROOFS)
def test_certification_entry_rejects_incomplete_temporal_proof(field: str) -> None:
    candidate = _candidate("CERTIFICATION_READY")
    candidate[field] = False
    with pytest.raises(ValueError, match=field):
        protocol.validate_certification_entry(candidate)


@pytest.mark.parametrize("field", _REQUIRED_TEMPORAL_PROOFS)
def test_certification_entry_rejects_missing_temporal_proof(field: str) -> None:
    candidate = _candidate("CERTIFICATION_READY")
    candidate.pop(field)
    with pytest.raises(ValueError, match=field):
        protocol.validate_certification_entry(candidate)
