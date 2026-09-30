"""[DATA-072..078 / AUD-271] Adaptateur Deribit (futures/perp/options) — OFFLINE : normalisation du
schema PUBLIC documente (book.*, trades.*, ticker.*) vers le schema canonique, sequencage via
change_id/prev_change_id, open interest, funding perpetuel, implied volatility et skew d'options.
Pull LIVE derriere une frontiere REQUIRES_NETWORK. stdlib pure, 0 reseau, 0 cle, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence

from ._canon import (ClientLiveBase, DetecteurSequence, OFFLINE_READY, REQUIRES_NETWORK,
                     ligne, nbbo, to_float)

VENUE = "deribit"
ENDPOINTS = {
    "ws": "wss://www.deribit.com/ws/api/v2",
    "channels": ("book.{instr}.{group}.{depth}.{interval}", "trades.{instr}.{interval}",
                 "ticker.{instr}.{interval}"),
}


def _niveaux_action(rows: Sequence[Sequence]) -> list:
    """Deribit book : [action('new'|'change'|'delete'), price, amount]. amount 0 / delete = suppression."""
    out = []
    for r in rows or ():
        try:
            out.append({"action": r[0], "prix": float(r[1]), "taille": float(r[2])})
        except (IndexError, TypeError, ValueError):
            continue
    return out


def normalize_book(data: Mapping) -> dict:
    """book.* data : type snapshot|change, instrument_name, change_id, prev_change_id, bids/asks."""
    return {"venue": VENUE, "symbole": data.get("instrument_name"), "type_maj": data.get("type"),
            "change_id": data.get("change_id"), "prev_change_id": data.get("prev_change_id"),
            "ts": data.get("timestamp"),
            "bids": _niveaux_action(data.get("bids")), "asks": _niveaux_action(data.get("asks"))}


def normalize_trade(t: Mapping) -> dict:
    """trades data : price, amount, direction(buy/sell), timestamp, instrument_name, iv, index_price."""
    return ligne(ts=t.get("timestamp"), venue=VENUE, symbole=t.get("instrument_name"), type_="trade",
                 prix=t.get("price"), taille=t.get("amount"), side=t.get("direction"),
                 iv=to_float(t.get("iv")), index=to_float(t.get("index_price")))


def normalize_ticker(tk: Mapping) -> dict:
    """ticker : mark_price, index_price, open_interest, current_funding/funding_8h, mark_iv, best bid/ask."""
    return {"venue": VENUE, "symbole": tk.get("instrument_name"),
            "mark": to_float(tk.get("mark_price")), "index": to_float(tk.get("index_price")),
            "oi": to_float(tk.get("open_interest")),
            "funding": to_float(tk.get("current_funding")), "funding_8h": to_float(tk.get("funding_8h")),
            "mark_iv": to_float(tk.get("mark_iv")),
            "best_bid": to_float(tk.get("best_bid_price")), "best_ask": to_float(tk.get("best_ask_price"))}


def best_bid_ask(book: Mapping) -> dict:
    bids = [{"prix": n["prix"], "taille": n["taille"]} for n in book.get("bids", []) if n["action"] != "delete"]
    asks = [{"prix": n["prix"], "taille": n["taille"]} for n in book.get("asks", []) if n["action"] != "delete"]
    d = nbbo(bids, asks)
    d.update({"venue": VENUE, "symbole": book.get("symbole")})
    return d


def skew_options(options: Sequence[Mapping], spot: float) -> dict:
    """DATA-078 : skew = iv(put OTM le plus proche) - iv(call OTM le plus proche). None si donnee absente
    (jamais inventee). options = [{type:'put'/'call', strike, iv}]."""
    puts = sorted((o for o in options if str(o.get("type")).lower() == "put" and o.get("strike", 0) < spot),
                  key=lambda o: spot - o["strike"])
    calls = sorted((o for o in options if str(o.get("type")).lower() == "call" and o.get("strike", 0) > spot),
                   key=lambda o: o["strike"] - spot)
    ivp = to_float(puts[0].get("iv")) if puts else None
    ivc = to_float(calls[0].get("iv")) if calls else None
    skew = (ivp - ivc) if (ivp is not None and ivc is not None) else None
    return {"venue": VENUE, "iv_put": ivp, "iv_call": ivc, "skew": skew}


def appliquer_flux_book(messages: Sequence[Mapping]) -> dict:
    """change_id continu via prev_change_id ; snapshot pose la base (DATA-072)."""
    det = DetecteurSequence()
    resyncs, ok = [], 0
    for m in messages:
        b = normalize_book(m)
        if b["type_maj"] == "snapshot":
            det.snapshot(b["change_id"])
            ok += 1
        else:
            r = det.delta(b["change_id"], b["prev_change_id"])
            if r["resync"]:
                resyncs.append({"change_id": b["change_id"], "raison": r["raison"]})
            else:
                ok += 1
    return {"applique": ok, "resyncs": resyncs, "synchronise": det.synchronise}


def mapping_silver() -> dict:
    return {"ts": "timestamp", "symbole": "instrument_name", "prix": "price", "taille": "amount",
            "side": "direction"}


def replay(msgs: Sequence[Mapping]) -> list:
    return [normalize_trade(m) for m in msgs]


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "funding", "oi"), "adaptateur": OFFLINE_READY,
            "pull_live": REQUIRES_NETWORK}


class LiveClientDeribit(ClientLiveBase):
    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def souscrire(self, canal):
        self._refuser(canal)
