"""[DATA-049..061 / AUD-269] Adaptateur OKX v5 (perp SWAP) — OFFLINE : normalisation du schema PUBLIC
documente v5 (books/books5/bbo-tbt, trades, funding-rate, open-interest, mark/index, liquidation,
instruments) vers le schema canonique, sequencage via seqId/prevSeqId, reconnexion sur service-upgrade.
Le pull LIVE reste derriere une frontiere REQUIRES_NETWORK (jamais de faux succes). Schema conforme a la
doc publique OKX v5. stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence

from ._canon import (ClientLiveBase, DetecteurSequence, OFFLINE_READY, REQUIRES_NETWORK,
                     ligne, nbbo, niveaux, to_float)

VENUE = "okx"
ENDPOINTS = {
    "rest_base": "https://www.okx.com",
    "ws_public": "wss://ws.okx.com:8443/ws/v5/public",
    "channels": ("books", "books5", "bbo-tbt", "books-l2-tbt", "trades",
                 "funding-rate", "open-interest", "mark-price", "index-tickers",
                 "liquidation-orders", "instruments"),
}


def _instId(msg: Mapping):
    arg = msg.get("arg") or {}
    return arg.get("instId")


def normalize_books(msg: Mapping) -> dict:
    """books/books5 — action snapshot|update. data[0] porte seqId/prevSeqId (DATA-053) et checksum.
    OKX niveaux = [prix, taille, liqOrders, numOrders] : on ne garde que prix/taille."""
    data = (msg.get("data") or [{}])[0]
    return {"venue": VENUE, "symbole": _instId(msg), "action": msg.get("action"),
            "seqId": data.get("seqId"), "prevSeqId": data.get("prevSeqId"),
            "checksum": data.get("checksum"), "ts": data.get("ts"),
            "bids": niveaux(data.get("bids")), "asks": niveaux(data.get("asks"))}


def normalize_trade(t: Mapping) -> dict:
    """trades data : instId, tradeId, px, sz, side (buy/sell taker), ts."""
    return ligne(ts=t.get("ts"), venue=VENUE, symbole=t.get("instId"), type_="trade",
                 prix=t.get("px"), taille=t.get("sz"), side=t.get("side"))


def normalize_funding(f: Mapping) -> dict:
    """funding-rate data : instId, fundingRate, nextFundingTime, fundingTime."""
    return {"venue": VENUE, "symbole": f.get("instId"), "funding": to_float(f.get("fundingRate")),
            "ts": f.get("fundingTime"), "next_funding": f.get("nextFundingTime")}


def normalize_oi(o: Mapping) -> dict:
    """open-interest data : instId, oi (contrats), oiCcy (en devise), ts (AUD-345)."""
    return {"venue": VENUE, "symbole": o.get("instId"), "oi_contrats": to_float(o.get("oi")),
            "oi_devise": to_float(o.get("oiCcy")), "ts": o.get("ts")}


def normalize_mark(m: Mapping) -> dict:
    """mark-price data : instId, markPx, ts."""
    return {"venue": VENUE, "symbole": m.get("instId"), "mark": to_float(m.get("markPx")), "ts": m.get("ts")}


def normalize_liquidation(l: Mapping) -> dict:
    """liquidation-orders : details[] {side, sz, bkPx/px, ts}. side = sens de l'ordre force (AUD-346)."""
    d = l
    if l.get("details"):
        d = (l.get("details") or [{}])[0]
    return ligne(ts=d.get("ts"), venue=VENUE, symbole=l.get("instId") or d.get("instId"),
                 type_="liquidation", prix=d.get("bkPx") or d.get("px"), taille=d.get("sz"),
                 side=d.get("side"))


def normalize_instrument(i: Mapping) -> dict:
    """instruments data : instId, state (live/suspend/expired), ctVal, ctMult (DATA-059 / AUD-342)."""
    return {"venue": VENUE, "symbole": i.get("instId"), "etat": i.get("state"),
            "ct_val": to_float(i.get("ctVal")), "ct_mult": to_float(i.get("ctMult")),
            "type_contrat": i.get("ctType")}


def best_bid_ask(book: Mapping) -> dict:
    """bbo-tbt / books5 -> meilleur bid/ask (DATA-050/051)."""
    d = nbbo(book.get("bids"), book.get("asks"))
    d.update({"venue": VENUE, "symbole": book.get("symbole")})
    return d


def reconnect_sur_service_upgrade(evt: Mapping) -> dict:
    """DATA-060 : sur un evenement de type service-upgrade / connexion fermee, il FAUT re-souscrire et
    re-synchroniser (resync=True). Aucun autre evenement ne declenche de resync silencieux."""
    ev = str(evt.get("event") or evt.get("type") or "").lower()
    besoin = ("service-upgrade" in ev) or ("close" in ev) or (str(evt.get("code")) in ("60004", "60006"))
    return {"resync": bool(besoin), "re_souscrire": bool(besoin), "event": ev or None}


def mapping_silver() -> dict:
    return {"ts": "ts", "symbole": "instId", "prix": "px", "taille": "sz", "side": "side"}


def replay(msgs: Sequence[Mapping]) -> list:
    return [normalize_trade(m) for m in msgs]


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "funding", "oi", "liquidations"),
            "adaptateur": OFFLINE_READY, "pull_live": REQUIRES_NETWORK}


def appliquer_flux_books(messages: Sequence[Mapping]) -> dict:
    """Applique snapshot->update via seqId/prevSeqId. prevSeqId != dernier seqId -> resync (DATA-053)."""
    det = DetecteurSequence()
    resyncs = []
    applique = 0
    for m in messages:
        b = normalize_books(m)
        if b["action"] == "snapshot":
            det.snapshot(b["seqId"])
            applique += 1
        else:
            r = det.delta(b["seqId"], b["prevSeqId"])
            if r["resync"]:
                resyncs.append({"seqId": b["seqId"], "raison": r["raison"]})
            else:
                applique += 1
    return {"applique": applique, "resyncs": resyncs, "synchronise": det.synchronise}


class LiveClientOKX(ClientLiveBase):
    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def souscrire_books(self, instId, canal="books"):
        self._refuser("%s %s" % (canal, instId))

    def souscrire_trades(self, instId):
        self._refuser("trades %s" % instId)
