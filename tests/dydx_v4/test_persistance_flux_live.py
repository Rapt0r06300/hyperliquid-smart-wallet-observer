"""[LANCEUR item 5] dYdX LEGACY — persistance des flux (trades/positions/subaccounts/orderbooks) et
branchement WS -> stockage (le chaînon manquant). Prouvé sans réseau (SQLite temporaire + normaliseurs
réels + indexer factice pour flux_live). dYdX réel, PAS la simu Hyperliquid ; 0 ordre.
"""
from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.flux_live import PiloteFluxDydx
from hyper_smart_observer.dydx_v4.indexer import DydxIndexer
from hyper_smart_observer.dydx_v4.models import (
    NormalizedPosition,
    NormalizedSubaccount,
    NormalizedTrade,
    OrderSide,
    PositionSide,
)
from hyper_smart_observer.dydx_v4.storage import DydxStorage

ISO = "2026-08-01T00:00:00.000Z"


def _storage(tmp_path):
    return DydxStorage(db_path=str(tmp_path / "dydx.sqlite3"), network="testnet")


def _count(st, table):
    with st._conn() as c:
        return c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


# ── Storage : les writers qui manquaient ────────────────────────────────────────────────────────────
def test_insert_trade_dedup(tmp_path):
    st = _storage(tmp_path)
    tr = NormalizedTrade("t1", "BTC-USD", OrderSide.BUY, 1.5, 60000.0, 1_700_000_000_000, "LIMIT", {"id": "t1"})
    assert st.insert_trade(tr) is True and st.insert_trade(tr) is False   # 2e = dupliqué
    assert _count(st, "dydx_trades") == 1
    assert st.get_latest_trade_ms("BTC-USD") == 1_700_000_000_000


def test_upsert_position_et_subaccount_idempotents(tmp_path):
    st = _storage(tmp_path)
    pos = NormalizedPosition("dydx1abc", 0, "BTC-USD", PositionSide.LONG, 2.0, 59000.0, 60000.0,
                             10.0, 0.0, 0.0, 1.0, 2.0, None, 1_700_000_000_000, 1_700_000_000_100, {})
    st.upsert_position(pos)
    st.upsert_position(pos)                                              # upsert -> toujours 1 ligne
    sub = NormalizedSubaccount("dydx1abc", 0, 10000.0, 8000.0, 0.2, 2.0, 1_700_000_000_000, {})
    st.upsert_subaccount(sub)
    st.upsert_subaccount(sub)
    assert _count(st, "dydx_positions") == 1 and _count(st, "dydx_subaccounts") == 1


def test_insert_orderbook_snapshot(tmp_path):
    st = _storage(tmp_path)
    assert st.insert_orderbook("BTC-USD", [[59990.0, 3.0]], [[60010.0, 2.0]],
                               received_at_ms=1_700_000_000_000) is True
    with st._conn() as c:
        row = c.execute("SELECT best_bid, best_ask, n_bids, n_asks FROM dydx_orderbooks").fetchone()
    assert row["best_bid"] == 59990.0 and row["best_ask"] == 60010.0 and row["n_bids"] == 1


# ── process_ws_message : normalisé PUIS PERSISTÉ (avant : jeté) ───────────────────────────────────────
def test_process_ws_trades_persiste(tmp_path):
    idx = DydxIndexer(config=SimpleNamespace(), rest_client=None, storage=_storage(tmp_path))
    data = {"id": "BTC-USD", "trades": [{"id": "t1", "side": "BUY", "size": "1", "price": "60000",
                                         "createdAt": ISO, "type": "LIMIT"}]}
    n = idx.process_ws_message("v4_trades", "channel_data", data, "testnet")
    assert n == 1 and _count(idx.storage, "dydx_trades") == 1 and idx.stats.trades_ingested == 1


