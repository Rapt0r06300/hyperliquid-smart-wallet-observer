"""LA PORTE DU COÛT D'OPPORTUNITÉ — battre l'alternative, pas seulement zéro (21/07).

Mesure qui l'a imposée : 12/12 positions ouvertes et 580/580 lectures de scan au **plancher
protocolaire** (0,125 bps/h) → APR net **2,65 %**, alors que le vault HLP paie **15-30 %**
(donnée publique, loi `hlp_benchmark`). Le capital rendait plus en dormant ailleurs.
"""
from __future__ import annotations

import pytest

from hl_observer.funding import carry_benchmark_gate as g


# ─────────────────────── l'arithmétique, vérifiée à la main ───────────────────────

def test_l_APR_au_plancher_vaut_bien_2_65_pourcent():
    """LE chiffre qui a déclenché la porte. S'il bouge, c'est la porte qu'il faut re-dériver."""
    apr = g.apr_net_pct(funding_bps_h=g.PLANCHER_PROTOCOLAIRE_BPS_H)
    assert apr == pytest.approx(2.65, abs=0.01)


def test_le_seuil_est_DERIVE_pas_choisi():
    """`funding_requis_bps_h` doit être l'inverse EXACT de `apr_net_pct` : un seuil qu'on ne
    sait pas recalculer à la main devient une constante magique que plus personne n'ose toucher."""
    for cible in (5.0, 15.0, 30.0, 45.0):
        f = g.funding_requis_bps_h(apr_cible_pct=cible)
        assert g.apr_net_pct(funding_bps_h=f) == pytest.approx(cible, abs=0.01)


def test_il_faut_2_13_fois_le_plancher_pour_egaler_HLP():
    f = g.funding_requis_bps_h(apr_cible_pct=g.BENCHMARK_APR_PCT)
    assert f == pytest.approx(0.266, abs=0.001)
    assert f / g.PLANCHER_PROTOCOLAIRE_BPS_H == pytest.approx(2.13, abs=0.01)


def test_l_APR_tient_compte_de_la_SORTIE_pas_seulement_de_l_entree():
    """Le bug du 21/07 matin (break-even sans la sortie) ne doit pas se rejouer ici."""
    from hl_observer.funding.delta_neutral_carry import COUT_MAKER_2_JAMBES_BPS
    avec = g.apr_net_pct(funding_bps_h=0.30)
    sans = g.apr_net_pct(funding_bps_h=0.30, cout_sortie_bps=0.0)
    assert sans > avec, "ignorer la sortie doit FLATTER le rendement — donc elle compte bien"
    ecart_bps = (sans - avec) / (24 * 365 / 100) * g.HORIZON_DEFAUT_H
    assert ecart_bps == pytest.approx(COUT_MAKER_2_JAMBES_BPS, abs=0.01)


def test_un_horizon_nul_ne_divise_pas_par_un_trou():
    assert g.apr_net_pct(funding_bps_h=0.5, horizon_h=0.0) is None
    assert g.apr_net_pct(funding_bps_h=0.5, horizon_h=-1.0) is None


# ─────────────────────── le verdict ───────────────────────

def test_le_plancher_est_refuse_avec_son_propre_motif():
    """« Au plancher » n'est pas « un peu trop bas » : c'est l'absence TOTALE de demande.
    Le motif doit le dire, sinon le ledger devient illisible."""
    v = g.evaluer(coin="BTC", funding_bps_h=0.125)
    assert v["autorise"] is False and v["motif"] == g.MOTIF_PLANCHER
    assert "personne ne paie" in v["explication"]


def test_un_rendement_positif_mais_domine_est_refuse():
    """LE point de la porte. 0,20 bps/h donne +9,2 % APR — POSITIF — et pourtant refusé,
    parce que le même capital rendrait 15 % ailleurs. Positif ne suffit pas."""
    v = g.evaluer(coin="ETH", funding_bps_h=0.20)
    assert v["apr_net_pct"] > 0, "le rendement est bien positif"
    assert v["autorise"] is False and v["motif"] == g.MOTIF_DOMINE
    assert v["funding_requis_bps_h"] > 0.20


