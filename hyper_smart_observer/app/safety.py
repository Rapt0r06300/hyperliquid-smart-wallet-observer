from __future__ import annotations

import re
from dataclasses import asdict
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass
from typing import Any

from hyper_smart_observer.app.config import AppConfig, FORBIDDEN_MODE_TERMS, RuntimeMode
from hyper_smart_observer.hyperliquid_client.models import RiskEvent


class SafetyViolation(RuntimeError):
    """Raised when runtime configuration or action violates the safety policy."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


class RefusalReason(StrEnum):
    MAINNET_FORBIDDEN = "MAINNET_FORBIDDEN"
    REAL_MONEY_FORBIDDEN = "REAL_MONEY_FORBIDDEN"
    EXECUTION_DISABLED_BY_DEFAULT = "EXECUTION_DISABLED_BY_DEFAULT"
    TESTNET_CONFIRMATION_REQUIRED = "TESTNET_CONFIRMATION_REQUIRED"
    SECRET_LOGGING_BLOCKED = "SECRET_LOGGING_BLOCKED"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    AMBIGUOUS_RUNTIME_MODE = "AMBIGUOUS_RUNTIME_MODE"
    CONFIGURATION_REFUSED = "CONFIGURATION_REFUSED"


SECRET_PATTERNS = (
    re.compile(r"0x[a-fA-F0-9]{64}"),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(private[_-]?key|seed|mnemonic|secret)\s*=\s*[^,\s]+"),
)


def validate_runtime_config(config: AppConfig) -> None:
    assert_no_real_money_mode(config)
    assert_mainnet_disabled(config)
    assert_execution_denied_by_default(config)
    if config.sensitive_key_material and not (
        config.runtime_mode == RuntimeMode.TESTNET_EXECUTION_LOCKED
        and config.confirm_testnet_only
        and config.testnet_execution_enabled
    ):
        raise SafetyViolation(
            RefusalReason.CONFIGURATION_REFUSED,
            "Private key present without explicit locked testnet confirmation.",
        )


def assert_mainnet_disabled(config: AppConfig) -> None:
    if config.allow_mainnet:
        raise SafetyViolation(RefusalReason.MAINNET_FORBIDDEN, "Mainnet is out of scope.")
    for value in (config.hyperliquid_info_base_url, config.hyperliquid_ws_base_url):
        lowered = value.lower()
        forbidden_path = "/" + "exchange"
        if forbidden_path in lowered or "mainnet" in lowered:
            raise SafetyViolation(
                RefusalReason.MAINNET_FORBIDDEN,
                "Forbidden execution endpoint detected in configuration.",
            )


def assert_no_real_money_mode(config: AppConfig) -> None:
    mode = config.mode.strip().upper()
    if "MAINNET" in mode:
        raise SafetyViolation(
            RefusalReason.MAINNET_FORBIDDEN,
            f"Forbidden runtime mode refused: {mode}",
        )
    if any(term in mode for term in FORBIDDEN_MODE_TERMS):
        raise SafetyViolation(
            RefusalReason.REAL_MONEY_FORBIDDEN,
            f"Forbidden runtime mode refused: {mode}",
        )
    try:
        RuntimeMode(mode)
    except ValueError as exc:
        raise SafetyViolation(
            RefusalReason.AMBIGUOUS_RUNTIME_MODE,
            f"Unknown or ambiguous runtime mode refused: {mode}",
        ) from exc


def assert_execution_denied_by_default(config: AppConfig) -> None:
    if config.execution_enabled and not config.testnet_execution_enabled:
        raise SafetyViolation(
            RefusalReason.EXECUTION_DISABLED_BY_DEFAULT,
            "Execution cannot be enabled outside locked testnet mode.",
        )
    if config.testnet_execution_enabled and not config.confirm_testnet_only:
        raise SafetyViolation(
            RefusalReason.TESTNET_CONFIRMATION_REQUIRED,
            "Testnet execution requires --confirm-testnet-only.",
        )


def require_testnet_confirmation(flag_value: bool) -> None:
    if not flag_value:
        raise SafetyViolation(
            RefusalReason.TESTNET_CONFIRMATION_REQUIRED,
            "Explicit --confirm-testnet-only is required.",
        )


def sanitize_for_logs(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_for_logs(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_logs(item) for item in value]
    if value is None:
        return None
    text = str(value)
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def create_risk_event_for_refusal(
    *,
    reason_code: str,
    message: str,
    blocked_action: str,
    component: str = "safety",
    context: dict[str, Any] | None = None,
) -> RiskEvent:
    return RiskEvent(
        severity="CRITICAL",
        component=component,
        reason_code=reason_code,
        message=message,
        blocked_action=blocked_action,
        context=sanitize_for_logs(context or {}),
    )


def config_snapshot(config: AppConfig) -> dict[str, Any]:
    snapshot = asdict(config)
    snapshot["database_path"] = str(config.database_path)
    snapshot["sensitive_key_material"] = sanitize_for_logs(snapshot.get("sensitive_key_material"))
    return snapshot
