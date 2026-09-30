from __future__ import annotations

from hl_observer.hyperliquid.schemas import RiskDecision, SignalDecision


class LiveExecutionDisabled(RuntimeError):
    pass


class LiveExecutorDisabled:
    """Hard stop for every live/mainnet execution attempt."""

    def place_order(self, *_args: object, **_kwargs: object) -> None:
        raise LiveExecutionDisabled("Mainnet live execution is disabled and unavailable in the MVP")


def refuse_live_execution() -> RiskDecision:
    return RiskDecision(
        allowed=False,
        decision=SignalDecision.REJECT_MAINNET_FORBIDDEN,
        reasons=["mainnet live execution is disabled"],
        gates={"mainnet_forbidden": False},
    )
