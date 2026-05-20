from hl_observer.hyperliquid.schemas import RiskDecision, SignalCandidate, SignalDecision
from hl_observer.paper.paper_executor import PaperExecutor


def test_paper_executor_refuses_if_risk_refuses():
    signal = SignalCandidate(
        id="s1",
        source_wallet="0xabc",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=100,
        timestamp_ms=1,
        signal_age_ms=100,
    )
    risk = RiskDecision(
        allowed=False,
        decision=SignalDecision.REJECT_EDGE_NEGATIVE,
        reasons=["edge remaining is negative"],
        gates={"edge": False},
    )

    order = PaperExecutor().submit(signal, risk, notional_usdc=10)

    assert order.notional_usdc == 0
    assert order.rejected_reason


def test_paper_executor_uses_pessimistic_fill():
    signal = SignalCandidate(
        id="s2",
        source_wallet="0xabc",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=100,
        timestamp_ms=1,
        signal_age_ms=100,
        estimated_spread_bps=2,
        estimated_slippage_bps=3,
    )
    risk = RiskDecision(
        allowed=True,
        decision=SignalDecision.PAPER_TRADE,
        reasons=[],
        gates={"all": True},
    )

    order = PaperExecutor().submit(signal, risk, notional_usdc=10)

    assert order.simulated_fill_price > order.requested_price
