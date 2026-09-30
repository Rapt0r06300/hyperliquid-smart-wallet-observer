"""Tests de l'ALLOCATION PAR RENDEMENT NET (21/07).

Ce qu'ils PROUVENT :
  * le capital va bien AU MEILLEUR (l'inversion mesurée −0,596 est corrigée) ;
  * les garde-fous du capital sont identiques à ceux de `marge_par_position` (réserve,
    plafond de concentration, plancher, plafond dur) — c'est le MÊME capital ;
  * on ne finance jamais un rendement absent, nul ou négatif ;
  * on ne dégrade JAMAIS le comportement existant quand la donnée manque (retour au défaut) ;
  * le total alloué ne dépasse jamais le capital déployable — jamais de capital fantôme.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.carry_allocation_nette import (EXPOSANT_DEFAUT, allouer_marges,

# 🔴 22/07 — funding d'ENTREE des fixtures d'OUVERTURE releve du plancher (0.125) a
# 0.45 : la porte du cout d'opportunite (carry_benchmark_gate) refuse d'ouvrir au
# plancher (APR net 2,65 %% vs HLP 15-30 %%). Ces tests ont besoin qu'une position
# EXISTE. Les appels-maths revenu_journalier_usd(...=0.125) restent au plancher.

                                                        diagnostic, poids_par_rendement)
from hl_observer.funding.carry_marge_dynamique import (MARGE_MIN_USD, PART_MAX_PAR_COIN,
                                                       RESERVE_FRAC_DEFAUT, marge_par_position)

#: les 8 coins RÉELS de la shortlist du 21/07 (rendement net journalier mesuré par le moteur)
REEL = {"BTC": 2.221, "ETH": 1.836, "SOL": 1.608, "XPL": 1.542,
        "ZEC": 1.487, "STABLE": 1.326, "PURR": 1.259, "VIRTUAL": 1.158}


# ------------------------------------------------------------------ les poids

def test_le_meilleur_recoit_le_plus_le_pire_le_moins():
    p = poids_par_rendement(REEL)
    assert max(p, key=lambda c: p[c]) == "BTC"
    assert min(p, key=lambda c: p[c]) == "VIRTUAL"
    # et l'ordre des poids suit EXACTEMENT l'ordre des rendements
    assert sorted(p, key=lambda c: -p[c]) == sorted(REEL, key=lambda c: -REEL[c])


def test_les_poids_somment_a_un():
    assert sum(poids_par_rendement(REEL).values()) == pytest.approx(1.0, abs=1e-6)


def test_correlation_marge_rendement_devient_POSITIVE():
    """La mesure qui a déclenché le module : elle valait −0,596. Elle doit devenir > 0."""
    import statistics as st
    p = poids_par_rendement(REEL)
    xs, ys = [p[c] for c in REEL], [REEL[c] for c in REEL]
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    assert num / den > 0.9


def test_plafond_de_concentration_respecte_et_excedent_redistribue():
    p = poids_par_rendement({"A": 100.0, "B": 1.0, "C": 1.0})
    assert p["A"] == pytest.approx(PART_MAX_PAR_COIN, abs=1e-6)
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-6)
    assert p["B"] == pytest.approx(p["C"])          # le surplus se partage au prorata


def test_un_seul_coin_prend_tout_meme_au_dessus_du_plafond():
    """Le plafond protège d'une CONCENTRATION relative ; avec un seul candidat il n'y a
    rien à diversifier — refuser le capital ne protégerait de rien."""
    assert poids_par_rendement({"BTC": 2.0}) == {"BTC": 1.0}


@pytest.mark.parametrize("net", [None, 0.0, -3.0, float("nan"), True, "2.0"])
def test_rendement_non_finançable_recoit_zero(net):
    p = poids_par_rendement({"BON": 2.0, "MAUVAIS": net})
    assert "MAUVAIS" not in p
    assert p == {"BON": 1.0}


def test_aucun_rendement_positif_ne_produit_aucun_poids():
    assert poids_par_rendement({"A": -1.0, "B": 0.0}) == {}


def test_exposant_plus_grand_concentre_davantage():
    faible = poids_par_rendement(REEL, exposant=1.0)
    fort = poids_par_rendement(REEL, exposant=6.0)
    assert fort["BTC"] > faible["BTC"]
    assert fort["VIRTUAL"] < faible["VIRTUAL"]


# ------------------------------------------------------------------ les marges (le capital)

def test_le_total_alloue_ne_depasse_JAMAIS_le_capital_deployable():
    capital = 1000.0
    m = allouer_marges(REEL, capital_usd=capital)
    assert sum(m.values()) <= capital * (1.0 - RESERVE_FRAC_DEFAUT) + 0.5


@pytest.mark.parametrize("capital", [200.0, 800.0, 1000.0, 5000.0, 50_000.0])
def test_reserve_intouchable_a_tous_les_capitaux(capital):
    m = allouer_marges(REEL, capital_usd=capital)
    assert sum(m.values()) <= capital * (1.0 - RESERVE_FRAC_DEFAUT) + 0.5
    assert all(v == 0.0 or v >= MARGE_MIN_USD for v in m.values())


def test_le_meilleur_coin_recoit_plus_que_le_pire_en_dollars():
    m = allouer_marges(REEL, capital_usd=1000.0)
    assert m["BTC"] > m["VIRTUAL"] > 0


@pytest.mark.parametrize("capital", [None, 0.0, -5.0, float("nan"), True, "1000"])
def test_capital_inconnu_retombe_sur_le_defaut_sans_rien_degrader(capital):
    m = allouer_marges(REEL, capital_usd=capital)
    attendu = marge_par_position(capital_usd=capital, n_positions_visees=len(REEL))
    assert set(m) == set(REEL)
    assert all(v == attendu for v in m.values())


def test_aucun_rendement_positif_retombe_sur_le_defaut():
    nets = {"A": -1.0, "B": 0.0}
    m = allouer_marges(nets, capital_usd=1000.0)
    assert set(m) == {"A", "B"}
    attendu = marge_par_position(capital_usd=1000.0, n_positions_visees=2)
    assert all(v == attendu for v in m.values())


def test_les_miettes_sont_coupees_et_leur_capital_redistribue():
    """Sous le plancher, une position ne paie même pas ses frais fixes : on préfère MOINS de
    lignes correctement dimensionnées."""
    m = allouer_marges(REEL, capital_usd=300.0)          # 240 $ déployables pour 8 coins
    finances = {c: v for c, v in m.items() if v > 0}
    assert len(finances) < len(REEL)
    assert all(v >= MARGE_MIN_USD for v in finances.values())
    assert "BTC" in finances                              # le meilleur survit toujours
    assert sum(finances.values()) <= 240.0 + 0.5


def test_capital_minuscule_finance_le_meilleur_seulement():
    m = allouer_marges(REEL, capital_usd=40.0)            # 32 $ déployables < plancher 25 ×2
    finances = {c: v for c, v in m.items() if v > 0}
    assert list(finances) == ["BTC"]
    assert finances["BTC"] <= 32.0


def test_coin_ecarte_recoit_zero_explicitement_jamais_une_cle_manquante():
    m = allouer_marges({"BON": 2.0, "PERDANT": -1.0}, capital_usd=1000.0)
    assert m["PERDANT"] == 0.0
    assert m["BON"] > 0


def test_plafond_dur_par_position():
    m = allouer_marges({"BTC": 2.0}, capital_usd=10_000_000.0, marge_max_usd=1500.0)
    assert m["BTC"] == 1500.0


# ------------------------------------------------------------------ le gain, mesuré

def test_le_gain_vs_part_egale_est_reel_et_annonce_honnetement():
    m = allouer_marges(REEL, capital_usd=1000.0)
    d = diagnostic(REEL, m)
    assert d["meilleur"] == "BTC"
    assert d["rendement_pondere_bps_j"] > d["rendement_part_egale_bps_j"]
    assert 5.0 < d["gain_vs_part_egale_pct"] < 40.0      # mesuré ~+14 % le 21/07
    assert d["capital_alloue_usd"] <= 800.5              # réserve 20 % respectée


def test_diagnostic_sur_allocation_vide_ne_casse_pas():
    d = diagnostic({}, {})
    assert d["coins_finances"] == 0 and d["gain_vs_part_egale_pct"] is None


# ------------------------------------------------------------------ le garde du plancher (z-score)

def test_le_zscore_ne_module_plus_rien_au_plancher_protocolaire():
    """LA CAUSE de l'inversion : au plancher, tous les coins sont à 0,125 par construction de
    la venue — un z-score y mesure du bruit, pas une opportunité."""
    from hl_observer.funding.carry_optimizer import facteur_zscore
    from hl_observer.funding.funding_previsionnel import TAUX_INTERET_BPS_H

    assert facteur_zscore(2.5, TAUX_INTERET_BPS_H) == 1.0
    assert facteur_zscore(-2.0, TAUX_INTERET_BPS_H) == 1.0
    assert facteur_zscore(2.5, TAUX_INTERET_BPS_H - 0.01) == 1.0     # sous le plancher aussi
    # au-dessus du plancher, il retrouve tout son rôle
    assert facteur_zscore(2.5, 0.40) == 1.5
    assert facteur_zscore(-2.0, 0.40) == 0.5
    # appelé sans funding -> comportement historique intact (aucun appelant cassé)
    assert facteur_zscore(2.5) == 1.5


# ------------------------------------------------------------------ le chemin de PRODUCTION

def test_chemin_production_le_meilleur_coin_recoit_vraiment_plus_de_capital(tmp_path):
    """`tick_multi_sur_disque` est le seul chemin qui tourne. On y prouve que l'allocation
    ARRIVE jusqu'aux positions — testé ≠ branché, la maladie du projet."""
    import json

    from hl_observer.funding.carry_positions_store import (charger_gestionnaire,
                                                           tick_multi_sur_disque)

    def mesure(coin, net, lev):
        return {"decision": {"coin": coin, "viable": True, "funding_bps_h": 0.45,
                             "cout_entree_bps": 10.0, "base_bps": 5.0,
                             "gain_net_24h_bps": net, "liquidite_spot_usd": 400_000.0},
                "inputs": {"levier_utilise": lev, "levier_max": lev, "perp_px": 100.0,
                           "pire_hausse_observee": 0.01, "liquidite_spot_usd": 400_000.0},
                "funding": 0.45}

    mesures = {"BTC": mesure("BTC", 2.221, 3.0), "VIRTUAL": mesure("VIRTUAL", 1.158, 3.0)}
    tick_multi_sur_disque(tmp_path, mesures, now_ms=1_760_000_000_000, mode="TEST_FIXTURE",
                          capital_usd=1000.0)
    ouvertes = charger_gestionnaire(tmp_path, mode="TEST_FIXTURE").ouvertes
    assert set(ouvertes) == {"BTC", "VIRTUAL"}
    assert ouvertes["BTC"]["marge_usdt"] > ouvertes["VIRTUAL"]["marge_usdt"]
    # ... et le levier est IDENTIQUE : on a déplacé du capital, pas acheté du risque
    assert ouvertes["BTC"]["levier"] == ouvertes["VIRTUAL"]["levier"]

    # le diagnostic est publié, lisible, et honnête sur son gain
    d = json.loads((tmp_path / "runtime" / "data" / "carry_allocation.json").read_text("utf-8"))
    assert d["meilleur"] == "BTC" and d["coins_finances"] == 2
    assert d["gain_vs_part_egale_pct"] > 0
    assert d["real_execution"] is False