def test_process_ws_subaccounts_persiste_fills_positions_subaccount(tmp_path):
    idx = DydxIndexer(config=SimpleNamespace(), rest_client=None, storage=_storage(tmp_path))
    data = {"contents": {
        "fills": [{"id": "f1", "address": "dydx1abc", "subaccountNumber": 0, "market": "BTC-USD",
                   "side": "BUY", "size": "1", "price": "60000", "fee": "0.5", "liquidity": "TAKER",
                   "createdAt": ISO}],
        "positions": [{"address": "dydx1abc", "subaccountNumber": 0, "market": "BTC-USD", "side": "LONG",
                       "size": "2", "entryPrice": "59000", "status": "OPEN", "createdAt": ISO,
                       "updatedAt": ISO}],
        "subaccount": {"address": "dydx1abc", "subaccountNumber": 0, "equity": "10000",
                       "freeCollateral": "8000", "leverage": "2", "updatedAt": ISO}}}
    idx.process_ws_message("v4_subaccounts", "channel_data", data, "testnet")
    assert _count(idx.storage, "dydx_fills") == 1
    assert _count(idx.storage, "dydx_positions") == 1
    assert _count(idx.storage, "dydx_subaccounts") == 1


def test_process_ws_orderbook_persiste(tmp_path):
    idx = DydxIndexer(config=SimpleNamespace(), rest_client=None, storage=_storage(tmp_path))
    data = {"id": "BTC-USD", "orderbook": {"market_id": "BTC-USD",
                                           "bids": [[59990.0, 3.0]], "asks": [[60010.0, 2.0]]}}
    n = idx.process_ws_message("v4_orderbook", "channel_data", data, "testnet")
    assert n == 1 and _count(idx.storage, "dydx_orderbooks") == 1 and idx.stats.orderbooks_ingested == 1


# ── flux_live : le branchement WS -> persistance + heartbeat + gap + reprise ──────────────────────────
class _FauxIndexer:
    def __init__(self):
        self.messages = []
        self.gaps = []
        self.backfills = []

    def process_ws_message(self, ch, mt, data, net):
        self.messages.append((ch, mt, net))
        return 3

    def gap_recovery(self, addr, num):
        self.gaps.append((addr, num))
        return 2

    def backfill_markets(self):
        return 5

    def backfill_subaccount(self, addr, num):
        self.backfills.append(("sub", addr, num))
        return True

    def backfill_fills(self, addr, num):
        self.backfills.append(("fills", addr, num))
        return 7


def test_flux_live_on_message_persiste_et_bat_le_coeur():
    idx = _FauxIndexer()
    battements = []
    pilote = PiloteFluxDydx(idx, network="testnet", subaccounts=[("dydx1abc", 0)],
                            heartbeat=lambda nom, n, ex: battements.append((nom, n, ex)))
    msg = SimpleNamespace(channel="v4_trades", type="channel_data",
                          data={"trades": [{"createdAt": ISO}]})
    n = pilote.on_message(msg)
    assert n == 3 and idx.messages == [("v4_trades", "channel_data", "testnet")]
    assert battements and battements[0][1] == 3 and pilote.stats.elements_persistes == 3


def test_flux_live_on_gap_rattrape_les_subaccounts_suivis():
    idx = _FauxIndexer()
    pilote = PiloteFluxDydx(idx, network="testnet", subaccounts=[("dydx1abc", 0), ("dydx1xyz", 1)])
    rattrapes = pilote.on_gap("v4_subaccounts", "42")
    assert idx.gaps == [("dydx1abc", 0), ("dydx1xyz", 1)] and rattrapes == 4  # 2 subaccounts x 2 fills


def test_flux_live_reprise_apres_crash_backfill():
    idx = _FauxIndexer()
    pilote = PiloteFluxDydx(idx, network="testnet", subaccounts=[("dydx1abc", 0)])
    r = pilote.reprendre()
    assert r["marches"] == 5 and r["subaccounts"] == 1 and r["fills"] == 7
    assert ("sub", "dydx1abc", 0) in idx.backfills and ("fills", "dydx1abc", 0) in idx.backfills


def test_flux_live_callbacks_sont_les_deux_hooks_ws():
    on_message, on_gap = PiloteFluxDydx(_FauxIndexer(), network="testnet").callbacks()
    assert callable(on_message) and callable(on_gap)
