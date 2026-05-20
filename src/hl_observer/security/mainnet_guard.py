from __future__ import annotations

from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.hyperliquid.schemas import SignalDecision


class MainnetExecutionForbidden(RuntimeError):
    def __init__(self, reason: str = "Mainnet execution is forbidden in this MVP") -> None:
        super().__init__(reason)
        self.decision = SignalDecision.REJECT_MAINNET_FORBIDDEN


def assert_mainnet_execution_disabled(settings: Settings) -> None:
    if settings.execution.enable_mainnet_execution:
        raise MainnetExecutionForbidden("HL_ENABLE_MAINNET_EXECUTION=true is forbidden")


def assert_not_mainnet_execution(settings: Settings) -> None:
    assert_mainnet_execution_disabled(settings)
    if settings.environment == ExecutionEnvironment.MAINNET:
        raise MainnetExecutionForbidden("Execution commands are forbidden when HL_ENV=mainnet")


def assert_info_endpoint_only(url: str) -> None:
    if not url.endswith("/info"):
        raise MainnetExecutionForbidden("Only the Hyperliquid /info endpoint is allowed")
