"""TIMING DU RÈGLEMENT (idée #6) — le seul gain gratuit du carry.

Hyperliquid règle au sommet de chaque heure. Ouvrir à H−1 min capture un paiement une minute
plus tard ; fermer à H−1 min le perd entièrement.

Ce que ces tests VERROUILLENT :
  * un DANGER n'est JAMAIS retardé — pas même pour un règlement (le capital d'abord) ;
  * un funding ≤ 0 inverse le conseil : attendre COÛTERAIT ;
  * on n'attend jamais assez longtemps pour que les inputs se périment.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_timing_reglement import (ATTENTE_MAX_OUVERTURE_MS, PERIODE_MS,
                                                        conseil_ouverture, conseil_sortie,
                                                        ms_avant_reglement, ms_depuis_reglement,
                                                        valeur_annuelle_usd)

H = PERIODE_MS
T_PILE = (1_760_000_000_000 // H) * H
MIN = 60_000


def test_le_compte_a_rebours_est_juste():
    assert ms_avant_reglement(T_PILE) == 0
    assert ms_avant_reglement(T_PILE + 59 * MIN) == MIN
    assert ms_depuis_reglement(T_PILE + 3 * MIN) == 3 * MIN


def test_periode_absurde_ne_leve_pas():
    assert ms_avant_reglement(T_PILE + MIN, periode_ms=0) >= 0


# ------------------------------------------------------------------ ouverture

def test_on_attend_quand_le_reglement_est_PROCHE_et_qu_il_rapporte():
    c = conseil_ouverture(T_PILE + 58 * MIN, funding_bps_h=0.125)
    assert c["attendre"] is True and c["ms"] == 2 * MIN and c["gain_bps"] == 0.125


def test_on_n_attend_PAS_si_le_reglement_est_loin():
    """Une opportunité de carry ne se met pas en pause 40 minutes pour 0,125 bps : les
    inputs spot se périment à 15 min, on déciderait sur du passé."""
    c = conseil_ouverture(T_PILE + 20 * MIN, funding_bps_h=0.125)
    assert c["attendre"] is False and "perimeraient" in c["motif"]


def test_sur_le_sommet_on_ouvre_TOUT_DE_SUITE():
    assert conseil_ouverture(T_PILE, funding_bps_h=0.125)["attendre"] is False


@pytest.mark.parametrize("funding", [0.0, -0.3, -2.0])
def test_un_funding_NEGATIF_inverse_le_conseil(funding):
    """Le short PAIE : capturer le règlement serait payer. On ouvre APRÈS le sommet."""
    c = conseil_ouverture(T_PILE + 59 * MIN, funding_bps_h=funding)
    assert c["attendre"] is False and "COUTE" in c["motif"]


def test_l_attente_ne_depasse_JAMAIS_le_plafond():
    for m in range(0, 60):
        c = conseil_ouverture(T_PILE + m * MIN, funding_bps_h=0.125)
        assert c["ms"] <= ATTENTE_MAX_OUVERTURE_MS


# ------------------------------------------------------------------ sortie

def test_un_DANGER_n_est_JAMAIS_retarde():
    """LA règle qui prime sur toutes les autres. Attendre 2 minutes pour 0,125 bps pendant
    qu'une jambe se fait liquider coûterait cent fois ce que ça rapporte."""
    for motif in ("LA_JAMBE_PERP_AURAIT_ETE_LIQUIDEE", "KILL_SWITCH", "FUNDING_HEMORRAGIE"):
        c = conseil_sortie(T_PILE + 59 * MIN, funding_bps_h=0.125, motif_sortie=motif)
        assert c["attendre"] is False
        assert "DANGER" in c["motif"]


def test_une_sortie_ORDINAIRE_patiente_pour_garder_le_reglement():
    c = conseil_sortie(T_PILE + 59 * MIN, funding_bps_h=0.125,
                       motif_sortie="PRISE_PROFIT_BASE_NET_POSITIF")
    assert c["attendre"] is True and c["ms"] == MIN


