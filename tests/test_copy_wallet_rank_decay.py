from hl_observer.copy_wallet.wallet_rank_decay import apply_wallet_rank_decay


def test_rank_decay_keeps_fresh_top_wallet_high_and_decays_stale_rank() -> None:
    fresh_top = apply_wallet_rank_decay(base_score=1.0, rank=1, age_ms=0)
    stale_deep = apply_wallet_rank_decay(base_score=1.0, rank=200, age_ms=24 * 60 * 60 * 1000)

    assert fresh_top.decayed_score == 1.0
    assert stale_deep.decayed_score < 0.05
    assert stale_deep.decay_factor < fresh_top.decay_factor
