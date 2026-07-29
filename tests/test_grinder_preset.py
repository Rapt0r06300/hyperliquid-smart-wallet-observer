"""Preset GRINDER (brique 3): plusieurs entrées distillées simultanées.

Le mode grinder copy = suivre plusieurs clusters de leaders en même temps,
chaque position petite mais dimensionnée par la preuve (whale sizing) et
exécutée maker. Ce test vérifie le levier multi-entrées existant.
"""

from __future__ import annotations

from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote  # noqa: F401  # ordre d'import (cycle)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.fusion_paper_engine_adapter import (
    run_distilled_opportunities_through_paper_engine,
)
from hl_observer.signals.distilled_opportunity_detector import DistilledOpportunity


def _opportunity(coin: str) -> DistilledOpportunity:
    return DistilledOpportunity(
        coin=coin,
        side="LONG",
        wallet_count=3,
        wallets=("0xa", "0xb", "0xc"),
        total_notional_usdc=15_000.0,
        average_edge_bps=45.0,
        average_liquidity_score=0.8,
        max_signal_age_ms=2_000,
        power_score=75.0,
        source_profiles=("canonical",),
    )


PRICES = {"HYPE": 70.0, "SOL": 150.0, "AVAX": 30.0}


def _install_recorded_books(monkeypatch, prices: dict[str, float]) -> None:
    def inputs(coin: str, *, observed_at_ms: int):
        mid = float(prices[str(coin).upper()])
        truth = ExecutionTruth.from_levels(
            coin=coin,
            bids=((mid * 0.99995, 10_000.0),),
            asks=((mid * 1.00005, 10_000.0),),
            received_ts_ms=observed_at_ms,
            exchange_ts_ms=observed_at_ms,
            source="TEST_RECORDED_L2",
            data_origin="RECORDED_REAL",
        )
        return truth.spread_bps, 1.0, truth

    monkeypatch.setattr(
        "hl_observer.paper_trading.fusion_paper_engine_adapter._live_execution_inputs",
        inputs,
    )


def test_default_stays_single_entry(monkeypatch):
    monkeypatch.delenv("HYPERSMART_DISTILLED_MAX_PAPER_ENTRIES", raising=False)
    _install_recorded_books(monkeypatch, PRICES)
    summary = run_distilled_opportunities_through_paper_engine(
        tuple(_opportunity(c) for c in PRICES),
        market_prices=PRICES,
        observed_at_ms=1_000_000,
    )
    assert summary.accepted_count == 1  # défaut prudent inchangé


def test_grinder_env_enables_multiple_small_entries(monkeypatch):
    monkeypatch.setenv("HYPERSMART_DISTILLED_MAX_PAPER_ENTRIES", "3")
    monkeypatch.setenv("HYPERSMART_WHALE_CONSENSUS_SIZING", "1")
    # MAX_POSITION_USDT = MARGE par position (fix "centimes"), pas le notional.
    # Notional max = marge x levier = 40 x 10 = 400. Le sizing proportionnel doit rester SOUS ce max.
    monkeypatch.setenv("HYPERSMART_MAX_POSITION_USDT", "40")
    monkeypatch.setenv("HYPERSMART_SIMULATION_LEVERAGE", "10")
    _install_recorded_books(monkeypatch, PRICES)
    max_notional = 40.0 * 10.0
    summary = run_distilled_opportunities_through_paper_engine(
        tuple(_opportunity(c) for c in PRICES),
        market_prices=PRICES,
        observed_at_ms=1_000_000,
    )
    assert summary.accepted_count == 3
    for decision in summary.decisions:
        assert decision.trade.notional_usdt < max_notional   # sizing proportionnel réduit
        assert decision.trade.notional_usdt >= 10.0          # plancher HL $10 respecté


def test_grinder_entries_capped_at_five(monkeypatch):
    monkeypatch.setenv("HYPERSMART_DISTILLED_MAX_PAPER_ENTRIES", "99")
    prices = dict(PRICES, BTC=50_000.0, ETH=3_000.0, DOGE=0.2, LINK=15.0)
    _install_recorded_books(monkeypatch, prices)
    summary = run_distilled_opportunities_through_paper_engine(
        tuple(_opportunity(c) for c in prices),
        market_prices=prices,
        observed_at_ms=1_000_000,
    )
    assert summary.accepted_count <= 5  # garde-fou dur conservé
