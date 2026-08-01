"""[CABLAGE intégration] CHEMIN RÉEL de bout en bout sur un replay :

    live/replay → Copy → (netting | cross-venue 2 jambes) → risk → PaperEngine(fills) → ledger → PnL

Prouve : netting de 2 leaders → 1 ordre ; mark-to-market ; carnet croisé rejeté (NO_TRADE) ; fermeture ;
exécution PAPER des DEUX jambes cross-venue (positions COIN@VENUE distinctes, aucun double comptage) ; PnL
RÉCONCILIÉ ; ZÉRO ordre réel (uniquement PaperLedger). 0 réseau.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.pipeline import MegaCablage   # noqa: E402
from hl_observer.simulation.paper_ledger import PaperLedger   # noqa: E402

T = 1_700_000_000_000
LEADERS = {"A": 100000.0, "B": 100000.0, "C": 100000.0}
BOOK_60 = {"asks": [(60010.0, 5.0), (60020.0, 5.0)], "bids": [(59990.0, 5.0), (59980.0, 5.0)]}
BOOK_61 = {"asks": [(61010.0, 5.0), (61020.0, 5.0)], "bids": [(60990.0, 5.0), (60980.0, 5.0)]}


def test_chemin_reel_netting_mark_fermeture_cross_venue_reconcilie():
    p = MegaCablage(notre_equity=1000.0, notional_max=500.0, fee_bps=4.5)

    # --- Tick 1 : deux leaders ACHÈTENT BTC dans le même tick -> NETTÉS -> une seule ouverture LONG.
    t1 = p.traiter_tick([
        {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.4, "signe": 1, "ts_ms": T, "vault": "A", "book": BOOK_60},
        {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.4, "signe": 1, "ts_ms": T, "vault": "B", "book": BOOK_60},
    ], leader_equity_par_vault=LEADERS)
    assert t1["n_candidats"] == 1
    assert any(f["action"] == "OPEN" for f in t1["fills"] if f.get("execute"))
    assert p.executeur._side["BTC"] == "LONG"

    # --- Tick 2 : mark favorable -> unrealized > 0.
    p.executeur.marquer({"BTC": 61000.0}, ts_ms=T + 1000)
    assert p.executeur.pnl()["unrealized"] > 0

    # --- Tick 3 : carnet ETH CROISÉ rejeté (NO_TRADE) ; leader A VEND BTC -> fermeture.
    t3 = p.traiter_tick([
        {"coin": "ETH", "px": 3000.0, "sz": 1.0, "signe": 1, "ts_ms": T + 2000, "vault": "A",
         "book": {"bids": [(3010.0, 2.0)], "asks": [(3000.0, 2.0)]}},
        {"coin": "BTC", "px": 61000.0, "mid": 61000.0, "sz": 0.8, "signe": -1, "ts_ms": T + 2000, "vault": "A",
         "book": BOOK_61},
    ], leader_equity_par_vault=LEADERS)
    assert any(str(r["raison"]).startswith("CARNET_") and r["coin"] == "ETH" for r in t3["rejets"])
    assert any(f.get("action") == "REDUCE_OR_CLOSE" for f in t3["fills"])
    assert p.executeur._side["BTC"] is None

    # --- Tick 4 : opportunité cross-venue COMPLETE -> les DEUX jambes exécutées en paper (HL + BINANCE).
    t4 = p.traiter_tick([
        {"coin": "BTC", "px": 61000.0, "mid": 61000.0, "sz": 0.5, "signe": 1, "ts_ms": T + 3000, "vault": "C",
         "book": {"asks": [(61000.0, 10.0)], "bids": [(60990.0, 10.0)]},
         "cross_venue": {"edge_bps": 12.0, "venue_hedge": "BINANCE",
                         "carnet_hedge": {"bids": [(61090.0, 10.0)], "asks": [(61100.0, 10.0)]},
                         "carnet_unwind": {"bids": [(60940.0, 10.0)], "asks": [(60950.0, 10.0)]},
                         "latences_ms": (10.0, 20.0, 30.0, 40.0, 50.0)}},
    ], leader_equity_par_vault=LEADERS)
    cv = t4["cross_venue"][0]
    assert cv["execute"] is True and cv["action"] == "CROSS_VENUE_2_JAMBES" and cv["positions_ledger"] >= 2
    coins = {pos.coin for pos in p.executeur.ledger.positions.values()}
    assert "BTC@HYPERLIQUID" in coins and "BTC@BINANCE" in coins   # deux jambes bookées, pas tracees

    # --- Vérité du PnL : le ledger unique se réconcilie ; de vrais coûts ont été facturés ; 0 ordre réel.
    resume = p.resume()
    assert resume["pnl"]["reconcilie"] is True and resume["pnl"]["fees"] > 0
    assert resume["cross_venue_executes"] == 1 and resume["fills_executes"] >= 2
    assert isinstance(p.executeur.ledger, PaperLedger)
    assert resume["snapshot"]["session_id"].startswith("paper:")


def test_replay_groupe_par_tick_reconcilie():
    p = MegaCablage(notre_equity=1000.0, notional_max=500.0)
    flux = [
        {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.3, "signe": 1, "ts_ms": T, "vault": "A", "book": BOOK_60},
        {"coin": "BTC", "px": 61000.0, "mid": 61000.0, "sz": 0.3, "signe": -1, "ts_ms": T + 1000, "vault": "A", "book": BOOK_61},
    ]
    resume = p.traiter_replay(flux, leader_equity_par_vault=LEADERS)
    assert resume["ticks"] == 2 and resume["pnl"]["reconcilie"] is True
