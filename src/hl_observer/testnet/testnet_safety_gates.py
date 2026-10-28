from __future__ import annotations

from dataclasses import dataclass

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.schemas import RiskDecision, SignalDecision
from hl_observer.testnet.safety import TESTNET_DISABLED_REASON


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
    raise TestnetLocked([TESTNET_DISABLED_REASON])
