from __future__ import annotations

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation
from hyper_smart_observer.execution.execution_guard import assert_execution_allowed
from hyper_smart_observer.execution.order_builder import OrderIntent


class TestnetExecutor:
    """Future mock-USDC executor; Sprint 1 refuses every submission."""

    def __init__(self, config: AppConfig):
        self.config = config

    def submit(self, order: OrderIntent, *, confirm_testnet_only: bool = False) -> None:
        assert_execution_allowed(self.config, confirm_testnet_only=confirm_testnet_only)
        raise SafetyViolation("EXECUTION_DISABLED_BY_DEFAULT", "Sprint 1 has no execution path.")
