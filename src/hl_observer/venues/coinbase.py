"""[DATA-062..071 / AUD-270] Adaptateur Coinbase (Advanced Trade WS) — OFFLINE : normalisation du schema
PUBLIC documente (l2_data, market_trades, ticker, candles, status, heartbeats) vers le schema canonique,
continuite via sequence_num (DATA-069), heartbeats (DATA-068), mapping USD/USDC (DATA-070), lead-lag
spot/perp (DATA-071). Pull LIVE derriere une frontiere REQUIRES_NETWORK. stdlib pure, 0 reseau, 0 cle."""
from __future__ import annotations

from typing import Mapping, Sequence

from ._canon import (ClientLiveBase, DetecteurSequence, OFFLINE_READY, REQUIRES_NETWORK,
                     ligne, nbbo, to_float)

VENUE = "coinbase"
ENDPOINTS = {
    "ws": "wss://advanced-trade-ws.coinbase.com",
    "channels": ("level2", "market_trades", "ticker", "candles", "status", "heartbeats"),
}


def normalize_l2(evt: Mapping) -> dict:
    """l2_data event : type snapshot|update, product_id, updates[{side(bid/offer), price_level, new_quantity}]."""
    bids, asks = [], []
    for u in evt.get("updates") or ():
        lvl = {"prix": to_float(u.get("price_level")), "taille": to_float(u.get("new_quantity"))}
        if str(u.get("side")).lower() in ("bid", "buy"):
            bids.append(lvl)
        else:
            asks.append(lvl)
    return {"venue": VENUE, "symbole": evt.get("product_id"), "type_maj": evt.get("type"),
            "bids": bids, "asks": asks}


def normalize_trade(t: Mapping) -> dict:
    """market_trades trade : trade_id, product_id, price, size, side (BUY/SELL taker), time."""
    return ligne(ts=t.get("time"), venue=VENUE, symbole=t.get("product_id"), type_="trade",
                 prix=t.get("price"), taille=t.get("size"), side=t.get("side"))


def normalize_ticker(tk: Mapping) -> dict:
    """ticker : product_id, price, best bid/ask (spot/perp)."""
    return {"venue": VENUE, "symbole": tk.get("product_id"), "last": to_float(tk.get("price")),
            "best_bid": to_float(tk.get("best_bid")), "best_ask": to_float(tk.get("best_ask"))}


def normalize_candle(c: Mapping) -> dict:
    """candles : start, open, high, low, close, volume, product_id (DATA-066)."""
    return {"venue": VENUE, "symbole": c.get("product_id"), "ts": c.get("start"),
            "open": to_float(c.get("open")), "high": to_float(c.get("high")),
            "low": to_float(c.get("low")), "close": to_float(c.get("close")),
            "volume": to_float(c.get("volume"))}


def normalize_status(s: Mapping) -> dict:
    """status : product_id, status (online/offline/...), trading (DATA-067)."""
    return {"venue": VENUE, "symbole": s.get("product_id"), "etat": s.get("status")}


def best_bid_ask(book: Mapping) -> dict:
    d = nbbo(book.get("bids"), book.get("asks"))
    d.update({"venue": VENUE, "symbole": book.get("symbole")})
    return d


def heartbeat(hb: Mapping) -> dict:
    """heartbeats : current_time, heartbeat_counter (DATA-068). Liveness ; le trou de counter se voit."""
    return {"venue": VENUE, "ts": hb.get("current_time"), "counter": hb.get("heartbeat_counter")}


def paire_usd_usdc(product_id: str) -> dict:
    """DATA-070 : map BTC-USD <-> BTC-USDC (meme sous-jacent, quote differente ; jamais confondus)."""
    base = str(product_id).split("-")[0]
    return {"base": base, "usd": base + "-USD", "usdc": base + "-USDC"}


def continuite_sequence(messages: Sequence[Mapping]) -> dict:
    """DATA-069 : sequence_num top-level doit s'incrementer de 1. Tout saut -> resync (jamais masque)."""
    det = DetecteurSequence()
    resyncs, ok = [], 0
    for i, m in enumerate(messages):
        sn = m.get("sequence_num")
        if i == 0:
            det.snapshot(sn)
            ok += 1
        else:
            r = det.delta(sn)
            if r["resync"]:
                resyncs.append({"sequence_num": sn, "raison": r["raison"]})
            else:
                ok += 1
    return {"ok": ok, "resyncs": resyncs}


def lead_lag(spot: Sequence[float], perp: Sequence[float]) -> dict:
    """DATA-071 : signe du lead-lag spot/perp par cross-correlation DEMEANEE des rendements a lag -1/0/+1.
    lag=+1 => perp mene le spot ; lag=-1 => spot mene ; lag=0 => synchrone. Une serie sans variation
    (tendance plate) ne porte aucune info de lead-lag -> lag 0 (jamais un faux signal)."""
    n = min(len(spot), len(perp))
    if n < 4:
        return {"lag": None, "raison": "series_trop_courtes"}
    ds = [spot[i + 1] - spot[i] for i in range(n - 1)]
    dp = [perp[i + 1] - perp[i] for i in range(n - 1)]

    def demean(x):
        m = sum(x) / len(x)
        return [v - m for v in x]

    ds, dp = demean(ds), demean(dp)

    def dot(a, b):
        m = min(len(a), len(b))
        return sum(a[i] * b[i] for i in range(m))

    c0 = dot(ds, dp)
    cpos = dot(ds[1:], dp[:-1])   # perp mene (perp[t-1] ~ spot[t])
    cneg = dot(ds[:-1], dp[1:])   # spot mene
    best_lag, best_val = 0, c0
    if cpos > best_val:
        best_lag, best_val = 1, cpos
    if cneg > best_val:
        best_lag, best_val = -1, cneg
    return {"lag": best_lag, "c0": c0, "c_perp_mene": cpos, "c_spot_mene": cneg}


def mapping_silver() -> dict:
    return {"ts": "time", "symbole": "product_id", "prix": "price", "taille": "size", "side": "side"}


def replay(msgs: Sequence[Mapping]) -> list:
    return [normalize_trade(m) for m in msgs]


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades"), "adaptateur": OFFLINE_READY,
            "pull_live": REQUIRES_NETWORK}


class LiveClientCoinbase(ClientLiveBase):
    statut = REQUIRES_NETWORK

    def __init__(self) -> None:
        super().__init__(venue=VENUE)

    def souscrire(self, canal, product_id):
        self._refuser("%s %s" % (canal, product_id))