def test_un_funding_qui_bat_le_benchmark_passe():
    v = g.evaluer(coin="HYPE", funding_bps_h=0.40)
    assert v["autorise"] is True and v["motif"] == ""
    assert v["apr_net_pct"] == pytest.approx(26.74, abs=0.05)
    assert v["multiple_du_plancher"] == pytest.approx(3.2, abs=0.01)


def test_funding_absent_ne_se_compare_pas_a_un_benchmark():
    for f in (None, float("nan"), "0.3", True):
        v = g.evaluer(coin="X", funding_bps_h=f)
        assert v["autorise"] is False and v["motif"] == g.MOTIF_DONNEE


def test_l_abattement_de_risque_est_TOUJOURS_reporte():
    """HLP n'est pas delta-neutre : un abattement se défend. Mais il doit être VISIBLE —
    on ne doit jamais pouvoir gagner une comparaison en baissant discrètement la barre.
    Même discipline que `carry_backtest`, qui refuse tout gain venant d'une baisse de sécurité."""
    strict = g.evaluer(coin="SOL", funding_bps_h=0.22)
    laxe = g.evaluer(coin="SOL", funding_bps_h=0.22, abattement_risque_pct=6.0)
    assert strict["autorise"] is False and laxe["autorise"] is True
    assert laxe["abattement_risque_pct"] == 6.0        # écrit noir sur blanc dans le verdict
    assert laxe["seuil_apr_pct"] == pytest.approx(9.0)
    assert strict["abattement_risque_pct"] == 0.0


def test_un_abattement_negatif_ne_releve_pas_la_barre_en_douce():
    v = g.evaluer(coin="X", funding_bps_h=0.40, abattement_risque_pct=-50.0)
    assert v["abattement_risque_pct"] == 0.0
    assert v["seuil_apr_pct"] == pytest.approx(g.BENCHMARK_APR_PCT)


# ─────────────────────── le portefeuille déjà ouvert ───────────────────────

def test_le_resume_convertit_les_dollars_par_heure_en_bps():
    """Le panneau publie `taux_accrual_usd_h`. Comparer des $/h à un seuil en bps/h, c'est
    exactement le piège d'unité qui a déjà coûté deux autopsies à ce projet."""
    r = g.resume_portefeuille([
        {"coin": "BTC", "notional_usdt": 1179.75, "taux_accrual_usd_h": 0.0147,
         "marge_usdt": 590.0},
    ])
    assert r["dominees"] == 1                      # 0,0147/1179,75 × 1e4 = 0,1246 bps/h
    assert r["marge_dominee_usd"] == pytest.approx(590.0)


def test_le_resume_dit_combien_de_capital_dort_sous_l_alternative():
    r = g.resume_portefeuille([
        {"coin": "A", "notional_usdt": 1000.0, "funding_bps_h": 0.125, "marge_usdt": 100.0},
        {"coin": "B", "notional_usdt": 1000.0, "funding_bps_h": 0.500, "marge_usdt": 100.0},
    ])
    assert r["positions"] == 2 and r["dominees"] == 1
    assert r["part_dominee_pct"] == 50.0
    assert r["marge_dominee_usd"] == pytest.approx(100.0)
    assert [d["coin"] for d in r["details"]] == ["A"]


def test_portefeuille_vide_ne_fabrique_pas_de_verdict():
    for p in (None, [], ["pas un dict"]):
        r = g.resume_portefeuille(p)
        assert r["dominees"] == 0


# ─────────────────────── LA PORTE EST-ELLE BRANCHÉE ? ───────────────────────

