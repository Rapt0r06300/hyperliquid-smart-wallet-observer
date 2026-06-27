from __future__ import annotations

from hyper_smart_observer.consensus.position_consensus import build_position_consensus
from hyper_smart_observer.opportunities.opportunity_engine import evaluate_opportunity


def strong_snapshot():
    return build_position_consensus(
        [
            {"wallet": "w1", "coin": "BTC", "direction": "LONG", "action_type": "OPEN_LONG", "wallet_score": 90, "notional": 50},
            {"wallet": "w2", "coin": "BTC", "direction": "LONG", "action_type": "OPEN_LONG", "wallet_score": 85, "notional": 50},
        ],
        timestamp_ms=1_800_000_000_000,
    )[0]


def test_opportunity_accepts_simulation_only_when_edge_remains() -> None:
    opportunity = evaluate_opportunity(strong_snapshot(), created_at_ms=1, current_mid=50_000, expected_edge_bps=40)

    assert opportunity.decision == "ACCEPT_FOR_SIMULATION_ONLY"
    assert opportunity.simulation_allowed is True
    assert opportunity.edge_remaining_bps == 26.0
    assert "pas un ordre" in opportunity.research_only_message


def test_opportunity_rejects_missing_edge_stale_low_liquidity_and_no_mid() -> None:
    opportunity = evaluate_opportunity(
        strong_snapshot(),
        created_at_ms=1,
        current_mid=None,
        expected_edge_bps=None,
        signal_age_seconds=999,
        liquidity_score=0.1,
    )

    assert opportunity.decision == "REJECT_NO_TRADE"
    assert "EDGE_UNMEASURABLE" in opportunity.refusal_reasons
    assert "STALE_SIGNAL" in opportunity.refusal_reasons
    assert "LIQUIDITY_TOO_LOW" in opportunity.refusal_reasons
    assert "NO_CURRENT_MID" in opportunity.refusal_reasons


def test_opportunity_rejects_low_remaining_edge() -> None:
    opportunity = evaluate_opportunity(strong_snapshot(), created_at_ms=1, current_mid=50_000, expected_edge_bps=5)

    assert opportunity.decision == "REJECT_NO_TRADE"
    assert "EDGE_REMAINING_TOO_LOW" in opportunity.refusal_reasons
