from __future__ import annotations

from hyper_smart_observer.dydx_v4.signal_quality import (
    QualityProfile,
    SignalQualityInput,
    evaluate_signal_quality,
    quality_score,
    reset_leader_stats,
    update_leader_stats,
)


def _input(wallet: str = "dydx1leader") -> SignalQualityInput:
    return SignalQualityInput(
        market_id="ETH-USD",
        side="LONG",
        leader_wallet=wallet,
        tremor_score=8.0,
        tremor_phase="BEFORE_MOVE",
        signal_age_ms=500,
        wallet_count=2,
        flow_imbalance=0.85,
        flow_volume_usdc=80_000.0,
        edge_remaining_bps=18.0,
        market_regime="TRENDING",
        data_source="stream",
        spread_bps=2.0,
        slippage_bps=2.0,
    )


def test_leader_market_low_winrate_halves_quality_score() -> None:
    reset_leader_stats()
    base = quality_score(_input())
    update_leader_stats("dydx1leader", "ETH-USD", won=False)
    update_leader_stats("dydx1leader", "ETH-USD", won=False)
    penalized = quality_score(_input())
    assert penalized == round(base * 0.5, 4)


def test_leader_market_good_winrate_keeps_score() -> None:
    reset_leader_stats()
    base = quality_score(_input())
    update_leader_stats("dydx1leader", "ETH-USD", won=True)
    update_leader_stats("dydx1leader", "ETH-USD", won=False)
    update_leader_stats("dydx1leader", "ETH-USD", won=True)
    assert quality_score(_input()) == base


def test_evaluate_signal_quality_notes_low_leader_market_winrate() -> None:
    reset_leader_stats()
    update_leader_stats("dydx1leader", "ETH-USD", won=False)
    decision = evaluate_signal_quality(_input(), QualityProfile(min_score=40.0, watch_score=20.0))
    assert "LEADER_MARKET_WINRATE_LOW" in decision.reasons or "LEADER_MARKET_WINRATE_LOW" in decision.notes
    assert any(note.startswith("leader_market_winrate=0.00") for note in decision.notes)
