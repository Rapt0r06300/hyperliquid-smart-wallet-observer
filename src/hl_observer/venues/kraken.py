"""[DATA-079..084 / AUD-272] Adaptateur Kraken Futures — OFFLINE : normalisation du schema PUBLIC
documente (book_snapshot/book, trade, ticker) vers le schema canonique, sequencage via seq, open
interest, funding/basis, CVD (cumulative volume delta) et volume de liquidation agrege.
Pull LIVE derriere une frontiere REQUIRES_NETWORK. stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence

from ._canon import (ClientLiveBase, DetecteurSequence, OFFLINE_READY, REQUIRES_NETWORK,
                     ligne, nbbo, norm_side, to_float)

VENUE = "kraken"
ENDPOINTS = {
    "ws": "wss://futures.kraken.com/ws/v1",
    "feeds": ("book_snapshot", "book", "trade", "ticker"),
}


def _niveaux_dict(rows: Sequence[Mapping]) -> list:
    """Kraken book : [{price, qty}]. qty 0 = suppression."""
    out = []
    for r in rows or ():
        out.append({"prix": to_float(r.get("price")), "taille": to_float(r.get("qty"))})
    return out


def normalize_book_snapshot(m: Mapping) -> dict:
    """book_snapshot : product_id, bids[{price,qty}], asks[{price,qty}], seq."""
    return {"venue": VENUE, "symbole": m.get("product_id"), "type_maj": "snapshot", "seq": m.get("seq"),
            "bids": _niveaux_dict(m.get("bids")), "asks": _niveaux_dict(m.get("asks"))}


def normalize_book_delta(m: Mapping) -> dict:
    """book (delta) : product_id, side(buy/sell), price, qty, seq."""
    return {"venue": VENUE, "symbole": m.get("product_id"), "type_maj": "delta", "seq": m.get("seq"),
            "side": norm_side(m.get("side")), "prix": to_float(m.get("price")), "taille": to_float(m.get("qty"))}


def normalize_trade(t: Mapping) -> dict:
    """trade : product_id, side, qty, price, time."""
    return ligne(ts=t.get("time"), venue=VENUE, symbole=t.get("product_id"), type_="trade",
                 prix=t.get("price"), taille=t.get("qty"), side=t.get("side"))


def normalize_ticker(tk: Mapping) -> dict:
    """ticker : markPrice, index, openInterest, funding, relative_funding. basis = mark - index (DATA-084)."""
    mark = to_float(tk.get("markPrice"))
    index = to_float(tk.get("index"))
    return {"venue": VENUE, "symbole": tk.get("product_id"), "mark": mark, "index": index,
            "oi": to_float(tk.get("openInterest")), "funding": to_float(tk.get("funding")),
            "basis": (mark - index) if (mark is not None and index is not None) else None}


def best_bid_ask(book: Mapping) -> dict:
    d = nbbo(book.get("bids"), book.get("asks"))
    d.update({"venue": VENUE, "symbole": book.get("symbole")})
    return d


def cvd(trades: Sequence[Mapping]) -> dict:
    """DATA-083 : Cumulative Volume Delta = somme signee (buy +, sell -) des tailles. None ignore."""
    total = 0.0
    n = 0
    for t in trades:
        s = norm_side(t.get("side"))
        q = to_float(t.get("qty") or t.get("taille"))
        if s is None or q is None:
            continue
        total += q if s == "buy" else -q
        n += 1
    return {"venue": VENUE, "cvd": total, "n": n}


def volume_liquidation(records: Sequence[Mapping]) -> dict:
    """DATA-082 : agrege le volume de liquidation a partir d'enregistrements fournis (source live =
    REQUIRES_NETWORK). Somme des tailles par sens ; jamais de faux 0 si liste vide (n=0)."""
    buy = sum(to_float(r.get("qty")) or 0.0 for r in records if norm_side(r.get("side")) == "buy")
    sell = sum(to_float(r.get("qty")) or 0.0 for r in records if norm_side(r.get("side")) == "sell")
    return {"venue": VENUE, "vol_buy": buy, "vol_sell": sell, "n": len(list(records))}


def appliquer_flux_book(messages: Sequence[Mapping]) -> dict:
    """seq continu : snapshot pose la base, chaque delta doit incrementer seq de 1 (DATA-079)."""
    det = DetecteurSequence()
    resyncs, ok = [], 0
    for m in messages:
        if m.get("feed") == "book_snapshot":
            det.snapshot(m.get("seq"))
            ok += 1
        else:
            r = det.delta(m.get("seq"))
            if r["resync"]:
                resyncs.append({"seq": m.get("seq"), "raison": r["raison"]})
            else:
                ok += 1
    return {"applique": ok, "resyncs": resyncs, "synchronise": det.synchronise}


def mapping_silver() -> dict:
    return {"ts": "time", "symbole": "product_id", "prix": "price", "taille": "qty", "side": "side"}


def replay(msgs: Sequence[Mapping]) -> list:
    return [normalize_trade(m) for m in msgs]


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "funding", "oi", "liquidations"),
            "adaptateur": OFFLINE_READY, "pull_live": REQUIRES_NETWORK}


class LiveClientKraken(ClientLiveBase):
    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def souscrire(self, feed, product_id):
        self._refuser("%s %s" % (feed, product_id))
