import pytest

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import (
    SafetyViolation,
    sanitize_for_logs,
    validate_runtime_config,
)


def test_hypersmart_mainnet_refused():
    with pytest.raises(SafetyViolation) as exc:
        validate_runtime_config(AppConfig(allow_mainnet=True))

    assert exc.value.reason_code == "MAINNET_FORBIDDEN"


def test_hypersmart_unknown_mode_refused():
    with pytest.raises(SafetyViolation) as exc:
        validate_runtime_config(AppConfig(mode="SOMETHING_ELSE"))

    assert exc.value.reason_code == "AMBIGUOUS_RUNTIME_MODE"


def test_hypersmart_execution_refused_without_confirmation():
    with pytest.raises(SafetyViolation) as exc:
        validate_runtime_config(AppConfig(execution_enabled=True))

    assert exc.value.reason_code == "EXECUTION_DISABLED_BY_DEFAULT"


def test_hypersmart_testnet_execution_refused_without_confirm_flag():
    with pytest.raises(SafetyViolation) as exc:
        validate_runtime_config(AppConfig(testnet_execution_enabled=True))

    assert exc.value.reason_code == "TESTNET_CONFIRMATION_REQUIRED"


def test_hypersmart_sanitize_for_logs_masks_secrets():
    raw = {
        "private_key": "private_key=0x" + "a" * 64,
        "nested": ["seed=very-secret-value"],
    }

    sanitized = sanitize_for_logs(raw)

    assert "very-secret-value" not in str(sanitized)
    assert "a" * 64 not in str(sanitized)
    assert "[REDACTED]" in str(sanitized)
