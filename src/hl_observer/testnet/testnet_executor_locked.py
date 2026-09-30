from __future__ import annotations

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.schemas import RiskDecision
from hl_observer.testnet.testnet_order_builder import TestnetOrderIntent
from hl_observer.testnet.testnet_safety_gates import (
    TestnetExecutionIntent,
    assert_testnet_unlocked,
)


class LockedTestnetExecutor:
    """Scaffold only: validates safety gates and never talks to mainnet."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def submit(
        self,
        order: TestnetOrderIntent,
        risk_decision: RiskDecision,
        *,
        confirm_testnet_only: bool = False,
    ) -> dict[str, str]:
        intent = TestnetExecutionIntent(
            cloid=order.cloid,
            confirm_testnet_only=confirm_testnet_only,
            schedule_cancel_required=self.settings.execution.require_schedule_cancel,
            schedule_cancel_configured=order.schedule_cancel_configured,
            reduce_only=order.reduce_only,
        )
        assert_testnet_unlocked(self.settings, risk_decision, intent)
        return {"status": "validated_testnet_only", "cloid": order.cloid}
