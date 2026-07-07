from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
from hl_observer.paper_trading.fusion_paper_engine_adapter import (
    run_copy_votes_through_paper_engine,
    run_distilled_opportunities_through_paper_engine,
)
from hl_observer.signals.distilled_opportunity_detector import DistilledOpportunity


def test_fusion_paper_engine_adapter_uses_existing_paper_engine():
    result = run_copy_votes_through_paper_engine(
        (
            LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=2.0),
            LeaderVote(wallet="0x2", coin="HYPE", side="LONG", score=1.0),
        ),
        market_price=100.0,
        observed_at_ms=1000,
    )
    assert result.accepted_count == 1
    assert result.decisions[0].accepted is True
    assert result.decisions[0].trade is not None
    assert result.paper_only is True
    assert result.real_execution is False


def test_distilled_opportunities_use_existing_paper_engine_with_real_mark():
    result = run_distilled_opportunities_through_paper_engine(
        (
            DistilledOpportunity(
                coin="HYPE",
                side="LONG",
                wallet_count=3,
                wallets=("0x1", "0x2", "0x3"),
                total_notional_usdc=25_000.0,
                average_edge_bps=45.0,
                average_liquidity_score=0.92,
                max_signal_age_ms=1_500,
                power_score=91.0,
                source_profiles=("whale_wallet_mirror",),
            ),
        ),
        market_prices={"HYPE": 100.0},
        observed_at_ms=10_000,
    )

    assert result.accepted_count == 1
    assert result.decisions[0].accepted is True
    assert result.decisions[0].trade is not None
    assert result.decisions[0].position is not None
    assert result.decisions[0].ledger_snapshot is not None
    assert result.paper_only is True
    assert result.real_execution is False


def test_distilled_opportunities_refuse_when_real_mark_is_missing():
    result = run_distilled_opportunities_through_paper_engine(
        (
            DistilledOpportunity(
                coin="HYPE",
                side="LONG",
                wallet_count=3,
                wallets=("0x1", "0x2", "0x3"),
                total_notional_usdc=25_000.0,
                average_edge_bps=45.0,
                average_liquidity_score=0.92,
                max_signal_age_ms=1_500,
                power_score=91.0,
                source_profiles=("whale_wallet_mirror",),
            ),
        ),
        market_prices={},
        observed_at_ms=10_000,
    )

    assert result.accepted_count == 0
    assert result.decisions[0].accepted is False
    assert "MARKET_PRICE_INVALID" in result.decisions[0].reason_codes
    assert result.paper_only is True
    assert result.real_execution is False
