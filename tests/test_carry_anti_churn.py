"""ANTI-CHURN — les tests qui reproduisent le bug à 5 $ et prouvent qu'il ne peut plus revenir.

LE FAIT MESURÉ (19/07) :
    opens = 32   closes = 31   sur 22,3 h   toujours HYPE
    motif : COIN_PLUS_DANS_SHORTLIST × 29        realized = -4,998 $
    funding réellement encaissé sur la position vivante : 0,000457 $

À 0,125 bps/h sur 75 $ de notional, un aller-retour (17,6 centimes) détruit ~188 HEURES de
funding. Le PnL n'était pas figé : il était MANGÉ, toutes les 15 minutes, parce qu'un fichier
n'avait pas été écrit à temps.
"""
from __future__ import annotations

from hl_observer.funding.carry_anti_churn import (
    MINUTES_ABSENCE_TOLEREES, PASSES_ABSENCE_TOLEREES, SORTIE_ABSENCE_PROLONGEE,
    churn_excessif, doit_fermer_pour_absence, est_un_danger, filtrer_sortie,
    funding_sous_seuil_de_sortie, heures_pour_amortir, sortie_rentable)
from hl_observer.funding.carry_positions_store import diagnostic_churn, tick_multi_sur_disque


# ---------------------------------------------------------------- A1 : l'absence n'est pas une sortie

def test_une_absence_BREVE_ne_ferme_RIEN():
    """LE CŒUR DU BUG : le feeder saute une passe -> l'ancienne version fermait (17,6 centimes)."""
    assert doit_fermer_pour_absence(absences_consecutives=1, minutes_depuis_1re_absence=10.0) is False
    assert doit_fermer_pour_absence(absences_consecutives=2, minutes_depuis_1re_absence=20.0) is False


def test_une_absence_PROLONGEE_ferme_bien():
    """Tolérer n'est pas ignorer : si la donnée a VRAIMENT disparu, on sort."""
    assert doit_fermer_pour_absence(
        absences_consecutives=PASSES_ABSENCE_TOLEREES,
        minutes_depuis_1re_absence=MINUTES_ABSENCE_TOLEREES) is True


def test_il_faut_les_DEUX_conditions():
    """Un poll rapide compterait vite les passes ; un poll lent compterait vite les minutes.
    Exiger les deux neutralise les deux faux positifs symétriques."""
    assert doit_fermer_pour_absence(absences_consecutives=99, minutes_depuis_1re_absence=1.0) is False
    assert doit_fermer_pour_absence(absences_consecutives=1, minutes_depuis_1re_absence=999.0) is False


# ---------------------------------------------------------------- A3 : amortir avant de sortir

def test_le_temps_d_amortissement_est_celui_qu_on_a_mesure():
    """12,47 bps d'entrée à 0,125 bps/h -> ~100 h. C'est le chiffre réel de la position HYPE."""
    assert round(heures_pour_amortir(cout_entree_bps=12.47, funding_bps_h=0.125)) == 100


def test_funding_nul_rend_l_amortissement_impossible():
    assert heures_pour_amortir(cout_entree_bps=12.0, funding_bps_h=0.0) == float("inf")


def test_une_sortie_NON_URGENTE_est_ANNULEE_tant_que_l_entree_n_est_pas_amortie():
    pos = {"entry_ts_ms": 1_000_000, "cout_entree_bps": 12.47}
    apres_2h = 1_000_000 + int(2 * 3.6e6)
    assert filtrer_sortie("SORTIE_AGE", pos, now_ms=apres_2h, funding_bps_h=0.125) is None


def test_une_sortie_de_DANGER_passe_TOUJOURS():
    """RÈGLE INTOUCHABLE : le capital avant l'économie de frais. Aucune optimisation ne
    retarde une liquidation."""
    pos = {"entry_ts_ms": 1_000_000, "cout_entree_bps": 12.47}
    apres_1min = 1_000_000 + 60_000
    assert filtrer_sortie("SORTIE_LIQUIDATION", pos, now_ms=apres_1min,
                          funding_bps_h=0.125) == "SORTIE_LIQUIDATION"
    assert est_un_danger("SORTIE_LIQUIDATION") is True
    assert est_un_danger("SORTIE_AGE") is False


def test_A6_un_tick_sous_zero_ne_sort_PAS_mais_l_hemorragie_OUI():
    """🔴 RÉÉCRIT (19/07 soir, 2e chasse). L'ancienne version laissait sortir au PREMIER tick a
    funding <= 0 : on payait ~11 bps pour eviter un cout quasi nul, puis on rouvrait a 7 bps
    quand le taux remontait (HYPE a fait 0,047 -> 0,125 aujourd'hui). Nouvelle regle :
    bruit tolere · persistance = sortie · hemorragie (<= -0,5 bps/h) = sortie IMMEDIATE."""
    from hl_observer.funding.carry_anti_churn import (
        MINUTES_FUNDING_NEG_TOLEREES, PASSES_FUNDING_NEG_TOLEREES)

    pos = {"entry_ts_ms": 1_000_000, "cout_entree_bps": 12.47}
    # 1) un tick a 0.0 : TOLERE (garder coute ~rien, fermer coute 11 bps)
    assert filtrer_sortie("SORTIE_FUNDING", pos, now_ms=1_060_000, funding_bps_h=0.0) is None
    assert pos["funding_negatif_consecutifs"] == 1
    # 2) persistance (> passes ET > minutes) : la, on sort — ce n'est plus du bruit
    t = 1_060_000
    for _ in range(PASSES_FUNDING_NEG_TOLEREES):
        t += int(MINUTES_FUNDING_NEG_TOLEREES / PASSES_FUNDING_NEG_TOLEREES * 60_000) + 60_000
        dernier = filtrer_sortie("SORTIE_FUNDING", pos, now_ms=t, funding_bps_h=-0.01)
    assert dernier == "SORTIE_FUNDING", "un negatif PERSISTANT doit finir par sortir"
    # 3) le retour en positif REMET le compteur a zero (pas de contamination d'episode)
    filtrer_sortie(None, pos, now_ms=t + 60_000, funding_bps_h=0.125)
    assert "funding_negatif_consecutifs" not in pos
    # 4) hemorragie : -1 bps/h = -24 bps/jour, plus cher que la fermeture -> IMMEDIAT
    assert filtrer_sortie("SORTIE_FUNDING", pos, now_ms=t + 120_000,
                          funding_bps_h=-1.0) == "SORTIE_FUNDING"


