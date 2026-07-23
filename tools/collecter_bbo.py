"""COLLECTEUR BBO RAPIDE HL↔Binance — la donnée propre pour trancher le lead-lag (23/07, chantier ARB).

POURQUOI. Le détecteur d'arb actuel est INVALIDE (offset de base persistant +17-30 bps = mauvais
mapping de contrat OU quote périmée — mesuré). Pour trancher HONNÊTEMENT les DEUX questions restées
ouvertes, il faut des quotes SYNCHRONISÉES et FRAÎCHES, pas le carnet à 60 s :
  1. arbitrage DEUX JAMBES convergent — l'écart se ferme-t-il vraiment, une fois le mapping propre ?
  2. lead-lag DIRECTIONNEL Binance→HL — Binance mène ~700 ms ; capturable en shadow ?

CE QUE FAIT CE COLLECTEUR (connexions PERSISTANTES) :
  * WS HL `bbo` (poussé quand le BBO change) + WS Binance `<sym>@bookTicker` (temps réel) ;
  * MAPPING EXACT des contrats (le bug du mirage) : `k`-tokens HL -> `1000…` Binance, exceptions
    connues, et **REFUS (None) si non mappable** — on ne paire JAMAIS deux contrats différents ;
  * bid/ask + taille (profondeur au top) ; timestamps EXCHANGE (venue) ET LOCAL ; ÂGE de la quote ;
  * REJET des quotes périmées (âge > seuil) — une quote vieille fabrique un faux écart ;
  * reconnexion avec backoff ; écrit des snapshots SYNCHRONISÉS (les deux venues fraîches en même temps).

Le lead-lag se mesure ENSUITE sur ces snapshots (`mesurer_lead_lag`), en shadow, jamais un ordre.

READ-ONLY / PAPER-ONLY : deux flux PUBLICS en lecture. Aucune clé, aucun ordre, aucune signature.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

WS_HL = "wss://api.hyperliquid.xyz/ws"
WS_BINANCE = "wss://fstream.binance.com/stream"
SORTIE = Path("runtime") / "data" / "bbo_synchro.jsonl"
AGE_MAX_MS = 750.0                 # au-delà, une quote est périmée pour un test lead-lag ~700 ms
FENETRE_SYNCHRO_MS = 250.0         # HL et Binance doivent être frais à moins de ça l'un de l'autre

#: MAPPING EXACT HL -> Binance perp. Les `k`-tokens HL = 1000× l'unité Binance. Exceptions listées ;
#: tout ce qui n'est pas mappable de façon SÛRE renvoie None (on n'invente pas un appariement).
_EXCEPTIONS = {"PEPE": "1000PEPEUSDT", "SHIB": "1000SHIBUSDT", "BONK": "1000BONKUSDT",
               "FLOKI": "1000FLOKIUSDT", "LUNC": "1000LUNCUSDT", "SATS": "1000SATSUSDT",
               "RATS": "1000RATSUSDT", "XEC": "1000XECUSDT", "WHYPE": None, "HYPE": None}   # HYPE pas sur Binance perp


def symbole_binance(coin_hl: str) -> str | None:
    """Le symbole perp Binance correspondant EXACTEMENT au coin HL, ou None si non mappable (refus)."""
    c = str(coin_hl or "").upper().strip()
    if not c:
        return None
    if c in _EXCEPTIONS:
        return _EXCEPTIONS[c]
    if c.startswith("K") and len(c) > 1 and c[1:].isalpha():     # kPEPE-style non listé -> 1000 + reste
        return "1000" + c[1:] + "USDT"
    if not c.isalnum():
        return None
    return c + "USDT"


def _f(x: Any) -> float | None:
    try:
        v = float(x)
        return v if v == v and v > 0 else None
    except (TypeError, ValueError):
        return None


def parser_bbo_hl(msg: Any) -> dict | None:
    """Message WS HL `bbo` -> {coin, bid, ask, bid_sz, ask_sz, ts_ex}. Autre message -> None."""
    if not isinstance(msg, dict) or msg.get("channel") != "bbo":
        return None
    d = msg.get("data") or {}
    bbo = d.get("bbo") or []
    try:
        bid, ask = bbo[0], bbo[1]
        b, a = _f(bid.get("px")), _f(ask.get("px"))
    except (IndexError, AttributeError, TypeError):
        return None
    if b is None or a is None or a < b:
        return None
    return {"coin": str(d.get("coin") or "").upper(), "bid": b, "ask": a,
            "bid_sz": _f(bid.get("sz")) or 0.0, "ask_sz": _f(ask.get("sz")) or 0.0,
            "ts_ex": float(d.get("time") or 0.0)}


def parser_bookticker_binance(msg: Any) -> dict | None:
    """Message WS Binance `<sym>@bookTicker` -> {symbol, bid, ask, bid_sz, ask_sz, ts_ex}."""
    d = msg.get("data") if isinstance(msg, dict) and "data" in msg else msg
    if not isinstance(d, dict) or "s" not in d:
        return None
    b, a = _f(d.get("b")), _f(d.get("a"))
    if b is None or a is None or a < b:
        return None
    return {"symbol": str(d.get("s")).upper(), "bid": b, "ask": a,
            "bid_sz": _f(d.get("B")) or 0.0, "ask_sz": _f(d.get("A")) or 0.0,
            "ts_ex": float(d.get("T") or d.get("E") or 0.0)}


class MagasinBBO:
    """Garde le dernier BBO de chaque venue par coin, avec son ts LOCAL, et ne produit un snapshot
    SYNCHRONISÉ que si les DEUX venues sont FRAÎCHES (âge < AGE_MAX) et proches dans le temps."""

    def __init__(self, *, age_max_ms: float = AGE_MAX_MS, fenetre_ms: float = FENETRE_SYNCHRO_MS):
        self.hl: dict[str, dict] = {}
        self.bin: dict[str, dict] = {}
        self.age_max_ms = age_max_ms
        self.fenetre_ms = fenetre_ms

    def maj_hl(self, q: dict, *, now_ms: float) -> None:
        self.hl[q["coin"]] = {**q, "ts_local": now_ms}

    def maj_binance(self, q: dict, coin_hl: str, *, now_ms: float) -> None:
        self.bin[coin_hl] = {**q, "ts_local": now_ms}

    def snapshot(self, coin: str, *, now_ms: float) -> dict | None:
        """Snapshot synchronisé FRAIS pour `coin`, ou None (une jambe manque/périmée -> rejet)."""
        h, b = self.hl.get(coin), self.bin.get(coin)
        if not h or not b:
            return None
        age_h, age_b = now_ms - h["ts_local"], now_ms - b["ts_local"]
        if age_h > self.age_max_ms or age_b > self.age_max_ms:
            return None                                        # une quote périmée = pas de snapshot
        if abs(h["ts_local"] - b["ts_local"]) > self.fenetre_ms:
            return None                                        # pas assez synchrones
        hmid, bmid = (h["bid"] + h["ask"]) / 2, (b["bid"] + b["ask"]) / 2
        return {"coin": coin, "ts_ms": int(now_ms),
                "hl_bid": h["bid"], "hl_ask": h["ask"], "bin_bid": b["bid"], "bin_ask": b["ask"],
                "hl_mid": hmid, "bin_mid": bmid, "ecart_mid_bps": round(1e4 * (hmid - bmid) / bmid, 3),
                "taille_top_usd": round(min(h["bid_sz"] * hmid, b["bid_sz"] * bmid), 2),
                "ts_ex_hl": h["ts_ex"], "ts_ex_bin": b["ts_ex"],
                "age_hl_ms": round(age_h, 1), "age_bin_ms": round(age_b, 1),
                "read_only": True, "real_execution": False}


def mesurer_lead_lag(series: list[tuple[float, float, float]], *, lag_ms: float) -> float | None:
    """Corrélation entre Δ(mid Binance) à t et Δ(mid HL) à t+lag, sur des snapshots (ts, hl_mid,
    bin_mid). > 0 et croissant avec lag -> Binance MÈNE HL. `None` si pas assez de points appariés."""
    s = sorted(series)
    if len(s) < 30:
        return None
    import bisect
    ts = [x[0] for x in s]
    dbin, dhl = [], []
    for i in range(1, len(s)):
        db = s[i][2] - s[i - 1][2]                             # Δ mid Binance à t
        t_cible = s[i][0] + lag_ms
        j = bisect.bisect_left(ts, t_cible)
        if j <= 0 or j >= len(s):
            continue
        dh = s[j][1] - s[j - 1][1]                             # Δ mid HL à t+lag
        dbin.append(db); dhl.append(dh)
    if len(dbin) < 20:
        return None
    import statistics as st
    mb, mh = st.mean(dbin), st.mean(dhl)
    num = sum((dbin[k] - mb) * (dhl[k] - mh) for k in range(len(dbin)))
    den = (sum((x - mb) ** 2 for x in dbin) * sum((x - mh) ** 2 for x in dhl)) ** 0.5
    return round(num / den, 4) if den > 0 else None


# ─────────────────────────────── boucle WS (asyncio, défensive) ───────────────────────────────

async def _boucle(root: Path, coins: list[str]) -> None:  # pragma: no cover (I/O réseau, non testable ici)
    import asyncio
    import websockets
    mag = MagasinBBO()
    sym_par_coin = {c: symbole_binance(c) for c in coins if symbole_binance(c)}
    from hl_observer.collection import collecte_fiable as CF
    cache = CF.CacheDedup()

    async def hl():
        while True:
            try:
                async with websockets.connect(WS_HL, ping_interval=20) as ws:
                    for c in sym_par_coin:
                        await ws.send(json.dumps({"method": "subscribe",
                                                  "subscription": {"type": "bbo", "coin": c}}))
                    async for raw in ws:
                        q = parser_bbo_hl(json.loads(raw))
                        if q and q["coin"] in sym_par_coin:
                            mag.maj_hl(q, now_ms=time.time() * 1000)
            except Exception:  # noqa: BLE001 — reconnexion
                await asyncio.sleep(2.0)

    async def binance():
        streams = "/".join("%s@bookTicker" % s.lower() for s in sym_par_coin.values())
        inv = {s.upper(): c for c, s in sym_par_coin.items()}
        while True:
            try:
                async with websockets.connect("%s?streams=%s" % (WS_BINANCE, streams), ping_interval=20) as ws:
                    async for raw in ws:
                        q = parser_bookticker_binance(json.loads(raw))
                        if q and q["symbol"] in inv:
                            mag.maj_binance(q, inv[q["symbol"]], now_ms=time.time() * 1000)
            except Exception:  # noqa: BLE001
                await asyncio.sleep(2.0)

    async def ecrire():
        while True:
            await asyncio.sleep(0.5)
            now = time.time() * 1000
            snaps = [s for c in sym_par_coin if (s := mag.snapshot(c, now_ms=now))]
            if snaps:
                propres = CF.collecter_proprement(snaps, source="bbo_hl_bin",
                                                  champs_cle=("coin", "ts_ms"), cache=cache)
                CF.append_jsonl(root / SORTIE, propres)

    await asyncio.gather(hl(), binance(), ecrire())


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import asyncio
    p = argparse.ArgumentParser(description="Collecteur BBO rapide HL/Binance (lecture seule).")
    p.add_argument("--root", default=".")
    p.add_argument("--coins", default="BTC,ETH,SOL,INJ,DASH,NEO,AVAX,LINK")
    #: run BORNÉ : le WS est persistant, mais on sort après `--duree` s pour que `boucle_collecteur`
    #: relance ET que le garde anti-orphelin (session finie ?) soit vérifié à chaque cycle.
    p.add_argument("--duree", type=float, default=300.0)
    a = p.parse_args(argv)
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]

    async def _run() -> None:
        try:
            await asyncio.wait_for(_boucle(Path(a.root), coins), timeout=max(5.0, float(a.duree)))
        except (asyncio.TimeoutError, KeyboardInterrupt):
            return

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        return 0
    return 0


__all__ = ["symbole_binance", "parser_bbo_hl", "parser_bookticker_binance", "MagasinBBO",
           "mesurer_lead_lag", "AGE_MAX_MS", "FENETRE_SYNCHRO_MS", "SORTIE"]
