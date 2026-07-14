"""DEUX MOTEURS, DEUX PnL (2026-07-11) — pistes 12 à 20.

Additionner le PnL du Grinder et celui du Sniper, c'est mélanger deux maladies et n'en soigner
aucune : le Grinder meurt des FRAIS, le Sniper meurt de la FRAÎCHEUR. Pire, un moteur qui gagne
peut masquer un moteur qui saigne.

Ces tests verrouillent trois choses que je ne veux plus jamais voir se casser :
  1. le PnL de chaque moteur est comptabilisé SÉPARÉMENT ;
  2. un moteur à zéro trade est signalé comme INACTIF, pas absent du rapport en silence
     (c'est exactement ainsi que le Grinder est resté éteint sans que personne le voie) ;
  3. le coût d'entrée n'est PAS recompté ici (il est déjà dans le prix d'entrée).

Aucun ordre réel.
"""
from __future__ import annotations

import pytest

from hl_observer.strategies.engine_pnl import (
    attribuer_pnl_par_moteur,
    rapport_par_moteur,
)
from hl_observer.strategies.strategy_mode import GRINDER, SNIPER, UNKNOWN_LEGACY


def _close(mode: str | None, net: float, *, brut: float | None = None,
           frais: float = 0.0, action: str = "CLOSE") -> dict:
    e: dict = {
        "paper_action_type": action,
        "estimated_net_pnl_usdc": net,
        "gross_pnl_usdc": net if brut is None else brut,
        "fee_cost_usdc": frais,
    }
    if mode is not None:
        e["strategy_mode"] = mode
    return e


# ------------------------------------------------------------------ la séparation elle-même

def test_the_two_engines_never_share_a_pnl():
    """LE CŒUR : un Grinder qui gagne ne doit pas masquer un Sniper qui saigne."""
    events = [
        _close(GRINDER, +5.0),
        _close(GRINDER, +3.0),
        _close(SNIPER, -20.0),
    ]
    b = attribuer_pnl_par_moteur(events)
    assert b[GRINDER].pnl_net_usdc == pytest.approx(8.0)
    assert b[SNIPER].pnl_net_usdc == pytest.approx(-20.0)
    assert b[GRINDER].trades == 2 and b[SNIPER].trades == 1
    # le total (-12) ne dit RIEN d'utile : c'est tout le probleme qu'on corrige
    assert rapport_par_moteur(events)["pnl_net_total_usdc"] == pytest.approx(-12.0)


def test_an_idle_engine_is_reported_as_idle_not_omitted():
    """UN MOTEUR À ZÉRO TRADE N'EST PAS UN MOTEUR SANS PROBLÈME : il est éteint, ou verrouillé.

    C'est très exactement le silence dans lequel le Grinder est resté éteint.
    """
    rep = rapport_par_moteur([_close(SNIPER, -1.0)])
    assert GRINDER in rep["moteurs"], "le moteur inactif a DISPARU du rapport"
    assert rep["moteurs"][GRINDER]["trades"] == 0
    assert rep["moteurs"][GRINDER]["pnl_net_usdc"] == 0.0
    assert GRINDER in rep["moteurs_inactifs"], "un moteur qui ne trade pas doit être SIGNALÉ"


def test_an_empty_ledger_still_names_the_three_engines():
    rep = rapport_par_moteur([])
    assert set(rep["moteurs"]) == {GRINDER, SNIPER, UNKNOWN_LEGACY}
    assert rep["trades_total"] == 0
    assert sorted(rep["moteurs_inactifs"]) == sorted([GRINDER, SNIPER])


# ------------------------------------------------------------------ le Grinder est VISIBLE

