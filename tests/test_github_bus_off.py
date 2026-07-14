"""LE BUS GITHUB EST ETEINT — ET LA COMPTABILITE EST DEJA PROTEGEE (2026-07-12).

CE QUE LE RAPPORT CODEX AFFIRMAIT :
    « le bus GitHub ecrit des evenements PAPER_ORDER_ACCEPTED [...] Cela pollue l'UI et la notion
      de trade accepte. [...] Elles doivent etre retirees de la chaine comptable. »

CE QUE LE VRAI CODE FAIT, VERIFIE PAR EXECUTION :
    `_ledger_closed_trade_stats` exige DEUX conditions pour compter un trade :
      (a) une action contenant CLOSE / REDUCE / EXIT / TRAILING_STOP / STOP_LOSS / TAKE_PROFIT ;
      (b) un `estimated_net_pnl_usdc` NUMERIQUE.
    Un ENGINE_EVALUATION a `paper_action_type="ENGINE_EVALUATION"` et `estimated_net_pnl_usdc=None`.
    Il echoue aux DEUX. 171 evaluations + 1 vraie fermeture -> closed_trades = 1.

    => La pollution est COSMETIQUE (vocabulaire, ecran, hot path), PAS COMPTABLE.
       Le PnL n'a jamais ete fausse par le bus. Il fallait le verifier avant de le "corriger".

CE QUI ETAIT VRAI, EN REVANCHE :
    `external_profile_scope()` avait pour defaut **"priority"** -- le bus TOURNAIT, et n'etait
    nulle part dans le launcher. Personne ne l'avait rallume : il n'avait jamais ete eteint.
    ~810 evaluations de profils externes pour 21 entrees reelles, dans le hot path.

Aucun ordre reel.
"""
from __future__ import annotations

from hl_observer.strategies.external_simulation_bus import external_profile_scope
from hl_observer.ui.status_routes import _ledger_closed_trade_stats


def _engine_evaluation() -> dict:
    """Un evenement REEL du bus, copie tel quel de la session auditee."""
    return {
        "paper_action_type": "ENGINE_EVALUATION",
        "bot_replay_action": "EXTERNAL_GITHUB_PROFILE_EVALUATED",
        "decision": "PAPER_ORDER_ACCEPTED",
        "reason": "PROFILE_PRODUCED_ACCEPTED_LOCAL_PAPER_ORDER",
        "copied_notional_usdt": 0.0,
        "leader_side": "NONE",
        "estimated_net_pnl_usdc": None,
        "coin": "EXTERNAL",
    }


def _vraie_fermeture(pnl: float = -3.5) -> dict:
    return {
        "paper_action_type": "CLOSE",
        "bot_replay_action": "CLOSE",
        "estimated_net_pnl_usdc": pnl,
        "coin": "ETH",
        "leader_side": "SHORT",
        "delta_key": "k1",
        "observed_at_ms": 1,
    }


# ------------------------------------------------------------------ le bus est ETEINT

def test_the_github_bus_is_OFF_by_default(monkeypatch):
    """LE TEST QUI COMPTE. Le defaut du code etait "priority" : le bus tournait sans que personne
    ne l'ait allume. Un moteur ecarte doit etre eteint DANS LE CODE, pas seulement dans les tetes."""
    monkeypatch.delenv("HYPERSMART_EXTERNAL_PROFILES_SCOPE", raising=False)
    assert external_profile_scope() == "off"


def test_an_unknown_scope_falls_back_to_OFF(monkeypatch):
    """Une valeur invalide ne doit pas RALLUMER le bus par accident."""
    monkeypatch.setenv("HYPERSMART_EXTERNAL_PROFILES_SCOPE", "n_importe_quoi")
    assert external_profile_scope() == "off"


def test_the_bus_can_still_be_turned_on_EXPLICITLY(monkeypatch):
    """On ne supprime pas : on eteint. La recherche reste possible, mais elle se demande."""
    monkeypatch.setenv("HYPERSMART_EXTERNAL_PROFILES_SCOPE", "priority")
    assert external_profile_scope() == "priority"


# ------------------------------------------------------------------ la comptabilite tient

def test_an_ENGINE_EVALUATION_is_NEVER_counted_as_a_trade():
    """171 evaluations du bus + 1 vraie fermeture -> UN seul trade ferme. Prouve, pas suppose."""
    stats = _ledger_closed_trade_stats([_engine_evaluation()] * 171 + [_vraie_fermeture()])
    assert stats["closed_trades"] == 1
    assert stats["losing_trades"] == 1
    assert stats["winning_trades"] == 0


def test_a_thousand_evaluations_alone_produce_ZERO_trades():
    stats = _ledger_closed_trade_stats([_engine_evaluation()] * 1000)
    assert stats["closed_trades"] == 0
    assert stats["winrate_pct"] == 0.0


def test_an_event_without_numeric_pnl_is_never_a_trade():
    """Le 2e verrou : meme un evenement qui SE DIT CLOSE ne compte pas sans PnL numerique."""
    faux = _vraie_fermeture()
    faux["estimated_net_pnl_usdc"] = None
    assert _ledger_closed_trade_stats([faux])["closed_trades"] == 0


def test_a_PAPER_ORDER_ACCEPTED_label_does_not_make_it_a_trade():
    """Le vocabulaire ment ; le filtre, non. C'est l'ACTION et le PnL qui decident, pas le libelle."""
    menteur = _engine_evaluation()
    menteur["decision"] = "PAPER_ORDER_ACCEPTED"
    assert _ledger_closed_trade_stats([menteur])["closed_trades"] == 0


def test_real_closes_are_still_counted_normally():
    """On ne casse pas la comptabilite en durcissant : un vrai trade reste un vrai trade."""
    gagnant = _vraie_fermeture(pnl=+2.0)
    gagnant["delta_key"] = "k2"
    stats = _ledger_closed_trade_stats([_vraie_fermeture(-1.0), gagnant])
    assert stats["closed_trades"] == 2
    assert stats["winning_trades"] == 1
    assert stats["losing_trades"] == 1
