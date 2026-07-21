"""L'ÉCONOMIE D'UNE POSITION, JAMBE PAR JAMBE (P1-1) — la neutralité MESURÉE, pas supposée.

L'audit du carry répondait `DATA_MISSING` à 5 des 15 questions, parce que la position ne
stockait qu'un notionnel et un coût agrégé. Et « delta-neutre » était une affirmation **par
construction** (le constructeur refuse le déséquilibre), jamais une mesure.

Ce que ces tests verrouillent :
  * ce qui n'est pas mesurable reste `None` — jamais un 0 fabriqué ;
  * la décomposition redonne EXACTEMENT le coût du moteur (pas de 2ᵉ standard) ;
  * le hedge ratio distingue MESURÉ et MODÉLISÉ, et ne ment pas sur son statut.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_economie_position import (HEDGE_MESURE, HEDGE_MODELISE,
                                                         coherence_avec_le_moteur,
                                                         decomposer_entree, enrichir,
                                                         hedge_ratio, quantites_par_jambe)
from hl_observer.funding.delta_neutral_carry import (COUT_MAKER_2_JAMBES_BPS, MAKER_BPS,
                                                     MAKER_SPOT_BPS)


def test_les_frais_par_jambe_viennent_de_la_doc_officielle():
    """Spot maker 4,0 / perp maker 1,5 — vérifié le 21/07 contre la doc Hyperliquid."""
    d = decomposer_entree(notional_usdt=1000.0, base_bps=0.0)
    assert d["frais_spot_bps"] == MAKER_SPOT_BPS == 4.0
    assert d["frais_perp_bps"] == MAKER_BPS == 1.5
    assert d["frais_2_jambes_bps"] == COUT_MAKER_2_JAMBES_BPS == 11.0


def test_le_spread_spot_est_l_ecart_VWAP_vs_MID():
    """C'est le seul poste qu'on sait isoler — et il pèse 3,3× les frais."""
    d = decomposer_entree(notional_usdt=1000.0, base_bps=0.0,
                          spot_px=100.30, spot_mid_px=100.00)
    assert d["spread_spot_bps"] == pytest.approx(30.0)
    assert d["spread_spot_usd"] == pytest.approx(3.0)


@pytest.mark.parametrize("manquant", [{"spot_px": None}, {"spot_mid_px": None},
                                      {"spot_mid_px": 0.0}])
def test_un_spread_non_mesurable_reste_None_JAMAIS_zero(manquant):
    """Un zéro fabriqué mentirait sur le coût réel de la position."""
    kw = {"spot_px": 100.3, "spot_mid_px": 100.0}
    kw.update(manquant)
    assert decomposer_entree(notional_usdt=1000.0, base_bps=0.0, **kw)["spread_spot_bps"] is None


def test_les_postes_NON_MESURES_sont_nommes():
    """On ne cache pas ce qu'on ne sait pas : le carnet perp n'est pas disponible à l'entrée."""
    d = decomposer_entree(notional_usdt=1000.0, base_bps=0.0)
    assert d["spread_perp_bps"] is None
    assert d["slippage_spot_bps"] is None and d["slippage_perp_bps"] is None
    assert set(d["postes_non_mesures"]) == {"spread_perp", "slippage_spot", "slippage_perp"}


# ------------------------------------------------------------------ pas de 2ᵉ standard

def test_la_decomposition_REDONNE_le_cout_du_moteur():
    """Un second calcul du même coût qui ne retombe pas sur le premier est un deuxième
    standard — le projet en a déjà payé le prix (les DEUX tables d'edge, 13/07)."""
    pos = {"cout_entree_bps": 11.0 - 3.0, "frais_2_jambes_bps": 11.0, "base_subie_bps": 3.0}
    c = coherence_avec_le_moteur(pos)
    assert c["coherent"] is True and c["ecart_bps"] == 0.0


def test_une_incoherence_est_DETECTEE_pas_absorbee():
    pos = {"cout_entree_bps": 99.0, "frais_2_jambes_bps": 11.0, "base_subie_bps": 3.0}
    assert coherence_avec_le_moteur(pos)["coherent"] is False


