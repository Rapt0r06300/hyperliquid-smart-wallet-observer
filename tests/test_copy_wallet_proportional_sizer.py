from hl_observer.copy_wallet.proportional_sizer import ProportionalSizingConfig, size_proportional_to_leader
from hl_observer.copy_wallet.wallet_tier import REJECTED_TIER, tier_for_wallet_score


def test_proportional_sizer_caps_to_follower_equity_and_tier() -> None:
    tier = tier_for_wallet_score(0.95, 0.95)
    decision = size_proportional_to_leader(
        leader_notional_usdt=500_000,
        tier=tier,
        config=ProportionalSizingConfig(
            follower_equity_usdt=1000,
            leader_equity_usdt=100_000,
            base_copy_ratio=0.05,
            max_margin_usdt=200,
            max_equity_fraction=0.10,
        ),
    )

    assert decision.accepted is True
    assert decision.margin_usdt == tier.max_margin_usdt
    assert decision.reason == "OK"


def test_proportional_sizer_rejects_untrusted_tier() -> None:
    decision = size_proportional_to_leader(leader_notional_usdt=100_000, tier=REJECTED_TIER)

    assert decision.accepted is False
    assert decision.reason == "WALLET_TIER_REJECTED"
