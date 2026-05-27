from datetime import UTC, datetime

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import Signal, SignalState, WalletStatus
from hyper_smart_observer.risk_engine.gates import evaluate_signal


def _signal(confidence: float = 0.9) -> Signal:
    return Signal(
        signal_id="sig",
        wallet_address="0x" + "3" * 40,
        coin="BTC",
        side="buy",
        confidence=confidence,
        created_at=datetime.now(UTC),
        state=SignalState.CANDIDATE,
        reason="test",
    )


def test_hypersmart_risk_deny_by_default():
    decision = evaluate_signal(None, {}, AppConfig())

    assert not decision.allowed
    assert decision.reason_code == "DENY_BY_DEFAULT"


def test_hypersmart_signal_refused_if_data_insufficient():
    decision = evaluate_signal(_signal(), {"sample_size": 1, "wallet_score": 99}, AppConfig())

    assert not decision.allowed
    assert decision.reason_code == "INSUFFICIENT_DATA"


def test_hypersmart_signal_refused_if_wallet_blocked():
    decision = evaluate_signal(
        _signal(),
        {"wallet_status": WalletStatus.BLOCKED.value, "sample_size": 100, "wallet_score": 99},
        AppConfig(),
    )

    assert not decision.allowed
    assert decision.reason_code == "WALLET_BLOCKED"


def test_hypersmart_signal_refused_if_mode_forbidden():
    decision = evaluate_signal(_signal(), {"sample_size": 100, "wallet_score": 99}, AppConfig(mode="LIVE"))

    assert not decision.allowed
    assert decision.reason_code == "MODE_FORBIDDEN"


def test_hypersmart_signal_can_only_reach_paper_allowed_after_gates():
    decision = evaluate_signal(_signal(), {"sample_size": 100, "wallet_score": 90}, AppConfig())

    assert decision.allowed
    assert decision.reason_code == "PAPER_ALLOWED"
