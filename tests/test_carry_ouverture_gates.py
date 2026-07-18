"""La PORTE DE RISQUE du carry : elle refuse pour de vrai, elle s'abstient quand on l'affame,
et surtout elle est APPELÉE par le chemin qui ouvre les positions (preuve par AST, pas par foi).

Contexte (18/07) : j'avais posé 7 gardes sur `v12_decision_pipeline`, que l'audit de câblage a
mesuré MORT. Ces tests existent pour que ça ne se reproduise pas en silence.
"""
from __future__ import annotations

import ast
from pathlib import Path

from hl_observer.funding.carry_ouverture_gates import (
    MOTIF_BUDGET_FUNDING, MOTIF_CVAR, MOTIF_DIVERGENCE, MOTIF_RESERVE, MOTIF_TAMPON,
    porte_risque_ouverture)

RACINE = Path(__file__).resolve().parents[1]
LIFECYCLE = RACINE / "src" / "hl_observer" / "funding" / "carry_position_lifecycle.py"


# ---------------------------------------------------------------- la porte REFUSE pour de vrai

def test_reserve_de_marge_entamee_refuse():
    """Capital 100 $, réserve 20 % : 75 $ déjà utilisés + 50 $ demandés dépassent les 80 $
    déployables -> refus. (Sinon la « réserve » ne serait qu'un commentaire.)"""
    r = porte_risque_ouverture(marge_demandee_usd=50.0, marge_utilisee_usd=75.0, capital_usd=100.0)
    assert r["autorise"] is False
    assert r["motif"] == MOTIF_RESERVE


def test_sources_divergentes_declenchent_le_kill_switch():
    """Deux sources qui annoncent 100 et 130 pour le même actif : la donnée est douteuse.
    On ne devine pas laquelle a raison — on ne trade pas."""
    r = porte_risque_ouverture(marge_demandee_usd=50.0, marks_multi_sources=[100.0, 130.0])
    assert r["autorise"] is False
    assert r["motif"] == MOTIF_DIVERGENCE


def test_tampon_de_liquidation_epuise_refuse():
    r = porte_risque_ouverture(marge_demandee_usd=50.0, distance_tampon_frac=0.0)
    assert r["autorise"] is False
    assert r["motif"] == MOTIF_TAMPON


def test_budget_de_funding_depasse_refuse():
    r = porte_risque_ouverture(marge_demandee_usd=50.0,
                               funding_paye_cumule_bps=120.0, budget_funding_bps=100.0)
    assert r["autorise"] is False
    assert r["motif"] == MOTIF_BUDGET_FUNDING


def test_queue_de_perte_trop_lourde_refuse():
    """CVaR des pertes réalisées récentes au-delà de 25 % du capital -> on n'empile pas."""
    r = porte_risque_ouverture(marge_demandee_usd=50.0, marge_utilisee_usd=0.0, capital_usd=100.0,
                               pnls_realises_recents=[-40.0, -50.0, -60.0, -55.0, -45.0, 1.0])
    assert r["autorise"] is False
    assert r["motif"] == MOTIF_CVAR


# ---------------------------------------------------------------- la porte NE S'AFFAME PAS

def test_sans_aucune_entree_la_porte_autorise_et_le_dit():
    """LA RÈGLE ANTI-GARDE-AFFAMÉ : aucune donnée = aucune raison de refuser. Le garde
    s'abstient EXPLICITEMENT (traçable), il n'invente pas un refus."""
    r = porte_risque_ouverture(marge_demandee_usd=50.0)
    assert r["autorise"] is True
    assert r["facteur_taille"] == 1.0
    assert all("ABSTENTION" in g for g in r["gardes"]), r["gardes"]


def test_le_facteur_de_taille_ne_peut_que_reduire():
    """Un garde de risque n'augmente JAMAIS la taille. Tampon moyen + drawdown -> facteur < 1."""
    r = porte_risque_ouverture(marge_demandee_usd=50.0, distance_tampon_frac=0.3, drawdown_frac=0.2)
    assert r["autorise"] is True
    assert 0.0 < r["facteur_taille"] < 1.0


def test_donnee_absente_ne_vaut_pas_zero():
    """`None` n'est pas `0.0`. Un tampon INCONNU ne doit pas être lu comme un tampon ÉPUISÉ,
    sinon le garde refuserait tout — exactement le bug « garde affamé »."""
    r = porte_risque_ouverture(marge_demandee_usd=50.0, distance_tampon_frac=None)
    assert r["autorise"] is True


# ---------------------------------------------------------------- la porte est VRAIMENT APPELÉE

def test_le_cycle_de_vie_du_carry_APPELLE_la_porte():
    """L'invariant qui aurait attrapé mon erreur X1-X4 : on vérifie un APPEL dans l'AST, pas
    une mention dans un commentaire. Importer une porte sans l'appeler ne protège de rien."""
    arbre = ast.parse(LIFECYCLE.read_text(encoding="utf-8", errors="ignore"))
    appels = {n.func.id for n in ast.walk(arbre)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "porte_risque_ouverture" in appels, (
        "carry_position_lifecycle n'APPELLE pas porte_risque_ouverture : les gardes de risk/ "
        "seraient de nouveau en limbe, sur un chemin mort. C'est la maladie du projet.")


def test_un_refus_de_la_porte_empeche_l_ouverture():
    """Preuve de bout en bout : porte fermée -> aucune position ouverte, et le motif est tracé."""
    from hl_observer.funding.carry_position_lifecycle import GestionnaireCarry

    g = GestionnaireCarry()
    decision = {"coin": "HYPE", "viable": True, "funding_bps_h": 1.0, "base_bps": 0.0,
                "levier": 2.0, "cout_entree_bps": 11.0}
    inputs = {"coin": "HYPE", "perp_px": 10.0, "levier_max": 2.0}
    evt = g.tick(decision, inputs, now_ms=1_000_000,
                 risque_contexte={"marks_multi_sources": [100.0, 130.0]})   # sources divergentes
    assert evt["ouvert"] is False
    assert evt.get("refus_risque") == MOTIF_DIVERGENCE
    assert not g.ouvertes
