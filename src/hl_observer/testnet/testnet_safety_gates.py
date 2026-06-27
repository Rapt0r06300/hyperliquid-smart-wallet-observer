from __future__ import annotations

from dataclasses import dataclass

from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.hyperliquid.schemas import RiskDecision, SignalDecision


class TestnetLocked(RuntimeError):
    __test__ = False

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("Testnet execution locked: " + ", ".join(reasons))
        self.reasons = reasons
        self.decision = SignalDecision.REJECT_TESTNET_LOCKED


@dataclass(frozen=True, slots=True)
class TestnetExecutionIntent:
    cloid: str | None
    confirm_testnet_only: bool
    schedule_cancel_required: bool
    schedule_cancel_configured: bool
    reduce_only: bool = False


def assert_testnet_unlocked(
    settings: Settings,
    risk_decision: RiskDecision,
    intent: TestnetExecutionIntent,
) -> None:
    reasons: list[str] = []
    if settings.environment != ExecutionEnvironment.TESTNET:
        reasons.append("HL_ENV must be testnet")
    if settings.execution.enable_mainnet_execution:
        reasons.append("mainnet execution flag must remain false")
    if not settings.execution.enable_testnet_execution:
        reasons.append("HL_ENABLE_TESTNET_EXECUTION must be true")
    if not intent.confirm_testnet_only:
        reasons.append("--confirm-testnet-only is required")
    if not intent.cloid:
        reasons.append("cloid is required")
    if intent.schedule_cancel_required and not intent.schedule_cancel_configured:
        reasons.append("scheduleCancel is required")
    if not risk_decision.allowed:
        reasons.append("risk engine rejected the signal")
    if reasons:
        raise TestnetLocked(reasons)
