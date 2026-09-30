from __future__ import annotations

from hyper_smart_observer.consensus.wallet_cluster_detector import detect_wallet_clusters


def test_wallet_cluster_detector_finds_aligned_wallets_in_four_second_window() -> None:
    events = [
        {"wallet": "w1", "coin": "BTC", "action_type": "OPEN_LONG", "timestamp_ms": 1_000, "wallet_score": 90, "copyability_score": 80, "simulation_score": 1, "notional": 50},
        {"wallet": "w2", "coin": "BTC", "action_type": "OPEN_LONG", "timestamp_ms": 4_000, "wallet_score": 85, "copyability_score": 75, "simulation_score": 2, "notional": 40},
        {"wallet": "w3", "coin": "BTC", "action_type": "OPEN_LONG", "timestamp_ms": 9_500, "wallet_score": 95, "copyability_score": 90, "simulation_score": 3, "notional": 60},
    ]

    clusters = detect_wallet_clusters(events, window_ms=4_000)

    assert len(clusters) == 1
    assert clusters[0].wallet_count == 2
    assert clusters[0].high_quality_wallet_count == 2
    assert clusters[0].total_notional == 90
    assert clusters[0].consensus_strength > 0


def test_wallet_cluster_detector_warns_on_low_quality_cluster() -> None:
    clusters = detect_wallet_clusters(
        [
            {"wallet": "w1", "coin": "SOL", "action_type": "OPEN_SHORT", "timestamp_ms": 1, "wallet_score": 10},
            {"wallet": "w2", "coin": "SOL", "action_type": "OPEN_SHORT", "timestamp_ms": 2, "wallet_score": 20},
        ]
    )

    assert "NO_HIGH_QUALITY_WALLET" in clusters[0].risk_flags
    assert "WEAK_CLUSTER" in clusters[0].risk_flags
