"""#3/#530 — la MESURE d'edge post-liquidation DISCRIMINE : edge quand le prix rebondit, PAS d'edge
quand il continue, et INSUFFISANT (échec bruyant) sur trop peu d'événements. Aucune donnée réseau."""
from __future__ import annotations

import pytest

from hl_observer.backtesting.liquidation_edge_measure import (
    DonneesLiquidationInsuffisantes, direction_trade, exiger_assez_d_evenements,
    mesurer_edge_liquidation, rendement_net_bps,
)


def _events(n: int, coin: str = "BTC", prix: float = 100.0):
    # n liquidations de LONGS (sens VENTE) -> le fade est LONG (on parie sur le rebond)
    return [{"coin": coin, "ts_ms": 1_000_000, "prix": prix, "sens": "VENTE"} for _ in range(n)]


def test_direction_relachee_correcte():
    assert direction_trade("VENTE") == "LONG"      # longs liquidés -> le haut est relâché
    assert direction_trade("ACHAT") == "SHORT"
    assert direction_trade("???") is None


def test_rendement_net_signe_correct():
    path = [(1000.0, 100.0), (1500.0, 101.0)]      # +1% = +100 bps
    r = rendement_net_bps(100.0, path, 1000.0, "LONG", horizon_s=1800.0, cout_bps=12.0)
    assert r is not None and abs(r - (100.0 - 12.0)) < 1e-6   # +88 bps net


def test_edge_positif_quand_le_prix_REBONDIT():
    marks = {"BTC": [(1000.0, 100.0), (1100.0, 100.5), (1500.0, 101.0)]}  # rebond +1%
    rap = mesurer_edge_liquidation(_events(60), marks, horizon_s=1800.0)
    assert rap.n_mesurables == 60
    assert rap.verdict == "EDGE_NET_POSITIF"
    assert rap.edge_net_moyen_bps > 0


def test_pas_d_edge_quand_le_prix_CONTINUE():
    marks = {"BTC": [(1000.0, 100.0), (1100.0, 99.5), (1500.0, 99.0)]}   # continue -1%
    rap = mesurer_edge_liquidation(_events(60), marks, horizon_s=1800.0)
    assert rap.verdict == "PAS_D_EDGE"
    assert rap.edge_net_moyen_bps < 0


def test_donnees_insuffisantes_echec_bruyant():
    marks = {"BTC": [(1000.0, 100.0), (1500.0, 101.0)]}
    rap = mesurer_edge_liquidation(_events(10), marks, horizon_s=1800.0)   # 10 < 50
    assert rap.verdict == "INSUFFISANT"
    with pytest.raises(DonneesLiquidationInsuffisantes):
        exiger_assez_d_evenements(rap)


def test_evenement_sans_futur_non_mesurable():
    # marks TOUS antérieurs à l'entrée -> aucun futur -> non mesurable -> tombe en INSUFFISANT
    marks = {"BTC": [(100.0, 100.0), (200.0, 100.0)]}
    rap = mesurer_edge_liquidation(_events(60), marks, horizon_s=1800.0)
    assert rap.n_mesurables == 0 and rap.verdict == "INSUFFISANT"


# ---------------- 20/07 : l'ARTEFACT +735 bps attrape AVANT publication ----------------
# Mesurer sur les snapshots de la carte B9 = « entrer » au niveau de liquidation (~700 bps
# sous le marche, un prix ou PERSONNE n'a trade) et compter 54x la meme grappe. Hit 100 %.
# La transformation `evenements_declenches` impose : franchissement REEL du niveau par le
# mark, entree AU MARK, dedupe par grappe.

from hl_observer.backtesting.liquidation_edge_measure import evenements_declenches


def _grappe(ts_s, prix, coin="BTC", sens="SELL"):
    return {"coin": coin, "prix": prix, "sens": sens, "ts_ms": ts_s * 1000.0,
            "notionnel_usd": 30000.0}


def test_une_grappe_JAMAIS_franchie_ne_produit_AUCUN_evenement():
    """Le coeur de l'artefact : niveau a 59 500, marche a 63 800, prix ne descend jamais.
    L'ancien code aurait 'gagne' ~700 bps ; le nouveau dit : rien ne s'est passe."""
    marks = {"BTC": [(t, 63800.0) for t in range(0, 7200, 60)]}
    evs = evenements_declenches([_grappe(0, 59500.0)], marks)
    assert evs == []


def test_le_franchissement_cree_l_evenement_avec_entree_AU_MARK_pas_au_niveau():
    marks = {"BTC": [(0, 63800.0), (600, 60000.0), (1200, 59400.0), (1800, 60500.0)]}
    evs = evenements_declenches([_grappe(0, 59500.0)], marks, tolerance_bps=5.0)
    assert len(evs) == 1
    assert evs[0]["prix"] == 59400.0, "l'entree est le MARK du franchissement (prix reel)"
    assert evs[0]["niveau_grappe"] == 59500.0 and evs[0]["declenchee"] is True


def test_la_meme_grappe_rephotographiee_54_fois_ne_compte_qu_UNE_fois():
    marks = {"BTC": [(0, 63800.0), (600, 59400.0), (1200, 59300.0)]}
    grappes = [_grappe(i * 10, 59500.0 + i) for i in range(54)]   # derive de quelques $
    evs = evenements_declenches(grappes, marks)
    assert len(evs) == 1, "54 snapshots de la meme grappe = 1 evenement, pas 54"


def test_deux_purges_au_MEME_niveau_mais_SEPAREES_dans_le_temps_sont_DEUX():
    """🔴 22/07 — L'EXCÈS INVERSE, corrigé. Sur données réelles, 286 snapshots (une zone BTC
    re-photographiée) s'effondraient en 1 SEUL événement : la clé de dedup n'avait pas de temps.
    Deux liquidations au même niveau mais séparées de plus d'une fenêtre sont DEUX événements —
    chacune exige toujours un franchissement de mark réel."""
    W = 6 * 3600.0
    # même niveau 59 500, deux purges a t=0 et a t=2W (bien separees), chacune franchie.
    marks = {"BTC": [(0, 63800.0), (600, 59400.0),
                     (2 * W, 63800.0), (2 * W + 600, 59400.0)]}
    grappes = [_grappe(0, 59500.0), _grappe(2 * W, 59500.0)]
    evs = evenements_declenches(grappes, marks)
    assert len(evs) == 2, "deux purges distinctes dans le temps = deux evenements"


def test_le_sens_BUY_franchit_vers_le_HAUT():
    marks = {"ETH": [(0, 3000.0), (600, 3220.0)]}
    evs = evenements_declenches([_grappe(0, 3200.0, coin="ETH", sens="BUY")], marks)
    assert len(evs) == 1 and evs[0]["prix"] == 3220.0
