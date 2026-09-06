from __future__ import annotations

from hl_observer.strategies.lead_lag_paper import SignalLeadLag, rejouer_lead_lag


CFG = {
    "notional": 100.0,
    "fee_bps": 2.5,
    "demi_spread_bps": 2.5,
    "slippage_bps": 1.0,
    "min_fill_ratio": 0.5,
    "costs_measured": True,
}


def test_replay_counts_missed_fill_inside_segments() -> None:
    signals = [
        SignalLeadLag(
            ts_ms=1_000 * i,
            coin="BTC",
            signe_leader=1,
            mid_entree=100.0,
            delta_mid_futur=0.5,
            edge_bps_prevu=60.0,
            liquidite=0.1 if i == 0 else 1.0,
        )
        for i in range(30)
    ]

    result = rejouer_lead_lag(signals, config=CFG, min_episodes=5)
    segments = result["segments"]

    assert sum(segment["missed"] for segment in segments.values()) == 1
    assert sum(segment["fills"] for segment in segments.values()) == 29
