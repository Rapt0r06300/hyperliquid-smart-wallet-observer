"""Portage idée n°1 (whale-wallet-mirror): sizing proportionnel au consensus.

Le multiplicateur ne peut QUE réduire la taille (jamais >1.0), reste borné au
plancher, et le câblage runtime est flag-gated (OFF par défaut tant que le
replay A/B dédié n'a pas prouvé un meilleur profit factor net).
"""

from __future__ import annotations

# NOTE ordre d'import: le paquet copy_wallet doit être amorcé avant
# paper_trading.fusion_paper_engine_adapter (cycle préexistant copy_wallet ->
# copy_mode -> strategies -> fusion_runtime -> fusion_paper_engine_adapter).
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote  # noqa: F401

from hl_observer.paper_trading.fusion_paper_engine_adapter import (
    run_distilled_opportunities_through_paper_engine,
)
from hl_observer.copying.whale_consensus_sizing import (
    FLOOR_MULTIPLIER,
    compute_whale_consensus_sizing,
)
from hl_observer.signals.distilled_opportunity_detector import DistilledOpportunity


def test_strong_fresh_whale_consensus_gets_full_size():
    sizing = compute_whale_consensus_sizing(
        wallet_count=4, max_signal_age_ms=1_500, total_notional_usdc=30_000.0
    )
    assert sizing.multiplier == 1.0
    assert sizing.tier == "FULL_SIZE"
    assert "CONSENSUS_STRONG_4PLUS_WALLETS" in sizing.reasons


def test_minimal_consensus_is_reduced_not_blocked():
    sizing = compute_whale_consensus_sizing(
        wallet_count=2, max_signal_age_ms=3_500, total_notional_usdc=6_000.0
    )
    assert FLOOR_MULTIPLIER <= sizing.multiplier < 0.65
    assert sizing.tier == "MINIMUM_SIZE"


def test_multiplier_never_exceeds_one_and_never_below_floor():
    high = compute_whale_consensus_sizing(
        wallet_count=99, max_signal_age_ms=0, total_notional_usdc=10_000_000.0
    )
    low = compute_whale_consensus_sizing(
        wallet_count=1, max_signal_age_ms=999_999, total_notional_usdc=0.0
    )
    assert high.multiplier <= 1.0
    assert low.multiplier >= FLOOR_MULTIPLIER
    assert low.reasons  # raisons explicites, pas de silence


def _opportunity(wallet_count: int = 2, age_ms: int = 2_500, notional: float = 6_000.0) -> DistilledOpportunity:
    return DistilledOpportunity(
        coin="HYPE",
        side="LONG",
        wallet_count=wallet_count,
        wallets=tuple(f"0x{i}" for i in range(wallet_count)),
        total_notional_usdc=notional,
        average_edge_bps=42.0,
        average_liquidity_score=0.8,
        max_signal_age_ms=age_ms,
        power_score=70.0,
        source_profiles=("canonical",),
    )


def test_adapter_scales_margin_when_flag_enabled(monkeypatch):
    # SEMANTIQUE CORRIGEE (audit 2026-07-11) : depuis le fix des "centimes",
    # MAX_POSITION_USDT = la MARGE, et le notional = marge x levier. On fixe le levier a 1
    # pour que ce test mesure ce qu'il pretend mesurer : le MULTIPLICATEUR de consensus.
    monkeypatch.setenv("HYPERSMART_WHALE_CONSENSUS_SIZING", "1")
    monkeypatch.setenv("HYPERSMART_MAX_POSITION_USDT", "40")
    monkeypatch.setenv("HYPERSMART_SIMULATION_LEVERAGE", "1")
    summary = run_distilled_opportunities_through_paper_engine(
        (_opportunity(),),
        market_prices={"HYPE": 70.0},
        observed_at_ms=1_000_000,
    )
    assert summary.accepted_count == 1
    trade = summary.decisions[0].trade
    expected = compute_whale_consensus_sizing(
        wallet_count=2, max_signal_age_ms=2_500, total_notional_usdc=6_000.0
    )
    assert abs(float(trade.notional_usdt) - 40.0 * expected.multiplier) < 0.5
    assert expected.multiplier < 1.0  # preuve: la taille est bien reduite vs cap


def test_adapter_keeps_full_size_when_flag_disabled(monkeypatch):
    monkeypatch.delenv("HYPERSMART_WHALE_CONSENSUS_SIZING", raising=False)
    monkeypatch.setenv("HYPERSMART_MAX_POSITION_USDT", "40")
    monkeypatch.setenv("HYPERSMART_SIMULATION_LEVERAGE", "1")   # marge x levier = notional
    summary = run_distilled_opportunities_through_paper_engine(
        (_opportunity(),),
        market_prices={"HYPE": 70.0},
        observed_at_ms=1_000_000,
    )
    assert summary.accepted_count == 1
    assert abs(float(summary.decisions[0].trade.notional_usdt) - 40.0) < 0.5
