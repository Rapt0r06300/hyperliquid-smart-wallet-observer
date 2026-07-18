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
