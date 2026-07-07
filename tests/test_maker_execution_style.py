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
    assert maker <= 0.0  # rebate par défaut (comportement historique)


def test_adverse_selection_penalty_applies_in_grinder_mode(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MAKER_ADVERSE_SELECTION_BPS", "2.0")
    maker = _cost(maker=True)
    assert abs(maker - (-1.0 + 2.0)) < 1e-9  # rebate -1.0 + adverse 2.0
    monkeypatch.setenv("HYPERSMART_MAKER_ADVERSE_SELECTION_BPS", "0")
    assert _cost(maker=True) <= 0.0


def test_paper_engine_execution_style_env(monkeypatch):
    from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote  # noqa: F401  # ordre d'import (cycle)
    from hl_observer.paper_trading.paper_engine import _maker_execution_style_enabled

    monkeypatch.delenv("HYPERSMART_EXECUTION_STYLE", raising=False)
    assert _maker_execution_style_enabled() is False  # taker par défaut
    monkeypatch.setenv("HYPERSMART_EXECUTION_STYLE", "maker")
    assert _maker_execution_style_enabled() is True
    monkeypatch.setenv("HYPERSMART_EXECUTION_STYLE", "TAKER")
    assert _maker_execution_style_enabled() is False
