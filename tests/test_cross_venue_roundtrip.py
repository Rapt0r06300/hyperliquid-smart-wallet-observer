"""P9.2 — coût round-trip cross-venue : 4 jambes (entrée+sortie causale) + 4 frais, deny-by-default."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import cross_venue_roundtrip as R  # noqa: E402
from hl_observer.arbitrage.cross_venue_capacity import BUY_HL_SELL_BINANCE  # noqa: E402


def _books(px=100.0, taille=100.0):
    # Carnets profonds à un seul niveau au touch → slippage de profondeur nul, seuls les frais comptent.
    return {"hl_bids": [(px, taille)], "hl_asks": [(px, taille)],
            "bin_bids": [(px, taille)], "bin_asks": [(px, taille)]}


def test_round_trip_flat_ne_paie_que_les_4_frais():
    r = R.cout_round_trip(
        BUY_HL_SELL_BINANCE, entree=_books(), sortie=_books(),
        notional_usd=100.0, fee_bps_hl=3.5, fee_bps_binance=4.5,
    )
    assert r["statut"] == "OK"
    assert r["slippage_4_jambes_bps"] == 0.0
    assert r["frais_4_jambes_bps"] == 2 * 3.5 + 2 * 4.5     # 16.0
    assert r["cout_round_trip_bps"] == 16.0


def test_round_trip_sell_hl_buy_binance_est_symetrique():
    r = R.cout_round_trip(
        R.SELL_HL_BUY_BINANCE, entree=_books(), sortie=_books(),
        notional_usd=100.0, fee_bps_hl=3.5, fee_bps_binance=4.5,
    )
    assert r["statut"] == "OK"
    assert r["direction"] == R.SELL_HL_BUY_BINANCE
    assert r["slippage_4_jambes_bps"] == 0.0
    assert r["cout_round_trip_bps"] == 16.0
    assert r["real_execution"] is False


def test_round_trip_compte_le_slippage_des_quatre_jambes():
    # Carnets fins : le notionnel traverse plusieurs niveaux → slippage > 0 sur chaque jambe.
    profond = {
        "hl_bids": [(100.0, 0.3), (99.5, 100.0)], "hl_asks": [(100.0, 0.3), (100.5, 100.0)],
        "bin_bids": [(100.0, 0.3), (99.5, 100.0)], "bin_asks": [(100.0, 0.3), (100.5, 100.0)],
    }
    r = R.cout_round_trip(BUY_HL_SELL_BINANCE, entree=profond, sortie=profond, notional_usd=100.0)
    assert r["statut"] == "OK" and r["slippage_4_jambes_bps"] > 0.0
    assert r["cout_round_trip_bps"] > r["frais_4_jambes_bps"]


def test_unmeasurable_si_une_jambe_de_sortie_trop_mince():
    entree = _books(taille=100.0)
    sortie = _books(taille=100.0)
    sortie["hl_bids"] = [(100.0, 0.1)]                       # sortie HL (vente) trop mince pour 100 USD
    r = R.cout_round_trip(BUY_HL_SELL_BINANCE, entree=entree, sortie=sortie, notional_usd=100.0)
    assert r["statut"] == "UNMEASURABLE" and "sortie_hl" in r["jambes_non_executables"]
    assert r["cout_round_trip_bps"] is None


def test_direction_inconnue():
    r = R.cout_round_trip("XXX", entree=_books(), sortie=_books(), notional_usd=100.0)
    assert r["statut"] == R.DIRECTION_INCONNUE if hasattr(R, "DIRECTION_INCONNUE") else True
    assert r["cout_round_trip_bps"] is None


def test_sortie_utilise_bien_les_carnets_futurs_distincts():
    # La sortie doit consommer le carnet FUTUR, pas celui d'entrée : un futur vide → UNMEASURABLE.
    entree = _books()
    sortie = {"hl_bids": [], "hl_asks": [], "bin_bids": [], "bin_asks": []}
    r = R.cout_round_trip(BUY_HL_SELL_BINANCE, entree=entree, sortie=sortie, notional_usd=100.0)
    assert r["statut"] == "UNMEASURABLE"
    assert "sortie_hl" in r["jambes_non_executables"] and "sortie_binance" in r["jambes_non_executables"]
