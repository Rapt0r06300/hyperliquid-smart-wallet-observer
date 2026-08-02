"""[LANCEUR item 2/5] Collecteur dYdX live auto-démarré — prouvé sans réseau (WS + pilote injectés).
Souscriptions bornées (budget WS), reprise+start+stop+heartbeat, présence dans REGISTRE/HARVEST/sources,
et injection du marché depuis l'id du canal.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import collecter_dydx_live as CDL  # noqa: E402


class _FakeWs:
    def __init__(self):
        self.subs = []
        self.started = self.stopped = False

    def subscribe_markets(self):
        self.subs.append(("markets",))

    def subscribe_trades(self, m):
        self.subs.append(("trades", m))

    def subscribe_orderbook(self, m):
        self.subs.append(("book", m))

    def subscribe_subaccount(self, a, n=0):
        self.subs.append(("sub", a, n))

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FakePilote:
    def __init__(self):
        self.stats = SimpleNamespace(messages=0, elements_persistes=0, gaps=0)
        self.reprises = self.battements = 0

    def reprendre(self):
        self.reprises += 1
        return {"marches": 3}

    def battre(self, n=0, ts=None):
        self.battements += 1


def test_plan_souscription_borne_le_budget_ws():
    ws = _FakeWs()
    r = CDL.plan_souscription(ws, marches=["BTC-USD", "ETH-USD", "SOL-USD", "A", "B", "C"],
                              subaccounts=[("dydx1abc", 0)], max_marches=3)
    assert r["marches_trades_book"] == 3 and r["subaccounts"] == 1
    assert ("markets",) in ws.subs and ("trades", "BTC-USD") in ws.subs and ("book", "SOL-USD") in ws.subs
    assert ("trades", "A") not in ws.subs                         # au-delà du cap WS


def test_executer_reprise_souscrit_start_stop_heartbeat():
    ws, pilote = _FakeWs(), _FakePilote()
    clock = {"t": 0.0}
    r = CDL.executer(pilote=pilote, ws=ws, marches=["BTC-USD"], subaccounts=[("dydx1abc", 0)],
                     duree_s=25, horloge=lambda: clock["t"],
                     dormir=lambda s: clock.__setitem__("t", clock["t"] + s), heartbeat_intervalle_s=10.0)
    assert pilote.reprises == 1 and ws.started and ws.stopped
    assert pilote.battements >= 2 and r["souscriptions"]["marches_trades_book"] == 1


def test_dydx_live_dans_registre_harvest_et_sources():
    from hl_observer.ops import superviseur_collecteurs as SC
    from hl_observer.ops.preuve_de_vie import SOURCES_HARVEST
    assert "dydx-live" in {c["nom"] for c in SC.REGISTRE} and "dydx-live" in SC.COLLECTEURS_HARVEST
    src = next((s for s in SOURCES_HARVEST if s.nom == "dydx-live"), None)
    assert src is not None and src.obligatoire is False           # secondaire : ne bloque pas HL


def test_flux_live_injecte_le_marche_depuis_id():
    from hyper_smart_observer.dydx_v4.flux_live import PiloteFluxDydx
    vus = []

    class _Idx:
        def process_ws_message(self, ch, mt, data, net):
            vus.append(data)
            return 1

    pilote = PiloteFluxDydx(_Idx(), network="mainnet")
    pilote.on_message(SimpleNamespace(channel="v4_trades", type="channel_data", id="BTC-USD",
                                      data={"trades": [{"id": "t1"}]}))
    assert vus[0].get("id") == "BTC-USD"                          # marché injecté depuis WsMessage.id
