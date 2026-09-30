import pytest

from hl_observer.simulation import vnext_promotion_protocol as protocol


def _windows() -> dict[str, dict[str, int]]:
    return {
        "validation": {"start_ms": 1_100, "end_ms": 1_200},
        "oos": {"start_ms": 1_200, "end_ms": 1_300},
        "forward": {"start_ms": 1_300, "end_ms": 1_400},
        "placebo": {"start_ms": 1_400, "end_ms": 1_500},
    }


def test_temporal_windows_are_machine_verified_after_freeze() -> None:
    validator = getattr(protocol, "validate_temporal_disjointness", None)
    assert callable(validator), "machine-derived temporal validator must exist"
    assert validator(_windows(), frozen_at_ms=1_000) is True


@pytest.mark.parametrize("field", ["validation", "oos", "forward", "placebo"])
def test_temporal_validator_rejects_missing_window(field: str) -> None:
    windows = _windows()
    windows.pop(field)
    with pytest.raises(ValueError, match=field):
        protocol.validate_temporal_disjointness(windows, frozen_at_ms=1_000)


def test_temporal_validator_rejects_overlap() -> None:
    windows = _windows()
    windows["oos"] = {"start_ms": 1_150, "end_ms": 1_300}
    with pytest.raises(ValueError, match="overlap"):
        protocol.validate_temporal_disjointness(windows, frozen_at_ms=1_000)


def test_temporal_validator_rejects_pre_freeze_evidence() -> None:
    windows = _windows()
    windows["validation"] = {"start_ms": 999, "end_ms": 1_100}
    with pytest.raises(ValueError, match="post-freeze"):
        protocol.validate_temporal_disjointness(windows, frozen_at_ms=1_000)


def test_temporal_validator_rejects_empty_or_reversed_window() -> None:
    windows = _windows()
    windows["forward"] = {"start_ms": 1_350, "end_ms": 1_350}
    with pytest.raises(ValueError, match="forward"):
        protocol.validate_temporal_disjointness(windows, frozen_at_ms=1_000)
