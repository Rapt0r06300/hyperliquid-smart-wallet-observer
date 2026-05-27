from __future__ import annotations

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation, require_testnet_confirmation


class TestnetExchangeClient:
    """Locked testnet exchange scaffold.

    This class never enables mainnet and refuses execution by default.
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def place_order(self, order: dict, *, confirm_testnet_only: bool = False) -> None:
        require_testnet_confirmation(confirm_testnet_only)
        if not self.config.testnet_execution_enabled:
            raise SafetyViolation(
                "EXECUTION_DISABLED_BY_DEFAULT",
                "Testnet execution is disabled by default.",
            )
        raise SafetyViolation(
            "TESTNET_CONFIRMATION_REQUIRED",
            "Sprint 1 does not implement order execution.",
        )
