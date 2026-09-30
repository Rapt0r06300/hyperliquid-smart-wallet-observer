from __future__ import annotations

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation, validate_runtime_config


def assert_execution_allowed(config: AppConfig, *, confirm_testnet_only: bool) -> None:
    validate_runtime_config(config)
    if not config.testnet_execution_enabled or not confirm_testnet_only:
        raise SafetyViolation(
            "TESTNET_CONFIRMATION_REQUIRED",
            "Execution is locked unless testnet-only confirmation is explicit.",
        )
