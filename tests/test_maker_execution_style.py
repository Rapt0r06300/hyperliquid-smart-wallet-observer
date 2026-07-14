"""Mode grinder brique 1: style d'exécution maker (recherche 2026-07-07).

Les mini-positions ne survivent que si le coût par trade est quasi nul:
maker ~1.5 bps / rebate vs taker 4.5 bps + spread + slippage. Le mode maker
reste OFF par défaut et inclut une pénalité d'adverse selection configurable.
"""

from __future__ import annotations

from hl_observer.paper_trading.exec_model import ExecModelConfig, simulate_execution


def _cost(side: str = "BUY", *, maker: bool) -> float:
    result = simulate_execution(
        side=side,
        notional_usdc=20.0,
        mid_price=100.0,
        top_depth_usdc=50_000.0,
        is_maker=maker,
        config=ExecModelConfig(),
    )
    return result.net_cost_bps


def test_maker_fill_is_much_cheaper_than_taker(monkeypatch):
    monkeypatch.delenv("HYPERSMART_MAKER_ADVERSE_SELECTION_BPS", raising=False)
    taker = _cost(maker=False)
    maker = _cost(maker=True)
    assert maker < taker
    assert taker >= 4.5  # taker fee + demi-spread au minimum
    # TARIF REEL HYPERLIQUID (corrige 2026-07-11) : le maker COUTE 0,015 % (1,5 bps).
    # Ce test affirmait `maker <= 0.0`, c'est-a-dire que le bot etait PAYE pour entrer. Faux :
    # le rebate n'existe qu'aux paliers de volume eleves. Un test qui encode un bug le protege.
    assert 0.0 < maker <= 2.0, "un fill maker est MOINS CHER qu'un taker, mais jamais gratuit"


def test_adverse_selection_penalty_applies_in_grinder_mode(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MAKER_ADVERSE_SELECTION_BPS", "2.0")
    maker = _cost(maker=True)
    # cout maker = frais reels (1,5) + selection adverse (2,0) -- et non plus un rebate de -1,0
    assert abs(maker - (1.5 + 2.0)) < 1e-9
    monkeypatch.setenv("HYPERSMART_MAKER_ADVERSE_SELECTION_BPS", "0")
    # sans penalite de selection adverse, le cout maker se reduit aux FRAIS reels (1,5 bps).
    # Il reste POSITIF : un fill passif n'est pas gratuit (tarif Hyperliquid 0,015 %).
    assert abs(_cost(maker=True) - 1.5) < 1e-9


def test_paper_engine_execution_style_env(monkeypatch):
    from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote  # noqa: F401  # ordre d'import (cycle)
    from hl_observer.paper_trading.paper_engine import _maker_execution_style_enabled

    monkeypatch.delenv("HYPERSMART_EXECUTION_STYLE", raising=False)
    assert _maker_execution_style_enabled() is False  # taker par défaut
    monkeypatch.setenv("HYPERSMART_EXECUTION_STYLE", "maker")
    assert _maker_execution_style_enabled() is True
    monkeypatch.setenv("HYPERSMART_EXECUTION_STYLE", "TAKER")
    assert _maker_execution_style_enabled() is False
