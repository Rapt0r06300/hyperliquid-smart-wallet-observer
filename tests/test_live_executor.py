import pytest

from hl_observer.execution.live_executor_disabled import (
    LiveExecutionDisabled,
    LiveExecutorDisabled,
    refuse_live_execution,
)
from hl_observer.hyperliquid.schemas import SignalDecision


def test_live_executor_always_refuses():
    with pytest.raises(LiveExecutionDisabled):
        LiveExecutorDisabled().place_order()


def test_live_executor_decision_is_mainnet_forbidden():
    decision = refuse_live_execution()

    assert not decision.allowed
    assert decision.decision == SignalDecision.REJECT_MAINNET_FORBIDDEN
