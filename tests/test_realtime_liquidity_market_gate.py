"""Regression tests for the market-based realtime liquidity score.

Root cause (session 2026-07-03, PF=0.34): the copy gate scored liquidity from
the *leader fill notional* (``max(0.2, min(1.0, notional/2500))``), refusing
BTC 1472 times as LIQUIDITY_TOO_LOW while letting large fills on thin coins
through. These tests lock the fix: market tier first, notional only raises.

Paper/simulation only — nothing here can create an order.
"""

from __future__ import annotations

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.markets.realtime_liquidity import (
    DEEP_TIER_SCORE,
    MID_TIER_SCORE,
    notional_proxy_score,
    resolve_realtime_liquidity_score,
    static_tier_score,
)


def _score(coin: str, leader_notional: float, cluster_notional: float | None = None, consensus: int = 1) -> float:
    return resolve_realtime_liquidity_score(
        coin=coin,
        leader_notional_usdc=leader_notional,
        cluster_notional_usdc=cluster_notional if cluster_notional is not None else leader_notional,
        consensus_wallets=consensus,
    )


class TestStaticTiers:
    def test_btc_small_fill_is_deep(self) -> None:
        # The exact live failure: 45 USDT whale clip on BTC scored 0.2 < 0.22.
        assert _score("BTC", 45.0) == DEEP_TIER_SCORE

    def test_majors_are_deep(self) -> None:
        for coin in ("BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE"):
            assert _score(coin, 10.0) >= DEEP_TIER_SCORE

    def test_mid_tier_coin(self) -> None:
        assert _score("PUMP", 10.0) == MID_TIER_SCORE

    def test_lowercase_and_spaces_normalised(self) -> None:
        assert static_tier_score(" btc ") == DEEP_TIER_SCORE

    def test_exotic_prefixes_have_no_tier(self) -> None:
        assert static_tier_score("XYZ:SNDK") is None
        assert static_tier_score("@107") is None
        assert static_tier_score("") is None


class TestNotionalProxy:
    def test_unknown_coin_small_fill_scores_low_no_floor(self) -> None:
        # The old 0.2 floor parked every small fill just under the 0.22 gate.
        score = _score("UNKNOWNCOIN", 45.0)
        assert score == notional_proxy_score(45.0)
        assert score < 0.22

    def test_unknown_coin_large_cluster_passes_via_proxy(self) -> None:
        score = _score("UNKNOWNCOIN", 100.0, cluster_notional=2_500.0, consensus=3)
        assert score == 1.0

    def test_consensus_uses_cluster_notional(self) -> None:
        single = _score("UNKNOWNCOIN", 100.0, cluster_notional=2_000.0, consensus=1)
        clustered = _score("UNKNOWNCOIN", 100.0, cluster_notional=2_000.0, consensus=3)
        assert clustered > single

    def test_notional_only_raises_tiered_market(self) -> None:
        # A big burst on ETH may raise the score to 1.0 but a tiny fill can
        # never sink it below the tier.
        assert _score("ETH", 5.0) == DEEP_TIER_SCORE
        assert _score("ETH", 2_500.0) == 1.0


class TestMeasuredScoreDominates:
    def test_measured_score_wins_over_tier(self) -> None:
        score = resolve_realtime_liquidity_score(
            coin="BTC",
            leader_notional_usdc=45.0,
            cluster_notional_usdc=45.0,
            consensus_wallets=1,
            measured_market_score=0.5,
        )
        assert score == 0.5

    def test_invalid_measured_falls_back(self) -> None:
        score = resolve_realtime_liquidity_score(
            coin="BTC",
            leader_notional_usdc=45.0,
            cluster_notional_usdc=45.0,
            consensus_wallets=1,
            measured_market_score=0.0,
        )
        assert score == DEEP_TIER_SCORE


class TestGateIntegration:
    def test_btc_single_wallet_is_not_refused_for_liquidity(self) -> None:
        """Replays the live refusal: BTC ADD, 1 wallet, fresh, decent edge."""
        liquidity = _score("BTC", 45.0)
        score = score_realtime_copy_candidate(
            RealtimeCopyScoreInput(
                action_type="ADD",
                direction="LONG",
                leader_expected_edge_bps=40.0,
                leader_consistency_factor=1.0,
                signal_age_ms=500,
                consensus_wallets=1,
                liquidity_score=liquidity,
                leader_score=80.0,
                leader_reference_price=100_000.0,
                current_mid=100_000.0,
                leader_notional_usdt=45.0,
                current_open_exposure_usdt=0.0,
                current_open_positions=0,
                max_open_positions=10,
            ),
            config=RealtimeCopyRiskConfig(),
        )
        assert "LIQUIDITY_TOO_LOW" not in score.refusal_reasons

    def test_unknown_thin_coin_small_fill_still_refused(self) -> None:
        """The gate must keep refusing genuinely unevidenced liquidity."""
        liquidity = _score("UNKNOWNCOIN", 45.0)
        score = score_realtime_copy_candidate(
            RealtimeCopyScoreInput(
                action_type="ADD",
                direction="LONG",
                leader_expected_edge_bps=40.0,
                leader_consistency_factor=1.0,
                signal_age_ms=500,
                consensus_wallets=1,
                liquidity_score=liquidity,
                leader_score=80.0,
                leader_reference_price=1.0,
                current_mid=1.0,
                leader_notional_usdt=45.0,
                current_open_exposure_usdt=0.0,
                current_open_positions=0,
                max_open_positions=10,
            ),
            config=RealtimeCopyRiskConfig(),
        )
        assert "LIQUIDITY_TOO_LOW" in score.refusal_reasons


class TestSafetyInvariants:
    def test_scores_are_bounded(self) -> None:
        for coin in ("BTC", "PUMP", "UNKNOWNCOIN", "@107", "XYZ:SNDK"):
            for notional in (0.0, 45.0, 10_000.0, -5.0):
                value = _score(coin, notional)
                assert 0.0 <= value <= 1.0

    def test_module_is_pure_no_network_no_orders(self) -> None:
        import hl_observer.markets.realtime_liquidity as module

        source = open(module.__file__, encoding="utf-8").read().lower()
        for forbidden in ("requests.", "httpx", "websocket", "aiohttp", "/exchange", "private_key", "signature"):
            assert forbidden not in source
