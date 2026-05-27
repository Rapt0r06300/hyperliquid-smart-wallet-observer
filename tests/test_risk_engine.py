from hl_observer.config.loader import load_settings
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine


def test_risk_engine_rejects_late_signal(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    settings = load_settings()
    decision = RiskEngine(settings).evaluate(
        RiskContext(
            spread_bps=1,
            slippage_bps=1,
            orderbook_depth_usdc=10000,
            wallet_score=90,
            signal_score=90,
            edge_remaining_bps=20,
            signal_age_ms=999999,
        )
    )

    assert not decision.allowed
    assert "signal is too old" in decision.reasons


def test_risk_engine_rejects_too_small_edge(monkeypatch):
    monkeypatch.setenv("HL_ENV", "paper")
    settings = load_settings()
    decision = RiskEngine(settings).evaluate(
        RiskContext(
            spread_bps=1,
            slippage_bps=1,
            orderbook_depth_usdc=10000,
            wallet_score=90,
            signal_score=90,
            edge_remaining_bps=2,
            signal_age_ms=100,
        )
    )

    assert not decision.allowed
    assert "edge remaining below minimum" in decision.reasons
