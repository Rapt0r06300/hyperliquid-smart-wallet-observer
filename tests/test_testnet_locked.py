import pytest

from hl_observer.config.loader import load_settings
from hl_observer.hyperliquid.schemas import RiskDecision, SignalDecision
from hl_observer.testnet.testnet_order_builder import build_testnet_order_intent
from hl_observer.testnet.testnet_executor_locked import LockedTestnetExecutor
from hl_observer.testnet.testnet_safety_gates import TestnetLocked


def _allowed_risk() -> RiskDecision:
    return RiskDecision(
        allowed=True,
        decision=SignalDecision.TESTNET_CANDIDATE,
        reasons=[],
        gates={"risk": True},
    )


def test_testnet_execution_disabled_by_default(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    monkeypatch.delenv("HL_ENABLE_TESTNET_EXECUTION", raising=False)
    settings = load_settings()
    order = build_testnet_order_intent(
        cloid="abc",
        coin="BTC",
        side="buy",
        size=0.001,
        limit_price=1,
        schedule_cancel_configured=True,
    )

    with pytest.raises(TestnetLocked):
        LockedTestnetExecutor(settings).submit(
            order,
            _allowed_risk(),
            confirm_testnet_only=True,
        )


def test_testnet_order_requires_cloid():
    with pytest.raises(ValueError):
        build_testnet_order_intent(
            cloid=None,
            coin="BTC",
            side="buy",
            size=0.001,
            limit_price=1,
        )


def test_testnet_order_requires_schedule_cancel(monkeypatch):
    monkeypatch.setenv("HL_ENV", "testnet")
    monkeypatch.setenv("HL_ENABLE_TESTNET_EXECUTION", "true")
    settings = load_settings()
    order = build_testnet_order_intent(
        cloid="abc",
        coin="BTC",
        side="buy",
        size=0.001,
        limit_price=1,
        schedule_cancel_configured=False,
    )

    with pytest.raises(TestnetLocked):
        LockedTestnetExecutor(settings).submit(
            order,
            _allowed_risk(),
            confirm_testnet_only=True,
        )