def test_donnee_absente_ne_produit_pas_un_faux_OK():
    assert coherence_avec_le_moteur({"cout_entree_bps": 8.0})["coherent"] is None


# ------------------------------------------------------------------ le hedge ratio

def test_le_hedge_est_MESURE_quand_les_deux_jambes_sont_connues():
    q = quantites_par_jambe(notional_usdt=100.0, perp_px=60000.0, spot_px=60000.0)
    h = hedge_ratio(q)
    assert h["statut"] == HEDGE_MESURE
    assert h["ratio"] == pytest.approx(1.0, abs=1e-6)
    assert abs(h["delta_usd"]) < 0.01


def test_le_hedge_est_MODELISE_quand_une_quantite_manque():
    """🔴 LE point du module : sans quantités, la neutralité est SUPPOSÉE. Le dire est le
    minimum ; l'afficher comme mesurée serait une fabrication."""
    h = hedge_ratio({"quantite_perp": 1.0, "prix_perp_entree": 100.0})
    assert h["statut"] == HEDGE_MODELISE
    assert h["delta_usd"] is None
    assert "SUPPOSEE" in h["note"] or "supposee" in h["note"].lower()


def test_un_hedge_DESEQUILIBRE_est_visible_en_dollars():
    """Si un jour le constructeur laisse passer un déséquilibre, il doit se voir."""
    h = hedge_ratio({"quantite_perp": 1.0, "prix_perp_entree": 100.0,
                     "quantite_spot": 1.2, "prix_spot_entree": 100.0})
    assert h["statut"] == HEDGE_MESURE
    assert h["ratio"] == pytest.approx(1.2)
    assert h["delta_usd"] == pytest.approx(20.0)


@pytest.mark.parametrize("prix", [0.0, -5.0, None])
def test_un_prix_absurde_ne_produit_pas_une_quantite(prix):
    q = quantites_par_jambe(notional_usdt=100.0, perp_px=prix, spot_px=prix)
    assert q["quantite_perp"] is None and q["quantite_spot"] is None


# ------------------------------------------------------------------ enrichissement & câblage

def test_enrichir_ne_MUTE_pas_la_position_source():
    """Une position est un fait : on ne la modifie pas en passant."""
    pos = {"notional_usdt": 100.0, "base_bps_entree": 3.0}
    copie = dict(pos)
    enrichir(pos, perp_px=100.0, spot_px=100.0)
    assert pos == copie


def test_l_economie_est_POSEE_A_L_OUVERTURE():
    """Testé ≠ branché : si la décomposition n'a pas lieu à l'ouverture, elle n'existe
    pour personne."""
    from hl_observer.funding.carry_position_lifecycle import ouvrir_position

    d = {"coin": "BTC", "viable": True, "funding_bps_h": 0.125, "cout_entree_bps": 8.0,
         "base_bps": 3.0, "gain_net_24h_bps": 2.2, "liquidite_spot_usd": 4e5}
    i = {"levier_utilise": 2.0, "levier_max": 10.0, "perp_px": 60000.0, "spot_px": 60018.0,
         "spot_mid_px": 60000.0, "pire_hausse_observee": 0.05, "liquidite_spot_usd": 4e5}
    pos = ouvrir_position(d, i, now_ms=1_760_000_000_000)
    assert pos is not None
    assert pos["frais_spot_bps"] == 4.0 and pos["frais_perp_bps"] == 1.5
    assert pos["spread_spot_bps"] == pytest.approx(3.0)
    assert pos["hedge"]["statut"] == HEDGE_MESURE
    assert coherence_avec_le_moteur(pos)["coherent"] is True


def test_le_feeder_publie_les_DEUX_prix_spot():
    """Sans `spot_px` ET `spot_mid_px`, le spread de la jambe spot reste non mesurable."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "tools"
           / "ecrire_carry_spot_inputs.py").read_text(encoding="utf-8")
    assert '"spot_px"' in src and '"spot_mid_px"' in src
