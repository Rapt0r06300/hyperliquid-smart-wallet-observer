"""UN MOTEUR QUI SAIGNE NE DOIT PAS TUER L'AUTRE (2026-07-11) — pistes 81-90.

Le garde-fou de session existant raisonne sur UN SEUL PnL. Deux absurdités en découlent :

  * le Sniper perd 40 $ → la session passe en protection → **le Grinder est puni aussi**, alors
    que son mécanisme (funding delta-neutre) n'a rien à voir avec la cause de la perte ;
  * un Grinder qui gagne **masquerait** un Sniper qui saigne : la session paraît « à peine
    négative », le garde-fou se déclenche mollement, et le vrai coupable continue de tirer.

Chaque moteur doit répondre de SES pertes. Ces tests le verrouillent, y compris sur le VRAI gate
d'ouverture (`_portfolio_open_refusal`) — un garde-fou non câblé ne protège personne.

Simulation paper uniquement. Aucun ordre réel.
"""
from __future__ import annotations

import pytest

from hl_observer.risk.engine_risk_budget import (
    engine_budget_refusal,
    evaluer_budgets,
    rapport_budgets,
)
from hl_observer.strategies.strategy_mode import GRINDER, SNIPER, UNKNOWN_LEGACY
from hl_observer.ui.fusion_persistent_adapter import _portfolio_open_refusal

CAPITAL = 1000.0        # soft = 4 % = 40 $ ; hard = 15 % = 150 $


def _close(mode: str, net: float) -> dict:
    return {"paper_action_type": "CLOSE", "strategy_mode": mode,
            "coin": "BTC", "leader_side": "LONG",
            "estimated_net_pnl_usdc": net, "gross_pnl_usdc": net, "fee_cost_usdc": 0.0}


# ------------------------------------------------------------- l'isolation des moteurs

def test_a_bleeding_sniper_does_not_gag_the_grinder():
    """LE CŒUR. Le Sniper a perdu 60 $ ; le Grinder n'a rien fait de mal. Il doit pouvoir ouvrir."""
    ledger = [_close(SNIPER, -60.0)]
    assert engine_budget_refusal(ledger, moteur=SNIPER, equity_usdt=CAPITAL) != ""
    assert engine_budget_refusal(ledger, moteur=GRINDER, equity_usdt=CAPITAL) == "", (
        "le Grinder est puni pour les pertes du Sniper"
    )


def test_a_winning_grinder_cannot_be_used_as_an_alibi_by_the_sniper():
    """L'AUTRE SENS, plus vicieux : Grinder +50, Sniper −60. La session est à −10 : « tout va bien ».
    Faux. Le Sniper doit être coupé sur SES pertes, pas sur la moyenne."""
    ledger = [_close(GRINDER, +50.0), _close(SNIPER, -60.0)]
    assert engine_budget_refusal(ledger, moteur=SNIPER, equity_usdt=CAPITAL) != "", (
        "le gain du Grinder a servi d'alibi au Sniper : c'est ainsi qu'on laisse un moteur saigner"
    )
    assert engine_budget_refusal(ledger, moteur=GRINDER, equity_usdt=CAPITAL) == ""


def test_the_two_thresholds_are_distinct():
    soft = [_close(SNIPER, -45.0)]            # > 40 $ mais < 150 $
    hard = [_close(SNIPER, -160.0)]           # > 150 $
    assert engine_budget_refusal(soft, moteur=SNIPER, equity_usdt=CAPITAL) == \
        "SNIPER_SOFT_LOSS_BUDGET_EXCEEDED"
    assert engine_budget_refusal(hard, moteur=SNIPER, equity_usdt=CAPITAL) == \
        "SNIPER_HARD_LOSS_BUDGET_EXCEEDED"


def test_a_small_loss_does_not_freeze_anything():
    """On ne coupe pas un moteur pour −5 $ : ce serait un cliquet, le bug déjà corrigé une fois."""
    assert engine_budget_refusal([_close(SNIPER, -5.0)], moteur=SNIPER, equity_usdt=CAPITAL) == ""