def test_apres_amortissement_la_sortie_passe():
    pos = {"entry_ts_ms": 1_000_000, "cout_entree_bps": 12.47}
    apres_150h = 1_000_000 + int(150 * 3.6e6)
    assert filtrer_sortie("SORTIE_AGE", pos, now_ms=apres_150h,
                          funding_bps_h=0.125) == "SORTIE_AGE"


# ---------------------------------------------------------------- A2 / A4 / A5

def test_hysteresis_une_baisse_legere_ne_ferme_pas():
    assert funding_sous_seuil_de_sortie(funding_courant_bps_h=0.11,
                                        funding_entree_bps_h=0.125) is False
    assert funding_sous_seuil_de_sortie(funding_courant_bps_h=0.05,
                                        funding_entree_bps_h=0.125) is True


def test_sortir_doit_rapporter_plus_que_les_frais_de_sortie():
    assert sortie_rentable(gain_attendu_bps=5.0, cout_sortie_bps=11.0) is False
    assert sortie_rentable(gain_attendu_bps=20.0, cout_sortie_bps=11.0) is True


def test_le_churn_est_detecte():
    assert churn_excessif(allers_retours_24h=2) is False
    assert churn_excessif(allers_retours_24h=31) is True, "31 A/R = exactement ce qu'on a vécu"


# ---------------------------------------------------------------- bout en bout, sur disque

def _mesure(coin="HYPE"):
    decision = {"coin": coin, "viable": True, "funding_bps_h": 0.125, "base_bps": -1.5,
                "levier": 1.5, "cout_entree_bps": 12.47, "gain_net_24h_bps": 46.5,
                "liquidite_spot_usd": 150_000.0, "marge_ratio": 0.667, "levier_max": 10.0,
                "pire_hausse_observee": 0.29}
    inputs = {"coin": coin, "perp_px": 61.0, "levier_max": 10.0, "marge_ratio": 0.667,
              "liquidite_spot_usd": 150_000.0, "pire_hausse_observee": 0.29}
    return {coin: {"decision": decision, "inputs": inputs, "funding": 0.125,
                   "prix": 61.0, "base": -1.5}}


def test_BOUT_EN_BOUT_le_coin_qui_disparait_une_passe_NE_SE_FERME_PLUS(tmp_path):
    """LA RÉGRESSION QUI A COÛTÉ 5 $ : ouvrir, puis une passe sans le coin -> on GARDE."""
    t0 = 1_800_000_000_000
    tick_multi_sur_disque(tmp_path, _mesure(), now_ms=t0, max_slots=12)

    evts = tick_multi_sur_disque(tmp_path, {}, now_ms=t0 + 600_000, max_slots=12)  # +10 min, coin absent

    assert all(e.get("ferme") is None for e in evts), "une absence brève ne doit RIEN fermer"
    assert any(e.get("attente_donnee") for e in evts), "l'attente doit être tracée, pas silencieuse"
    from hl_observer.funding.carry_positions_store import etat_carry
    assert etat_carry(tmp_path)["positions_ouvertes"] == 1


def test_BOUT_EN_BOUT_une_absence_vraiment_prolongee_ferme(tmp_path):
    t0 = 1_800_000_000_000
    tick_multi_sur_disque(tmp_path, _mesure(), now_ms=t0, max_slots=12)
    for i in range(1, 4):                                   # 3 passes, 60 min plus tard
        evts = tick_multi_sur_disque(tmp_path, {}, now_ms=t0 + i * 3_600_000, max_slots=12)
    assert any(e.get("ferme") == SORTIE_ABSENCE_PROLONGEE for e in evts)


def test_le_diagnostic_de_churn_voit_les_allers_retours(tmp_path):
    """Ce que le dashboard n'affichait pas : 32/31 sur un coin, pendant 22 h, invisible."""
    t0 = 1_800_000_000_000
    for i in range(4):                                      # 4 cycles ouvre/ferme forcés
        tick_multi_sur_disque(tmp_path, _mesure(), now_ms=t0 + i * 14_400_000, max_slots=12)
        for k in range(1, 4):
            tick_multi_sur_disque(tmp_path, {}, now_ms=t0 + i * 14_400_000 + k * 3_600_000,
                                  max_slots=12)
    d = diagnostic_churn(tmp_path, now_ms=t0 + 20 * 3_600_000, fenetre_h=24.0)
    assert "HYPE" in d["par_coin"]
    assert d["par_coin"]["HYPE"]["opens"] >= 3
