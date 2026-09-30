"""[CABLAGE étage C] cross_venue_stage : hedge cross-venue seulement si edge mesuré au-dessus du seuil."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.cross_venue_stage import intent_hedge   # noqa: E402


def test_hedge_emis_si_edge_suffisant():
    r = intent_hedge(coin="BTC", notional_copie_signe=600.0, edge_cross_venue_bps=5.0)
    assert r["hedge"]["montant_signe"] == -600.0 and r["hedge"]["venue"] == "BINANCE"
    assert r["hedge"]["coin"] == "BTC" and r["hedge"]["type"] == "ARB_HEDGE"


def test_pas_de_hedge_sous_seuil():
    r = intent_hedge(coin="BTC", notional_copie_signe=600.0, edge_cross_venue_bps=0.5, seuil_edge_bps=1.0)
    assert r["hedge"] is None and r["raison"] == "EDGE_SOUS_SEUIL"


def test_pas_de_hedge_sans_edge_mesure():
    r = intent_hedge(coin="BTC", notional_copie_signe=600.0, edge_cross_venue_bps=None)
    assert r["hedge"] is None and r["raison"] == "DONNEE_INSUFFISANTE"


def test_pas_de_hedge_sans_coin():
    r = intent_hedge(coin="", notional_copie_signe=600.0, edge_cross_venue_bps=5.0)
    assert r["hedge"] is None and r["raison"] == "COIN_MANQUANT"