def test_an_engine_that_never_traded_is_never_cut():
    """On ne punit pas le néant : un moteur sans trade ne peut pas avoir perdu."""
    b = evaluer_budgets([_close(SNIPER, -200.0)], equity_usdt=CAPITAL)
    assert b[GRINDER].trades == 0 and b[GRINDER].refus == ""


# ------------------------------------------------------------- deny-by-default

def test_an_invalid_threshold_falls_back_to_the_default_not_to_infinity(monkeypatch):
    """Un plafond invalide ne veut PAS dire « illimité ». Un garde-fou ne se desserre jamais seul."""
    ledger = [_close(SNIPER, -200.0)]
    for mauvais in ("0", "-3", "", "abc", "nan"):
        monkeypatch.setenv("HYPERSMART_ENGINE_HARD_LOSS_PCT", mauvais)
        monkeypatch.setenv("HYPERSMART_ENGINE_SOFT_LOSS_PCT", mauvais)
        assert engine_budget_refusal(ledger, moteur=SNIPER, equity_usdt=CAPITAL) != "", (
            f"un plafond invalide ({mauvais!r}) a désactivé le garde-fou : FAIL-OPEN"
        )


def test_an_incoherent_config_cannot_make_hard_softer_than_soft(monkeypatch):
    monkeypatch.setenv("HYPERSMART_ENGINE_SOFT_LOSS_PCT", "10")
    monkeypatch.setenv("HYPERSMART_ENGINE_HARD_LOSS_PCT", "2")     # incohérent
    b = evaluer_budgets([], equity_usdt=CAPITAL)
    assert b[SNIPER].seuil_hard_usdc >= b[SNIPER].seuil_soft_usdc


def test_an_unreadable_capital_does_not_disable_the_guard():
    assert engine_budget_refusal([_close(SNIPER, -200.0)], moteur=SNIPER, equity_usdt=0.0) != ""


def test_an_unidentified_engine_is_not_cut():
    """On ne coupe pas ce qu'on n'a pas su identifier : on ne saurait pas ce qu'on coupe."""
    ledger = [_close(UNKNOWN_LEGACY, -500.0)]
    assert engine_budget_refusal(ledger, moteur=UNKNOWN_LEGACY, equity_usdt=CAPITAL) == ""
    assert engine_budget_refusal(ledger, moteur="", equity_usdt=CAPITAL) == ""


# ------------------------------------------------------------- le garde-fou est CÂBLÉ

class _State:
    def __init__(self, events: list[dict]) -> None:
        self.simulation_ledger_events = events
        self.simulation_virtual_positions: dict = {}
        self.simulation_starting_equity_usdt = CAPITAL


def test_the_real_open_gate_refuses_the_bleeding_engine_only():
    """LE CÂBLAGE. Un garde-fou testé mais jamais appelé ne protège personne."""
    state = _State([_close(SNIPER, -200.0)])
    refus_sniper = _portfolio_open_refusal(
        state, new_notional_usdt=500.0, coin="BTC", side="LONG", strategy_mode=SNIPER,
    )
    refus_grinder = _portfolio_open_refusal(
        state, new_notional_usdt=500.0, coin="BTC", side="LONG", strategy_mode=GRINDER,
    )
    assert refus_sniper == "SNIPER_HARD_LOSS_BUDGET_EXCEEDED"
    assert refus_grinder == "", "le Grinder a été bloqué par les pertes du Sniper, en LIVE"


def test_the_open_gate_still_lets_a_healthy_engine_through():
    state = _State([_close(SNIPER, -2.0)])
    assert _portfolio_open_refusal(
        state, new_notional_usdt=500.0, coin="BTC", side="LONG", strategy_mode=SNIPER,
    ) == ""


def test_the_report_names_the_cut_engines():
    rep = rapport_budgets([_close(SNIPER, -200.0)], equity_usdt=CAPITAL)
    assert rep["moteurs_coupes"] == [SNIPER]
    assert rep["budgets"][SNIPER]["coupe"] is True
    assert rep["budgets"][GRINDER]["coupe"] is False
    assert rep["real_execution"] is False


def test_garbage_never_crashes_the_budget():
    for bad in (None, [], [None], [{}]):
        rep = rapport_budgets(bad, equity_usdt=CAPITAL)  # type: ignore[arg-type]
        assert rep["moteurs_coupes"] == []
