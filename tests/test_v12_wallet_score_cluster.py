from __future__ import annotations

from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.scoring.wallet_score_v2 import (
    WalletPerformanceSample,
    WalletScoreV2Config,
    score_wallet_v2,
)
from hl_observer.signals.cluster_detector import ClusterConfig, detect_signal_clusters
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.signals.no_trade_taxonomy import resolve


def _samples(wallet: str, *, one_big: bool = False) -> list[WalletPerformanceSample]:
    base = 1_700_000_000_000
    pnls = [80, 70, 65, 55, -20, 75, 68, -18, 60, 62, 58, 64, 72, -25]
    if one_big:
        pnls = [900, 8, 6, 4, -10, 5, 4, 3, 2, 1, -5, 3, 2, 1]
    coins = ["BTC", "ETH", "HYPE", "SOL"]
    return [
        WalletPerformanceSample(
            wallet=wallet,
            coin=coins[i % len(coins)],
            closed_pnl_usdc=float(p),
            timestamp_ms=base + i * 86_400_000,
            notional_usdc=2_000.0,
            fee_usdc=0.7,
        )
        for i, p in enumerate(pnls)
    ]


def test_wallet_score_v2_shortlists_sufficient_diffuse_history():
    wallet = "0x" + "a" * 40
    score = score_wallet_v2(wallet, _samples(wallet), now_ms=1_700_000_000_000 + 14 * 86_400_000)
    assert score.status == "SHORTLISTED"
    assert score.accepted_for_shortlist is True
    assert score.copyability_score >= 50
    assert score.sample_confidence > 0
    assert score.score_hash.startswith("wsv2:")


def test_wallet_score_v2_rejects_one_big_win_concentration():
    wallet = "0x" + "b" * 40
    score = score_wallet_v2(wallet, _samples(wallet, one_big=True), now_ms=1_700_000_000_000 + 14 * 86_400_000)
    assert score.status == "REJECTED"
    assert "PNL_CONCENTRATION_TOO_HIGH" in score.reasons
    assert "ONE_BIG_WIN_RISK" in score.reasons
    assert score.one_big_win_risk is True


def test_wallet_score_v2_insufficient_data_is_explicit():
    wallet = "0x" + "c" * 40
    score = score_wallet_v2(
        wallet,
        [WalletPerformanceSample(wallet=wallet, coin="BTC", closed_pnl_usdc=10, timestamp_ms=1)],
        config=WalletScoreV2Config(min_closed_pnl_points=3),
    )
    assert score.status == "INSUFFICIENT_DATA"
    assert "INSUFFICIENT_CLOSED_PNL" in score.reasons


def _delta(wallet: str, coin: str, size: float, ts: int) -> LeaderDelta:
    return LeaderDelta(
        delta_id=f"ld:{wallet[-4:]}:{coin}:{ts}",
        wallet=wallet,
        coin=coin,
        action=LifecycleAction.OPEN_LONG if size > 0 else LifecycleAction.OPEN_SHORT,
        previous_size=0.0,
        current_size=size,
        delta_size=size,
        observed_at_ms=ts + 500,
        leader_event_time_ms=ts,
        source="test",
        confidence=0.9,
        evidence_ref=f"raw:{wallet[-4:]}",
    )


def test_cluster_detector_accepts_fresh_multi_wallet_same_coin_side():
    deltas = [
        _delta("0x" + "1" * 40, "HYPE", 2.0, 10_000),
        _delta("0x" + "2" * 40, "HYPE", 1.5, 12_000),
        _delta("0x" + "3" * 40, "BTC", 1.0, 12_500),
    ]
    clusters = detect_signal_clusters(deltas, observed_at_ms=13_000, config=ClusterConfig(window_ms=4_000))
    assert clusters[0].coin == "HYPE"
    assert clusters[0].side == "LONG"
    assert clusters[0].accepted is True
    assert len(clusters[0].unique_wallets) == 2
    assert clusters[0].consensus_strength > 0


def test_cluster_detector_rejects_single_wallet_or_stale_cluster():
    one = detect_signal_clusters([_delta("0x" + "4" * 40, "HYPE", 2.0, 10_000)], observed_at_ms=11_000)
    assert one and one[0].accepted is False
    assert "CLUSTER_TOO_FEW_WALLETS" in one[0].reason_codes

    stale = detect_signal_clusters(
        [_delta("0x" + "5" * 40, "HYPE", 2.0, 10_000), _delta("0x" + "6" * 40, "HYPE", 1.0, 11_000)],
        observed_at_ms=30_000,
        config=ClusterConfig(max_age_ms=6_000),
    )
    assert stale[0].accepted is False
    assert "CLUSTER_STALE" in stale[0].reason_codes


def test_cluster_reason_codes_are_registered_no_trade_taxonomy():
    assert resolve("CLUSTER_TOO_FEW_WALLETS").value == "CLUSTER_TOO_FEW_WALLETS"
    assert resolve("CLUSTER_STALE").value == "CLUSTER_STALE"
    assert resolve("CLUSTER_CONFIDENCE_TOO_LOW").value == "CLUSTER_CONFIDENCE_TOO_LOW"
