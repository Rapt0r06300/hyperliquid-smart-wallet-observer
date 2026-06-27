from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import (
    PaperIntent,
    ScoreBreakdown,
    Signal,
    SignalState,
    WalletScoreStatus,
    WalletStatus,
)
from hyper_smart_observer.risk_engine.gates import evaluate_paper_intent, evaluate_signal


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


def _score(
    *,
    status: WalletScoreStatus = WalletScoreStatus.SCORED,
    confidence: float = 90.0,
    sample_quality: float = 90.0,
) -> ScoreBreakdown:
    return ScoreBreakdown(
        wallet_address="0x" + "3" * 40,
        calculated_at=datetime.now(UTC),
        status=status,
        total_fills=100,
        usable_fills=100,
        skipped_fills=0,
        sample_quality_score=sample_quality,
        confidence_score=confidence,
        profit_factor=2.0,
        net_pnl=100.0,
        risk_score=80.0,
    )


def _intent(**overrides) -> PaperIntent:
    data = {
        "intent_id": "intent",
        "wallet_address": "0x" + "3" * 40,
        "coin": "BTC",
        "side": "BUY",
        "reference_price": 100.0,
        "requested_notional": 50.0,
        "created_at": datetime.now(UTC),
        "source": "unit_test",
        "reason": "paper only",
    }
    data.update(overrides)
    return PaperIntent(**data)


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


def test_hypersmart_signal_refused_if_mainnet_or_execution_enabled():
    mainnet = evaluate_signal(
        _signal(),
        {"sample_size": 100, "wallet_score": 99},
        AppConfig(allow_mainnet=True),
    )
    execution = evaluate_signal(
        _signal(),
        {"sample_size": 100, "wallet_score": 99},
        AppConfig(execution_enabled=True),
    )

    assert not mainnet.allowed
    assert mainnet.reason_code == "MAINNET_FORBIDDEN"
    assert not execution.allowed
    assert execution.reason_code == "EXECUTION_DISABLED"


def test_hypersmart_signal_refused_for_missing_or_low_score():
    missing = evaluate_signal(_signal(), {"sample_size": 100}, AppConfig())
    low = evaluate_signal(_signal(confidence=0.1), {"sample_size": 100, "wallet_score": 99}, AppConfig())

    assert not missing.allowed
    assert missing.reason_code == "SCORE_MISSING"
    assert not low.allowed
    assert low.reason_code == "CONFIDENCE_TOO_LOW"


def test_hypersmart_signal_refused_if_testnet_enabled_without_confirmation():
    decision = evaluate_signal(
        _signal(),
        {"sample_size": 100, "wallet_score": 99},
        AppConfig(testnet_execution_enabled=True, confirm_testnet_only=False),
    )

    assert not decision.allowed
    assert decision.reason_code == "TESTNET_CONFIRMATION_REQUIRED"


def test_hypersmart_signal_can_only_reach_paper_allowed_after_gates():
    decision = evaluate_signal(_signal(), {"sample_size": 100, "wallet_score": 90}, AppConfig())

    assert decision.allowed
    assert decision.reason_code == "PAPER_ALLOWED"


def test_risk_engine_deny_by_default_all_paper_intent_failure_modes():
    cases = [
        (AppConfig(enable_paper_trading=False), _score(), _intent(), {}, "PAPER_TRADING_DISABLED"),
        (AppConfig(mode="LIVE"), _score(), _intent(), {}, "MODE_FORBIDDEN"),
        (AppConfig(execution_enabled=True), _score(), _intent(), {}, "EXECUTION_DISABLED"),
        (AppConfig(), None, _intent(), {}, "PAPER_WALLET_SCORE_MISSING"),
        (AppConfig(), _score(status=WalletScoreStatus.INSUFFICIENT_DATA), _intent(), {}, "PAPER_WALLET_SCORE_NOT_SCORED"),
        (AppConfig(), _score(confidence=10.0), _intent(), {}, "PAPER_CONFIDENCE_TOO_LOW"),
        (AppConfig(), _score(sample_quality=10.0), _intent(), {}, "PAPER_SAMPLE_QUALITY_TOO_LOW"),
        (AppConfig(), _score(), _intent(side="HOLD"), {}, "PAPER_INVALID_SIDE"),
        (AppConfig(), _score(), _intent(reference_price=0.0), {}, "PAPER_INVALID_PRICE"),
        (AppConfig(), _score(), _intent(requested_notional=0.0), {}, "PAPER_INVALID_NOTIONAL"),
        (AppConfig(paper_max_position_notional=10.0), _score(), _intent(requested_notional=50.0), {}, "PAPER_NOTIONAL_TOO_HIGH"),
        (AppConfig(paper_max_open_trades=1), _score(), _intent(), {"open_trades": 1}, "PAPER_MAX_OPEN_TRADES_REACHED"),
    ]

    for config, score, intent, portfolio, reason in cases:
        decision = evaluate_paper_intent(intent, score, config, portfolio)
        assert not decision.allowed
        assert decision.reason_code == reason


def test_risk_engine_allows_paper_intent_only_after_all_gates():
    decision = evaluate_paper_intent(_intent(), _score(), AppConfig(), {"open_trades": 0})

    assert decision.allowed
    assert decision.reason_code == "PAPER_SIMULATION_ONLY"
    assert decision.decision_scope == "PAPER_SIMULATION_ONLY"
