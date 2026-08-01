"""[CABLAGE E2E] MESSAGES BRUTS → PnL FINAL, via le chemin unique consolidé :

    frames bruts HL (userFills/L2) → feed_adapter → MegaCablage → Copy-Vault + cross-venue 2 jambes →
    netting/routing → risk gates → fills paper → PaperLedger → PnL

Couvre dans un seul run : netting (2 leaders → 1 ordre), exécution PAPER des DEUX jambes cross-venue,
missed fill (carnet mince), MORE_DATA (carnet absent), contrôle de risque (plafond notional), PnL réconcilié,
0 ordre réel. Aucune donnée manquante n'est remplacée par une valeur fictive.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.feed_adapter import evenements_depuis_bundles   # noqa: E402
from hl_observer.mega_cablage.pipeline import MegaCablage   # noqa: E402
from hl_observer.mega_cablage.runner import run_mega_cablage, _EquityMap   # noqa: E402

T = 1_700_000_000_000


def _uf(user, coin, px, sz, side, t):
    return {"channel": "userFills", "data": {"isSnapshot": False, "user": user, "fills": [
        {"coin": coin, "px": str(px), "sz": str(sz), "side": side, "time": t,
         "dir": "Open", "hash": "0x0", "startPosition": "0"}]}}


def _l2(coin, t, bid, ask, sz=5.0):
    return {"coin": coin, "time": t,
            "levels": [[{"px": str(bid), "sz": str(sz)}], [{"px": str(ask), "sz": str(sz)}]]}


def _bundles():
    return [
        # Tick T : deux leaders ACHÈTENT BTC (raw userFills + L2) -> NETTÉS -> 1 ouverture LONG.
        {"vault": "A", "userfills_msg": _uf("0xA", "BTC", 60000, 0.4, "B", T), "l2_par_coin": {"BTC": _l2("BTC", T, 59990, 60010)}},
        {"vault": "B", "userfills_msg": _uf("0xB", "BTC", 60000, 0.4, "B", T), "l2_par_coin": {"BTC": _l2("BTC", T, 59990, 60010)}},
        # Tick T+1000 : leader C ACHÈTE ETH avec edge + carnet hedge BINANCE -> DEUX jambes exécutées en paper.
        {"vault": "C", "userfills_msg": _uf("0xC", "ETH", 3000, 0.5, "B", T + 1000),
         "l2_par_coin": {"ETH": _l2("ETH", T + 1000, 2999, 3000, sz=10.0)},
         "l2_hedge_par_coin": {"ETH": _l2("ETH", T + 1000, 3008, 3010, sz=10.0)},
         "edge_cross_venue_par_coin": {"ETH": 26.0}, "venue_hedge": "BINANCE"},
        # Tick T+2000 : leader D ACHÈTE SOL sur carnet MINCE -> MISSED_FILL ; leader E ACHÈTE XRP SANS carnet -> MORE_DATA.
        {"vault": "D", "userfills_msg": _uf("0xD", "SOL", 150, 1.0, "B", T + 2000),
         "l2_par_coin": {"SOL": _l2("SOL", T + 2000, 149.9, 150.1, sz=0.0001)}},
        {"vault": "E", "userfills_msg": _uf("0xE", "XRP", 0.5, 100.0, "B", T + 2000)},   # pas de L2 -> MORE_DATA
        # Tick T+3000 : leader F ACHÈTE BTC en TRÈS GROS -> notional > plafond -> refus de risque.
        {"vault": "F", "userfills_msg": _uf("0xF", "BTC", 60000, 5.0, "B", T + 3000), "l2_par_coin": {"BTC": _l2("BTC", T + 3000, 59990, 60010)}},
    ]


LEADERS = {"A": 100000.0, "B": 100000.0, "C": 100000.0, "D": 100000.0, "E": 100000.0, "F": 100000.0}


def test_e2e_messages_bruts_jusqu_au_pnl():
    evenements = evenements_depuis_bundles(_bundles())     # frames bruts -> feed_adapter -> evenements
    assert len(evenements) == 6                            # 6 fills leader normalisés
    pipe = MegaCablage(notre_equity=1000.0, notional_max=500.0, fee_bps=4.5)
    pipe.traiter_replay(evenements, leader_equity_par_vault=_EquityMap(LEADERS, None))

    fills = [f for t in pipe.trace for f in t["fills"]]
    cvs = [cv for t in pipe.trace for cv in t.get("cross_venue", [])]
    raisons = {f.get("raison") for f in fills}

    # netting : un tick a 1 seul candidat pour 2 leaders BTC, et une ouverture LONG.
    assert any(t["n_candidats"] == 1 and any(f["action"] == "OPEN" for f in t["fills"] if f.get("execute"))
               for t in pipe.trace)
    # cross-venue : les deux jambes exécutées.
    assert any(cv.get("execute") and cv.get("action") == "CROSS_VENUE_2_JAMBES" for cv in cvs)
    coins = {p.coin for p in pipe.executeur.ledger.positions.values()}
    assert "ETH@HYPERLIQUID" in coins and "ETH@BINANCE" in coins and "BTC:LONG" in pipe.executeur.ledger.positions
    # données manquantes -> sentinelles honnêtes (jamais de fill fabriqué).
    assert "MISSED_FILL" in raisons and "MORE_DATA" in raisons and "NOTIONAL_DEPASSE_LIMITE" in raisons
    # PnL réconcilié sur le ledger unique ; de vrais coûts facturés.
    pnl = pipe.executeur.pnl()
    assert pnl["reconcilie"] is True and pnl["fees"] > 0


def test_e2e_runner_meme_chemin_reconcilie():
    # Le runner emprunte EXACTEMENT le même chemin (bundles -> feed_adapter -> traiter_replay).
    r = run_mega_cablage(bundles=_bundles(), notre_equity=1000.0, notional_max=500.0,
                         leader_equity_defaut=100000.0)
    assert r.events_traites == 6 and r.reconcilie is True
    assert r.fills_executes >= 1 and r.cross_venue_executes == 1


def test_e2e_paper_strict_aucun_ordre_reel():
    from hl_observer.simulation.paper_ledger import PaperLedger
    evenements = evenements_depuis_bundles(_bundles())
    pipe = MegaCablage(notre_equity=1000.0, notional_max=500.0)
    pipe.traiter_replay(evenements, leader_equity_par_vault=_EquityMap(LEADERS, None))
    assert isinstance(pipe.executeur.ledger, PaperLedger)
    assert pipe.executeur.ledger.snapshot()["session_id"].startswith("paper:")
    assert pipe.executeur.ledger.verify_event_chain() is True
