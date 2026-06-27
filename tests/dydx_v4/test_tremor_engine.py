from __future__ import annotations

from hyper_smart_observer.dydx_v4.tremor_engine import (
    TremorConfig,
    TremorDecision,
    TremorObservation,
    TremorReason,
    evaluate_tremor,
    observation_from_cluster,
    observation_from_flow,
    timeline_phase,
    tremor_intensity,
)


def test_tremor_intensity_scores_strong_confluence() -> None:
    obs = TremorObservation(
        market_id="ETH-USD",
        direction="LONG",
        price_move_bps=42.0,
        volume_zscore=3.0,
        flow_imbalance=0.72,
        flow_volume_usdc=25_000.0,
        flow_trade_count=12,
        leading_wallets=2,
        consensus_wallets=3,
        signal_age_ms=1200,
        edge_remaining_bps=11.0,
        market_regime="TRENDING",
        market_confidence=0.8,
    )
    assert tremor_intensity(obs) >= 6.5


def test_timeline_before_during_after() -> None:
    cfg = TremorConfig(already_moved_bps=100.0)
    assert timeline_phase(TremorObservation("BTC-USD", "LONG", price_move_bps=20.0, leading_wallets=2, consensus_wallets=2), cfg) == "BEFORE_MOVE"
    assert timeline_phase(TremorObservation("BTC-USD", "LONG", price_move_bps=55.0, flow_imbalance=0.70), cfg) == "DURING_MOVE"
    assert timeline_phase(TremorObservation("BTC-USD", "LONG", price_move_bps=120.0), cfg) == "AFTER_MOVE"


def test_wallet_confluence_can_be_paper_candidate() -> None:
    obs = observation_from_cluster(
        market_id="SOL-USD",
        direction="SHORT",
        wallet_count=3,
        signal_age_ms=800,
        total_notional_usdc=35_000.0,
        price_move_bps=38.0,
        volume_zscore=2.8,
        flow_imbalance=0.70,
        flow_trade_count=9,
        edge_remaining_bps=14.0,
        market_regime="TRENDING",
        market_confidence=0.7,
    )
    event = evaluate_tremor(obs)
    assert event.decision == TremorDecision.PAPER_CANDIDATE
    assert event.read_only is True
    assert event.paper_only is True


def test_late_signal_is_no_trade() -> None:
    obs = TremorObservation(
        market_id="ETH-USD",
        direction="LONG",
        price_move_bps=40.0,
        volume_zscore=5.0,
        flow_imbalance=0.85,
        flow_volume_usdc=80_000.0,
        flow_trade_count=30,
        leading_wallets=4,
        consensus_wallets=4,
        signal_age_ms=45_000,
        edge_remaining_bps=30.0,
        market_regime="TRENDING",
        market_confidence=0.9,
    )
    event = evaluate_tremor(obs)
    assert event.decision == TremorDecision.NO_TRADE
    assert TremorReason.SIGNAL_TOO_LATE.value in event.reasons


def test_flow_only_is_watch_not_candidate() -> None:
    obs = observation_from_flow(
        market_id="DOGE-USD",
        direction="LONG",
        flow_imbalance=0.78,
        flow_volume_usdc=60_000.0,
        flow_trade_count=20,
        price_move_bps=25.0,
        volume_zscore=3.0,
        signal_age_ms=300,
        market_regime="TRENDING",
        market_confidence=0.6,
    )
    event = evaluate_tremor(obs)
    assert event.decision == TremorDecision.WATCH
    assert not event.is_actionable_paper_candidate



def test_large_trade_public_flow_boosts_tremor_and_is_logged() -> None:
    base = observation_from_flow(
        market_id="ETH-USD",
        direction="LONG",
        flow_imbalance=0.62,
        flow_volume_usdc=70_000.0,
        flow_trade_count=10,
        price_move_bps=18.0,
        volume_zscore=1.2,
        signal_age_ms=250,
        market_regime="TRENDING",
        market_confidence=0.7,
    )
    boosted = observation_from_flow(
        market_id="ETH-USD",
        direction="LONG",
        flow_imbalance=0.62,
        flow_volume_usdc=70_000.0,
        flow_trade_count=10,
        large_trade_usdc=65_000.0,
        price_move_bps=18.0,
        volume_zscore=1.2,
        signal_age_ms=250,
        market_regime="TRENDING",
        market_confidence=0.7,
    )

    assert tremor_intensity(boosted) > tremor_intensity(base)
    event = evaluate_tremor(boosted)
    assert TremorReason.LARGE_TRADE_BOOST.value in event.reasons
    assert event.to_log_dict()["large_trade_usdc"] == 65_000.0
    assert "large_trade=65000USDC" in event.explanation
