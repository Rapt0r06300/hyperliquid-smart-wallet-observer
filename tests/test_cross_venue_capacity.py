"""P9.1 — capacité directionnelle cross-venue : bons côtés, jambe contraignante, jamais la somme des bids."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import cross_venue_capacity as C  # noqa: E402


def test_buy_hl_sell_binance_utilise_hl_asks_et_bin_bids():
    r = C.capacite_directionnelle(
        C.BUY_HL_SELL_BINANCE,
        hl_asks=[(100.0, 10.0)],          # 1000 USD (côté acheté sur HL)
        bin_bids=[(99.0, 5.0)],           # 495 USD (côté vendu sur Binance)
        hl_bids=[(99.0, 1000.0)],         # NE DOIT PAS compter
        bin_asks=[(101.0, 1000.0)],       # NE DOIT PAS compter
        notional_cible_usd=100.0,
    )
    assert r["statut"] == "OK"
    assert r["cote_hl"] == "ACHAT" and r["cote_binance"] == "VENTE"
    assert r["capacite_appariee_usd"] == 495.0      # min(1000, 495), PAS une somme de bids
    assert r["jambe_contraignante"] == "BINANCE"


def test_le_mauvais_cote_ne_change_pas_la_capacite():
    # Rendre hl_bids / bin_asks gigantesques ne doit RIEN changer (c'est le cœur du bug corrigé).
    base = dict(hl_asks=[(100.0, 10.0)], bin_bids=[(99.0, 5.0)], notional_cible_usd=100.0)
    petit = C.capacite_directionnelle(C.BUY_HL_SELL_BINANCE, hl_bids=[(1.0, 1.0)], bin_asks=[(1.0, 1.0)], **base)
    enorme = C.capacite_directionnelle(C.BUY_HL_SELL_BINANCE, hl_bids=[(1.0, 1e9)], bin_asks=[(1e9, 1e9)], **base)
    assert petit["capacite_appariee_usd"] == enorme["capacite_appariee_usd"] == 495.0


def test_sell_hl_buy_binance_utilise_hl_bids_et_bin_asks():
    r = C.capacite_directionnelle(
        C.SELL_HL_BUY_BINANCE,
        hl_bids=[(100.0, 3.0)],           # 300 USD (côté vendu sur HL)
        bin_asks=[(101.0, 10.0)],         # 1010 USD (côté acheté sur Binance)
        notional_cible_usd=100.0,
    )
    assert r["cote_hl"] == "VENTE" and r["cote_binance"] == "ACHAT"
    assert r["capacite_appariee_usd"] == 300.0 and r["jambe_contraignante"] == "HL"


def test_capacite_est_le_min_des_deux_jambes():
    r = C.capacite_directionnelle(
        C.BUY_HL_SELL_BINANCE,
        hl_asks=[(100.0, 2.0)],           # 200 USD
        bin_bids=[(100.0, 8.0)],          # 800 USD
        notional_cible_usd=50.0,
    )
    assert r["capacite_appariee_usd"] == 200.0 and r["jambe_contraignante"] == "HL"


def test_executable_a_la_cible_si_les_deux_jambes_absorbent():
    r = C.capacite_directionnelle(
        C.BUY_HL_SELL_BINANCE,
        hl_asks=[(100.0, 10.0)], bin_bids=[(100.0, 10.0)], notional_cible_usd=100.0,
    )
    assert r["executable_a_la_cible"] is True and r["cout_entree_bps"] == 0.0


def test_non_executable_si_une_jambe_trop_mince():
    r = C.capacite_directionnelle(
        C.BUY_HL_SELL_BINANCE,
        hl_asks=[(100.0, 10.0)],          # 1000 USD
        bin_bids=[(99.0, 5.0)],           # 495 USD < cible 600
        notional_cible_usd=600.0,
    )
    assert r["executable_a_la_cible"] is False and r["cout_entree_bps"] is None


def test_direction_inconnue():
    r = C.capacite_directionnelle("N_IMPORTE_QUOI", hl_asks=[(1.0, 1.0)])
    assert r["statut"] == C.DIRECTION_INCONNUE and r["capacite_appariee_usd"] is None
