"""[CROSS-VENUE #2] resulting-price-for-amount : VWAP réel par montant, jamais seulement best bid/ask."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import resulting_price_ladder as RL   # noqa: E402


def test_price_for_amount_walk_book_et_slippage_croissant():
    asks = [{"price": 100.0, "size": 1.0}, {"price": 101.0, "size": 1.0}, {"price": 102.0, "size": 2.0}]
    r = RL.resulting_price_for_amount(asks, sens="ACHAT", montants=[10.0, 100.0, 150.0, 10_000.0])
    assert r["best"] == 100.0
    lad = {row["montant_usd"]: row for row in r["ladder"]}
    assert lad[10.0]["prix_moyen"] == 100.0 and lad[10.0]["slippage_bps"] == 0.0   # petit ordre = top-of-book
    # $150 traverse 2 niveaux -> VWAP > best (JAMAIS juste le best ask)
    assert lad[150.0]["prix_moyen"] > 100.0 and lad[150.0]["slippage_bps"] > 0.0
    # slippage croît avec la taille
    assert lad[150.0]["slippage_bps"] > lad[100.0]["slippage_bps"]
    # au-delà de la profondeur visible : partial, jamais extrapolé
    assert lad[10_000.0]["partial"] is True


def test_price_for_amount_vente_slippage_est_un_cout():
    bids = [{"price": 100.0, "size": 1.0}, {"price": 99.0, "size": 5.0}]
    r = RL.resulting_price_for_amount(bids, sens="VENTE", montants=[50.0, 300.0])
    lad = {row["montant_usd"]: row for row in r["ladder"]}
    assert r["best"] == 100.0                                   # meilleur bid en tête même si l'entrée n'est pas triée
    assert lad[300.0]["prix_moyen"] < 100.0 and lad[300.0]["slippage_bps"] > 0.0   # vendre en profondeur = encaisser moins
