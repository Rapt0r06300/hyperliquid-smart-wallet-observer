from hl_observer.config.loader import load_settings
from hl_observer.risk.adaptive_filter import AdaptiveRiskLevel, apply_adaptive_risk_filter
from hl_observer.risk.risk_context import AdaptiveRiskContext


def test_adaptive_risk_filter_blocks_bad_liquidity():
    settings = load_settings()
    decision = apply_adaptive_risk_filter(
        AdaptiveRiskContext(depth_usdc=1, wallet_score=90, wallet_coin_score=90, opening_pattern_score=90, pattern_sample_size=30),
        settings,
    )

    assert decision.risk_level == AdaptiveRiskLevel.BLOCK
    assert "liquidity_too_low" in decision.reasons


def test_adaptive_risk_filter_reduces_size_on_altcoin():
    settings = load_settings()
    decision = apply_adaptive_risk_filter(
        AdaptiveRiskContext(
            coin="MEME",
            depth_usdc=settings.adaptive_risk_filter.min_orderbook_depth_usdc,
            wallet_score=90,
            wallet_coin_score=90,
            opening_pattern_score=90,
            pattern_sample_size=settings.adaptive_risk_filter.min_pattern_sample_size,
        ),
        settings,
    )

    assert decision.allowed
    assert decision.paper_size_usdc <= settings.adaptive_risk_filter.paper_tiny_size_usdc
