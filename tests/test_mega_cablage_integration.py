"""[CABLAGE intégration] CHEMIN RÉEL de bout en bout sur un replay :

    live/replay → Copy/Cross-Venue → netting/routing → PaperEngine (fills) → ledger → PnL

Ce test prouve que les pépites 201-300, composées via mega_cablage, produisent de VRAIS fills et un PnL
RÉCONCILIÉ, avec des NO_TRADE honnêtes (carnet croisé rejeté), du netting (2 leaders → 1 ordre), un hedge
cross-venue tracé mais non exécuté en paper, et ZÉRO ordre réel (uniquement PaperLedger). 0 réseau.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.pipeline import MegaCablage   # noqa: E402
from hl_observer.simulation.paper_ledger import PaperLedger   # noqa: E402

T = 1_700_000_000_000
LEADERS = {"A": 100000.0, "B": 100000.0}
BOOK_60 = {"asks": [(60010.0, 5.0), (60020.0, 5.0)], "bids": [(59990.0, 5.0), (59980.0, 5.0)]}
BOOK_61 = {"asks": [(61010.0, 5.0), (61020.0, 5.0)], "bids": [(60990.0, 5.0), (60980.0, 5.0)]}


def _pipeline():
    return MegaCablage(notre_equity=1000.0, notional_max=500.0, fee_bps=4.5)


def test_chemin_reel_ouverture_nettee_mark_fermeture_pnl_reconcilie():
    p = _pipeline()

    # --- Tick 1 : deux leaders ACHÈTENT BTC dans le même tick -> NETTÉS -> une seule ouverture LONG.
    #     Le 2e leader porte un edge cross-venue -> hedge BINANCE émis, tracé mais non exécuté en paper.
    t1 = p.traiter_tick([
        {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.4, "signe": 1, "ts_ms": T, "vault": "A", "book": BOOK_60},
        {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.4, "signe": 1, "ts_ms": T, "vault": "B",
         "book": BOOK_60, "cross_venue_edge_bps": 5.0},
    ], leader_equity_par_vault=LEADERS)
    hl_fills = [f for f in t1["fills"] if f.get("execute")]
    assert t1["n_candidats"] == 2                       # HYPERLIQUID/BTC (nette) + BINANCE/BTC (hedge)
    assert any(f["action"] == "OPEN" for f in hl_fills)
    assert any(f.get("raison") == "VENUE_NON_PAPER" for f in t1["fills"])   # hedge cross-venue non paper ici
    assert p.executeur._side["BTC"] == "LONG"

    # --- Tick 2 : mark-to-market favorable (opération ledger réelle, pas un trade) -> unrealized > 0.
    p.executeur.marquer({"BTC": 61000.0}, ts_ms=T + 1000)
    assert p.executeur.pnl()["unrealized"] > 0

    # --- Tick 3 : un événement au carnet CROISÉ (ETH) est rejeté (NO_TRADE) ; le leader A VEND BTC -> fermeture.
    t3 = p.traiter_tick([
        {"coin": "ETH", "px": 3000.0, "sz": 1.0, "signe": 1, "ts_ms": T + 2000, "vault": "A",
         "book": {"bids": [(3010.0, 2.0)], "asks": [(3000.0, 2.0)]}},          # croisé -> quarantaine
        {"coin": "BTC", "px": 61000.0, "mid": 61000.0, "sz": 0.8, "signe": -1, "ts_ms": T + 2000, "vault": "A",
         "book": BOOK_61},
    ], leader_equity_par_vault=LEADERS)
    assert any(str(r["raison"]).startswith("CARNET_") and r["coin"] == "ETH" for r in t3["rejets"])
    assert any(f.get("action") == "REDUCE_OR_CLOSE" for f in t3["fills"])
    assert p.executeur._side["BTC"] is None            # position refermée

    # --- Vérité du PnL : le ledger se réconcilie (equity = start + realized + unrealized − fees + funding).
    resume = p.resume()
    assert resume["pnl"]["reconcilie"] is True
    assert resume["pnl"]["fees"] > 0                   # de VRAIS coûts ont été facturés (aller-retour)
    assert isinstance(p.executeur.ledger, PaperLedger) # 0 ordre réel : uniquement le PaperLedger
    assert resume["snapshot"]["session_id"].startswith("paper:")


def test_replay_groupe_par_tick_reconcilie():
    p = _pipeline()
    flux = [
        {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.3, "signe": 1, "ts_ms": T, "vault": "A", "book": BOOK_60},
        {"coin": "BTC", "px": 61000.0, "mid": 61000.0, "sz": 0.3, "signe": -1, "ts_ms": T + 1000, "vault": "A", "book": BOOK_61},
    ]
    resume = p.traiter_replay(flux, leader_equity_par_vault=LEADERS)
    assert resume["ticks"] == 2 and resume["pnl"]["reconcilie"] is True
