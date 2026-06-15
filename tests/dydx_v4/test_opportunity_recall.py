from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.opportunity_recall import evaluate_opportunity_recall


def _tuned(edge=8.0, quality=70.0, tremor=7.0, age=10000, wallets=3, phase="BEFORE_MOVE"):
    return SimpleNamespace(
        tremor=SimpleNamespace(
            edge_remaining_bps=edge,
            intensity_score=tremor,
            signal_age_ms=age,
            leading_wallets=wallets,
            consensus_wallets=wallets,
            timeline_phase=phase,
        ),
        quality=SimpleNamespace(score=quality),
    )


def test_recall_accepts_promising_watch_candidate() -> None:
    decision = evaluate_opportunity_recall(
        _tuned(),
        {"opportunity_score": 72.0, "risk_score": 30.0},
        [],
        base_notional_usdc=12.0,
        max_notional_usdc=100.0,
    )

    assert decision.should_recall is True
    assert decision.notional_usdc > 0
    assert "RECALL_PROMISING_MISSED_OPPORTUNITY" in decision.reasons


def test_recall_rejects_low_edge() -> None:
    decision = evaluate_opportunity_recall(
        _tuned(edge=1.0),
        {"opportunity_score": 80.0, "risk_score": 20.0},
        [],
    )

    assert decision.should_recall is False
    assert "RECALL_EDGE_TOO_LOW" in decision.reasons


def test_recall_rejects_hard_reason() -> None:
    decision = evaluate_opportunity_recall(
        _tuned(),
        {"opportunity_score": 80.0, "risk_score": 20.0},
        ["DIRECTOR_NO_EDGE"],
    )

    assert decision.should_recall is False
    assert "RECALL_HARD_REASON_PRESENT" in decision.reasons