def test_the_funding_arb_events_count_as_grinder():
    """Le funding-arb écrit FUNDING_ARB_*, pas OPEN/CLOSE. Un rapport aveugle à ces actions
    est aveugle au Grinder — l'erreur a déjà été commise une fois."""
    events = [
        _close(GRINDER, +0.40, action="FUNDING_ARB_ACCRUAL"),
        _close(GRINDER, -0.10, action="FUNDING_ARB_CLOSE", frais=0.10),
    ]
    b = attribuer_pnl_par_moteur(events)
    assert b[GRINDER].trades == 2
    assert b[GRINDER].pnl_net_usdc == pytest.approx(0.30)


def test_an_entry_realises_no_pnl():
    """Une ENTRÉE ne réalise aucun PnL. La compter fabriquerait un chiffre."""
    entree = {"paper_action_type": "OPEN", "strategy_mode": SNIPER,
              "estimated_net_pnl_usdc": -0.05, "fee_cost_usdc": 0.05}
    b = attribuer_pnl_par_moteur([entree])
    assert b[SNIPER].trades == 0
    assert b[SNIPER].pnl_net_usdc == 0.0


# ------------------------------------------------------------------ les métriques ne mentent pas

def test_the_profit_factor_is_the_judge_not_the_winrate():
    """9 petits gains + 1 grosse perte : winrate 90 %, profit factor 0,45. Le PF a raison."""
    events = [_close(SNIPER, +1.0) for _ in range(9)] + [_close(SNIPER, -20.0)]
    b = attribuer_pnl_par_moteur(events)[SNIPER]
    assert b.winrate == pytest.approx(0.9)
    assert b.profit_factor == pytest.approx(9.0 / 20.0)
    assert b.pnl_net_usdc == pytest.approx(-11.0)


def test_metrics_are_none_when_unmeasurable_not_zero():
    """VÉRITÉ : « pas mesurable » ≠ « zéro ». Un PF infini sur 1 trade serait un mensonge."""
    vide = attribuer_pnl_par_moteur([])[GRINDER]
    assert vide.winrate is None and vide.profit_factor is None

    que_des_gains = attribuer_pnl_par_moteur([_close(GRINDER, +1.0)])[GRINDER]
    assert que_des_gains.profit_factor is None, "un PF « infini » n'est pas une mesure"


def test_the_fee_ratio_exposes_the_grinder_disease():
    """Frais 6,50 $ pour un brut de 1,81 $ : les frais valent 3,6× le mouvement.
    Aucun réglage de signal ne sauve ça — et c'est CE chiffre qui doit sauter aux yeux."""
    b = attribuer_pnl_par_moteur(
        [_close(GRINDER, net=-7.81, brut=-1.81, frais=6.50)]
    )[GRINDER]
    assert b.frais_en_part_du_brut == pytest.approx(6.50 / 1.81, rel=1e-3)
    assert b.frais_en_part_du_brut > 1.0, "les frais dévorent plus que tout le mouvement"


def test_the_equity_curve_is_per_engine():
    events = [_close(GRINDER, +2.0), _close(SNIPER, -5.0), _close(GRINDER, +1.0)]
    b = attribuer_pnl_par_moteur(events)
    assert b[GRINDER].courbe_equity == [2.0, 3.0]
    assert b[SNIPER].courbe_equity == [-5.0]


# ------------------------------------------------------------------ honnêteté et robustesse

def test_an_unclassifiable_close_goes_to_unknown_not_to_a_guess():
    b = attribuer_pnl_par_moteur([_close(None, -3.0)])
    assert b[UNKNOWN_LEGACY].pnl_net_usdc == pytest.approx(-3.0)
    assert b[GRINDER].trades == 0 and b[SNIPER].trades == 0


def test_garbage_never_crashes_the_report():
    for bad in (None, [], [None], ["x"], [{}], [{"paper_action_type": "CLOSE"}]):
        rep = rapport_par_moteur(bad)  # type: ignore[arg-type]
        assert set(rep["moteurs"]) == {GRINDER, SNIPER, UNKNOWN_LEGACY}
        assert rep["real_execution"] is False
