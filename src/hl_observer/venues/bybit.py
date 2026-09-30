"""[DATA-036..048 / AUD-268] Adaptateur Bybit v5 (perp lineaire) — OFFLINE : normalisation du schema
PUBLIC documente v5 (orderbook.{1,50,200,500}, publicTrade, tickers, funding, open-interest,
liquidation) vers le schema canonique, snapshot/delta via u/seq + cts (matching-engine ts), NBBO.
Le pull LIVE (REST/WS) reste derriere une frontiere REQUIRES_NETWORK (jamais de faux succes).
Schema conforme a la doc publique Bybit v5 ; validation live = etape reseau (golden packets AUD-371).
stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence

from ._canon import (ClientLiveBase, DetecteurSequence, OFFLINE_READY, REQUIRES_NETWORK,
                     ligne, nbbo, niveaux, to_float)

VENUE = "bybit"
ENDPOINTS = {
    "rest_base": "https://api.bybit.com",
    "ws_public_linear": "wss://stream.bybit.com/v5/public/linear",
    "orderbook_depths": (1, 50, 200, 500),           # DATA-037/038/039/040
    "topics": ("orderbook.{depth}.{sym}", "publicTrade.{sym}", "tickers.{sym}",
               "liquidation.{sym}", "allLiquidation.{sym}"),
    "rest_funding": "/v5/market/funding/history",     # DATA-043
    "rest_oi": "/v5/market/open-interest",             # DATA-044
}


def normalize_orderbook(msg: Mapping) -> dict:
    """orderbook.{depth}.{sym} — type snapshot|delta. Porte data.u (updateId), data.seq et cts
    (matching-engine ts, DATA-046). taille 0 dans un delta = suppression de niveau (DATA-047)."""
    data = msg.get("data") or {}
    return {"venue": VENUE, "symbole": data.get("s"), "type_maj": msg.get("type"),
            "u": data.get("u"), "seq": data.get("seq"), "cts": msg.get("cts"), "ts": msg.get("ts"),
            "bids": niveaux(data.get("b")), "asks": niveaux(data.get("a"))}


def normalize_trade(t: Mapping) -> dict:
    """publicTrade : T=ts(ms), s=symbole, S=Buy/Sell (agressor), v=taille, p=prix."""
    return ligne(ts=t.get("T"), venue=VENUE, symbole=t.get("s"), type_="trade",
                 prix=t.get("p"), taille=t.get("v"), side=t.get("S"))


def normalize_liquidation(l: Mapping) -> dict:
    """liquidation.{sym} : S/side = sens de l'ordre de liquidation (agressor). p/price, v/size, T (AUD-346)."""
    return ligne(ts=l.get("T") or l.get("updatedTime"), venue=VENUE,
                 symbole=l.get("s") or l.get("symbol"), type_="liquidation",
                 prix=l.get("p") or l.get("price"), taille=l.get("v") or l.get("size"),
                 side=l.get("S") or l.get("side"))


def normalize_ticker(tk: Mapping) -> dict:
    """tickers.{sym} : last/mark/index/funding/oi (DATA-042/043/044). oi en CONTRATS (AUD-345)."""
    return {"venue": VENUE, "symbole": tk.get("symbol"),
            "last": to_float(tk.get("lastPrice")), "mark": to_float(tk.get("markPrice")),
            "index": to_float(tk.get("indexPrice")), "funding": to_float(tk.get("fundingRate")),
            "next_funding": tk.get("nextFundingTime"),
            "oi_contrats": to_float(tk.get("openInterest")),
            "oi_valeur": to_float(tk.get("openInterestValue"))}


def normalize_funding(row: Mapping) -> dict:
    """/v5/market/funding/history : fundingRate, fundingRateTimestamp."""
    return {"venue": VENUE, "symbole": row.get("symbol"), "funding": to_float(row.get("fundingRate")),
            "ts": row.get("fundingRateTimestamp")}


def normalize_oi(row: Mapping) -> dict:
    """/v5/market/open-interest : openInterest (contrats), timestamp."""
    return {"venue": VENUE, "symbole": row.get("symbol"),
            "oi_contrats": to_float(row.get("openInterest")), "ts": row.get("timestamp")}


def best_bid_ask(book: Mapping) -> dict:
    """Meilleur bid/ask depuis un book normalise (DATA-037 L1 / DATA-048 NBBO)."""
    d = nbbo(book.get("bids"), book.get("asks"))
    d.update({"venue": VENUE, "symbole": book.get("symbole")})
    return d


def mapping_silver() -> dict:
    """Mapping {canonique: champ_source_trade} pour medallion.to_silver (flux trades)."""
    return {"ts": "T", "symbole": "s", "prix": "p", "taille": "v", "side": "S"}


def replay(msgs: Sequence[Mapping]) -> list:
    """Rejoue une capture brute de trades -> lignes canoniques (offline, deterministe)."""
    return [normalize_trade(m) for m in msgs]


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "funding", "oi", "liquidations"),
            "adaptateur": OFFLINE_READY, "pull_live": REQUIRES_NETWORK}


class LiveClientBybit(ClientLiveBase):
    """Live-gate Bybit : chaque souscription/pull LEVE (jamais de faux succes)."""

    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def souscrire_orderbook(self, symbole, depth=50):
        self._refuser("orderbook.%s.%s" % (depth, symbole))

    def souscrire_trades(self, symbole):
        self._refuser("publicTrade.%s" % symbole)

    def rest_open_interest(self, symbole):
        self._refuser("open-interest %s" % symbole)


def appliquer_flux_orderbook(messages: Sequence[Mapping]) -> dict:
    """Applique une sequence snapshot->deltas via DetecteurSequence : renvoie l'etat + les resync
    detectes. Un delta orphelin ou un trou d'updateId force un resync (n'est jamais masque)."""
    det = DetecteurSequence()
    resyncs = []
    applique = 0
    for m in messages:
        b = normalize_orderbook(m)
        if b["type_maj"] == "snapshot":
            det.snapshot(b["u"])
            applique += 1
        else:
            r = det.delta(b["u"])
            if r["resync"]:
                resyncs.append({"u": b["u"], "raison": r["raison"]})
            else:
                applique += 1
    return {"applique": applique, "resyncs": resyncs, "synchronise": det.synchronise}