def test_chemin_production_donnee_absente_ne_degrade_rien(tmp_path):
    """Sans `gain_net_24h_bps`, on retombe EXACTEMENT sur la marge par défaut d'avant."""
    from hl_observer.funding.carry_marge_dynamique import marge_par_position
    from hl_observer.funding.carry_positions_store import (charger_gestionnaire,
                                                           tick_multi_sur_disque)

    mes = {c: {"decision": {"coin": c, "viable": True, "funding_bps_h": 0.45,
                            "cout_entree_bps": 10.0, "base_bps": 5.0,
                            "liquidite_spot_usd": 400_000.0},
               "inputs": {"levier_utilise": 3.0, "levier_max": 3.0, "perp_px": 100.0,
                          "pire_hausse_observee": 0.01, "liquidite_spot_usd": 400_000.0},
               "funding": 0.45} for c in ("BTC", "ETH")}
    tick_multi_sur_disque(tmp_path, mes, now_ms=1_760_000_000_000, mode="TEST_FIXTURE",
                          capital_usd=1000.0)
    attendu = marge_par_position(capital_usd=1000.0, n_positions_visees=2)
    for p in charger_gestionnaire(tmp_path, mode="TEST_FIXTURE").ouvertes.values():
        assert p["marge_usdt"] == pytest.approx(attendu)