def test_on_ne_patiente_pas_si_le_reglement_n_est_pas_imminent():
    c = conseil_sortie(T_PILE + 10 * MIN, funding_bps_h=0.125, motif_sortie="AGE_MAX")
    assert c["attendre"] is False


def test_un_funding_negatif_fait_SORTIR_tout_de_suite():
    c = conseil_sortie(T_PILE + 59 * MIN, funding_bps_h=-0.4, motif_sortie="AGE_MAX")
    assert c["attendre"] is False and "COUTE" in c["motif"]


# ------------------------------------------------------------------ la taille du gain, sans illusion

def test_la_valeur_annuelle_est_calculee_et_reste_MODESTE():
    """On mesure ce que ça vaut pour ne pas s'illusionner : gratuit ≠ gros."""
    v = valeur_annuelle_usd(1400.0, 0.125, allers_retours_par_mois=2.0)
    assert 0.5 < v < 2.0, v


def test_le_gain_grandit_avec_le_funding_et_le_notionnel():
    assert valeur_annuelle_usd(1400.0, 0.5) > valeur_annuelle_usd(1400.0, 0.125)
    assert valeur_annuelle_usd(5000.0, 0.125) > valeur_annuelle_usd(1400.0, 0.125)


# ------------------------------------------------------------------ testé ≠ branché

def test_le_timing_est_BRANCHE_dans_la_sortie_du_lifecycle():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "funding"
           / "carry_position_lifecycle.py").read_text(encoding="utf-8")
    assert "carry_timing_reglement" in src
    assert "sortie_reportee_reglement" in src


def test_bout_en_bout_une_sortie_ORDINAIRE_est_reportee_mais_pas_un_DANGER():
    """Le report doit se voir dans l'événement du tick, et le danger doit passer outre."""
    from hl_observer.funding.carry_position_lifecycle import GestionnaireCarry

    inputs = {"levier_utilise": 3.0, "levier_max": 3.0, "perp_px": 100.0,
              "pire_hausse_observee": 0.01, "liquidite_spot_usd": 500_000.0}
    dec = {"coin": "HYPE", "viable": True, "funding_bps_h": 0.125, "cout_entree_bps": 12.0,
           "base_bps": 20.0, "gain_net_24h_bps": 3.0, "liquidite_spot_usd": 50_000.0}
    g = GestionnaireCarry(mode="TEST_FIXTURE")
    g.tick(dec, inputs, now_ms=T_PILE, marge_usd=50.0, risque_contexte={"capital_usd": 5000.0})
    # l'anti-churn (A3) annule toute sortie non amortie : on force l'amortissement, sinon on
    # testerait le garde anti-churn, pas le timing.
    g.ouvertes["HYPE"]["funding_accrued_usdt"] = 50.0
    # âge > 96 h (anti-churn A3) ET décision NON viable — depuis le 21/07, une position
    # VIABLE n'est plus fermée à l'âge max, elle est revalidée. Il faut donc une vraie
    # raison de sortir pour que le timing du règlement ait quelque chose à reporter.
    dec_ko = dict(dec)
    dec_ko["viable"] = False
    evt = g.tick(dec_ko, inputs, now_ms=T_PILE + 120 * H + 59 * MIN, marge_usd=50.0,
                 age_max_h=1.0, risque_contexte={"capital_usd": 5000.0})
    assert evt.get("sortie_reportee_reglement"), evt
    assert evt["ferme"] is None, "la position doit rester ouverte une minute de plus"
    # une minute plus tard, le reglement est passe : la sortie s'execute
    evt2 = g.tick(dec_ko, inputs, now_ms=T_PILE + 121 * H + 1 * MIN, marge_usd=50.0,
                  age_max_h=1.0, risque_contexte={"capital_usd": 5000.0})
    assert evt2.get("ferme"), evt2
