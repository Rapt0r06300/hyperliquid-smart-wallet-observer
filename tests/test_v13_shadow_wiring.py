from hl_observer.signals.shadow_wiring import classify_vol_regime, compute_shadow_signals


def test_regime_classifier_levels():
    assert classify_vol_regime(adverse_move_bps=5) == "low"
    assert classify_vol_regime(adverse_move_bps=20) == "normal"
    assert classify_vol_regime(adverse_move_bps=40) == "high"
    assert classify_vol_regime(adverse_move_bps=80) == "panic"


def test_shadow_is_context_only_and_complete():
    s = compute_shadow_signals(
        action_type="OPEN_LONG", coin="BTC", side="LONG", age_ms=4000,
        consensus_wallets=3, leader_score=72.0, leader_notional_usdc=60000.0,
        net_edge_bps=22.0, liquidity_score=0.5, directional_bias_bps=4.0,
        adverse_move_bps=10.0, price_deviation_bps=8.0, confidence=0.8,
    )
    assert s["shadow_context_only"] is True and s["shadow_changes_decision"] is False
    # fresh + large + quality leader => primary whale signal
    assert s["shadow_whale_primary"] is True and s["shadow_whale_strength"] > 0
    assert s["shadow_regime"] in {"low", "normal"} and s["shadow_regime_allows"] is True
    assert s["shadow_power_score"] > 0           # passes floors
    assert 0.0 <= s["shadow_size_pct"] <= 5.0


def test_shadow_drops_and_halts_correctly():
    # stale + thin + low edge => ranker floor => power 0; panic vol => regime blocks
    s = compute_shadow_signals(
        action_type="OPEN_LONG", coin="X", side="LONG", age_ms=99_000,
        consensus_wallets=1, leader_score=10.0, leader_notional_usdc=100.0,
        net_edge_bps=1.0, liquidity_score=0.05, adverse_move_bps=90.0,
    )
    assert s["shadow_power_score"] == 0.0
    assert s["shadow_whale_primary"] is None       # not an entry-grade whale fill
    assert s["shadow_regime"] == "panic" and s["shadow_regime_allows"] is False


def test_streak_sizing_reduces_after_losses():
    base = compute_shadow_signals(action_type="OPEN_LONG", coin="BTC", side="LONG", age_ms=1000,
                                  consensus_wallets=2, leader_score=70, leader_notional_usdc=5000,
                                  net_edge_bps=20, liquidity_score=0.5, confidence=1.0)
    lossy = compute_shadow_signals(action_type="OPEN_LONG", coin="BTC", side="LONG", age_ms=1000,
                                   consensus_wallets=2, leader_score=70, leader_notional_usdc=5000,
                                   net_edge_bps=20, liquidity_score=0.5, confidence=1.0,
                                   consecutive_losses=3)
    assert lossy["shadow_size_pct"] < base["shadow_size_pct"]


def test_bias_model_wired_when_closes_present():
    up_fast = [100, 101, 102, 103, 104, 105]
    up_slow = [90, 94, 98, 100, 103, 106]
    s = compute_shadow_signals(
        action_type="OPEN_LONG", coin="BTC", side="LONG", age_ms=2000, consensus_wallets=2,
        leader_score=70, leader_notional_usdc=5000, net_edge_bps=20, liquidity_score=0.5,
        closes_fast_tf=up_fast, closes_slow_tf=up_slow,
    )
    assert s["shadow_bias_bps"] is not None and s["shadow_bias_combined"] is not None
    # no closes -> degraded (None), engine never breaks
    s2 = compute_shadow_signals(
        action_type="OPEN_LONG", coin="BTC", side="LONG", age_ms=2000, consensus_wallets=2,
        leader_score=70, leader_notional_usdc=5000, net_edge_bps=20, liquidity_score=0.5,
    )
    assert s2["shadow_bias_bps"] is None
