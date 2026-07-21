"""FUNDING PRÉVISIONNEL — la formule PUBLIQUE d'HL transformée en lunettes vers l'avant.

Trois lois testées :
  1. la formule reproduit LE PLANCHER (premium≈0 -> 0,125 bps/h, 57 % de nos relevés) ;
  2. elle suit le premium quand il est grand (le clamp lâche) — c'est LA prévisibilité
     que les desks exploitent (« basis is a strong predictor of next funding ») ;
  3. la prévision ne peut que RÉDUIRE la taille (décrue -> ÷2), JAMAIS l'amplifier :
     un edge se mesure sur du réalisé (A4), pas sur une promesse.
"""
from __future__ import annotations

from hl_observer.funding.funding_previsionnel import (
    facteur_prevision, prevoir_funding_bps_h, tendance,
    TENDANCE_BAISSE, TENDANCE_HAUSSE, TENDANCE_STABLE,
)


def test_1_premium_nul_donne_LE_PLANCHER():
    assert prevoir_funding_bps_h(0.0) == 0.125
    assert prevoir_funding_bps_h(0.05) == 0.125          # petit premium : clamp comble jusqu'au plancher


def test_2_la_BANDE_MORTE_du_clamp_et_son_POINT_DE_RUPTURE():
    """🌟 DECOUVERTE (en ecrivant ce test) plus fine que la litterature : le clamp ±5 bps/h
    cree une BANDE MORTE — tant que |premium| <= ~5 bps, F = 0,125 EXACTEMENT (voila pourquoi
    57 % de nos 105k releves sont pile au plancher). Le funding ne DECOLLE qu'au-dela :
    F = premium − 5. => LE signal avance d'un spike n'est pas 'la base monte', c'est
    'le premium APPROCHE 5 bps'. Un seuil net, gratuit, en avance d'une heure."""
    assert prevoir_funding_bps_h(3.0) == 0.125           # DANS la bande : plancher exact
    assert prevoir_funding_bps_h(5.0) == 0.125           # encore dans la bande
    assert prevoir_funding_bps_h(6.0) == 1.0             # RUPTURE : F = 6 - 5
    assert prevoir_funding_bps_h(10.0) == 5.0            # F = P - 5
    assert prevoir_funding_bps_h(-10.0) == -5.0          # symetrique


def test_3_tendances_avec_bande_morte():
    assert tendance(0.25, 0.125) == TENDANCE_HAUSSE      # x2
    assert tendance(0.05, 0.125) == TENDANCE_BAISSE      # -60%
    assert tendance(0.13, 0.125) == TENDANCE_STABLE      # +4% : bande morte
    assert tendance(None, 0.125) == TENDANCE_STABLE


def test_4_la_prevision_REDUIT_mais_n_amplifie_JAMAIS():
    assert facteur_prevision(0.05, 0.125) == 0.5         # decrue franche -> taille /2
    assert facteur_prevision(5.0, 0.125) == 1.0          # hausse annoncee -> PAS d'amplification
    assert facteur_prevision(None, 0.125) == 1.0
    assert facteur_prevision(0.2, 0.125) == 1.0


def test_5_le_feeder_ECRIT_les_champs_de_prevision():
    """Mention != porte : les champs doivent partir dans les inputs que lit le moteur."""
    src = open("tools/ecrire_carry_spot_inputs.py", encoding="utf-8").read()
    assert '"funding_prevu_bps_h"' in src and '"funding_tendance"' in src
    assert "facteur_prevision" in src and "premium_bps" in src and "oraclePx" in src


# ---------------- 21/07 : LE CHASSEUR DE SPIKES — l'alerte touche enfin la TAILLE ----------------

def test_facteur_rupture_amplifie_UNIQUEMENT_sur_un_CONSTAT_jamais_sur_une_prevision():
    """RUPTURE_HAUTE = premium >= 5,125 bps ⟹ F = P−5 DEJA (formule publique de la venue) :
    c'est un CONSTAT. APPROCHE_HAUTE est une PREVISION -> jamais d'amplification (leçon du
    facteur_prevision qui ne peut que reduire)."""
    from hl_observer.funding.funding_previsionnel import (
        FACTEUR_RUPTURE_CONFIRMEE, FACTEUR_RUPTURE_SEULE, alerte_rupture, facteur_rupture)
    assert facteur_rupture(alerte_rupture(8.0, 3.0)) == FACTEUR_RUPTURE_CONFIRMEE  # +OI
    assert facteur_rupture(alerte_rupture(8.0)) == FACTEUR_RUPTURE_SEULE
    assert facteur_rupture(alerte_rupture(4.5)) == 1.0          # APPROCHE = prevision
    assert facteur_rupture(alerte_rupture(-8.0)) == 1.0         # rupture BASSE (cross-venue)
    assert facteur_rupture(None) == 1.0 and facteur_rupture({}) == 1.0


def test_le_facteur_rupture_est_CABLE_dans_le_feeder():
    """Mention != porte : l'alerte doit multiplier `facteur_taille`, pas seulement s'afficher."""
    src = open("tools/ecrire_carry_spot_inputs.py", encoding="utf-8").read()
    assert "facteur_rupture(p.get(\"alerte_rupture\"))" in src
    assert "facteur_taille" in src
