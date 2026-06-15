from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import PaperIntent, ScoreBreakdown, WalletScoreStatus
from hyper_smart_observer.risk_engine.gates import evaluate_paper_intent


def _intent(**overrides):
    values = {
        "intent_id": "intent",
        "wallet_address": "0x" + "a" * 40,
        "coin": "ETH",
        "side": "BUY",
        "reference_price": 100.0,
        "requested_notional": 50.0,
        "created_at": datetime.now(UTC),
        "source": "test",
        "reason": "test",
    }
    values.update(overrides)
    return PaperIntent(**values)


def _score(**overrides):
    values = {
        "wallet_address": "0x" + "a" * 40,
        "calculated_at": datetime.now(UTC),
        "status": WalletScoreStatus.SCORED,
        "total_fills": 50,
        "usable_fills": 50,
        "skipped_fills": 0,
        "confidence_score": 90.0,
        "sample_quality_score": 90.0,
        "risk_score": 90.0,
        "profit_factor": 2.0,
        "net_pnl": 10.0,
    }
    values.update(overrides)
    return ScoreBreakdown(**values)


def test_hypersmart_paper_gate_accepts_simulation_only():
    decision = evaluate_paper_intent(_intent(), _score(), AppConfig(), {"open_trades": 0})

    assert decision.allowed
    assert decision.decision_scope == "PAPER_SIMULATION_ONLY"
    assert "Not an order" in decision.message


def test_hypersmart_paper_gate_refuses_disabled():
    decision = evaluate_paper_intent(
        _intent(),
        _score(),
        AppConfig(enable_paper_trading=False),
        {"open_trades": 0},
    )

    assert not decision.allowed
    assert decision.reason_code == "PAPER_TRADING_DISABLED"


def test_hypersmart_paper_gate_refuses_execution_flags():
    decision = evaluate_paper_intent(
        _intent(),
        _score(),
        AppConfig(execution_enabled=True),
        {"open_trades": 0},
    )

    assert not decision.allowed
    assert decision.reason_code == "EXECUTION_DISABLED"