def test_la_porte_d_ouverture_refuse_vraiment_un_funding_au_plancher():
    """« mention ≠ porte » : le module ne vaut rien s'il n'est pas dans le chemin qui ouvre.
    Ce test appelle `porte_risque_ouverture`, le SEUL chemin d'ouverture du carry."""
    from hl_observer.funding.carry_ouverture_gates import porte_risque_ouverture as p
    r = p(marge_demandee_usd=50.0, funding_bps_h=0.125, coin="BTC")
    assert r["autorise"] is False
    assert r["motif"] == g.MOTIF_PLANCHER
    assert r["facteur_taille"] == 0.0
    assert "cout_opportunite:REFUS" in r["gardes"]
    assert r["benchmark"]["apr_net_pct"] == pytest.approx(2.65, abs=0.01)


def test_la_porte_laisse_passer_un_funding_qui_bat_le_benchmark():
    from hl_observer.funding.carry_ouverture_gates import porte_risque_ouverture as p
    r = p(marge_demandee_usd=50.0, funding_bps_h=0.45, coin="HYPE")
    assert r["autorise"] is True
    assert any("cout_opportunite:OK" in x for x in r["gardes"])


def test_sans_funding_la_porte_s_ABSTIENT_elle_ne_devine_pas():
    """Une donnée absente doit figer la décision de CETTE porte, pas inventer un rendement —
    et surtout pas bloquer les autres gardes qui, eux, ont leurs données."""
    from hl_observer.funding.carry_ouverture_gates import porte_risque_ouverture as p
    r = p(marge_demandee_usd=50.0)
    assert "cout_opportunite:ABSTENTION_funding_absent" in r["gardes"]


def test_le_cycle_de_vie_transmet_bien_le_funding_a_la_porte():
    """Le chaînon le plus fragile : la porte peut être parfaite et ne jamais recevoir le
    nombre. On vérifie que `carry_position_lifecycle` le passe explicitement."""
    import inspect

    from hl_observer.funding import carry_position_lifecycle as lc
    src = inspect.getsource(lc)
    assert "funding_bps_h=" in src, "le cycle de vie doit passer le funding a la porte"
    assert "cout_entree_bps=" in src


def test_la_porte_NE_FERME_PAS_les_positions_deja_ouvertes(tmp_path):
    """🔴 LE PIÈGE À NE PAS TOMBER DEDANS.

    Les 12 positions ouvertes sont toutes au plancher, donc toutes dominées. La tentation est
    de les fermer. **Ce serait une erreur chiffrable** : l'aller-retour coûte 11 bps sur
    2 819 $ = 3,10 $, pour échapper à une position qui rapporte 0,85 $/jour. On paierait
    3,6 jours de revenu pour arrêter de gagner 2,65 % — le coût est certain, le gain
    hypothétique.

    La porte est donc branchée sur le chemin d'OUVERTURE uniquement. « Ne plus ouvrir » et
    « fermer » sont deux actions différentes ; seule la première est gratuite. C'est la même
    leçon que `carry_anti_churn` : l'abstention est le défaut, l'action coûte.
    """
    import sys
    sys.path.insert(0, "tests")
    from test_carry_anti_churn import _mesure, tick_multi_sur_disque

    t0 = 1_800_000_000_000
    ouvert = tick_multi_sur_disque(tmp_path, _mesure(funding=0.45), now_ms=t0, max_slots=12)
    assert ouvert[0]["ouvert"] is True

    # le funding retombe AU PLANCHER : la position ne doit PAS être fermée pour autant
    apres = tick_multi_sur_disque(tmp_path, _mesure(funding=g.PLANCHER_PROTOCOLAIRE_BPS_H),
                                  now_ms=t0 + 3_600_000, max_slots=12)
    assert apres[0]["ferme"] is None, (
        "un funding devenu mediocre n'autorise pas a payer 11 bps de sortie")


def test_aucune_execution_reelle():
    assert g.evaluer(coin="X", funding_bps_h=0.5)["real_execution"] is False
