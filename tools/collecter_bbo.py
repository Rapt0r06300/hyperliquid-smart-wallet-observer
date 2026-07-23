"""COLLECTEUR BBO RAPIDE HL↔Binance — PERSISTANT, horloge MONOTONE (23/07, chantier ARB).

POURQUOI CETTE VERSION (correction critique de Flo). Pour mesurer un lead-lag de ~100-700 ms :
  * le processus doit être VRAIMENT PERSISTANT — pas relancé toutes les 300 s (ça briserait la
    continuité). Il reconnecte SEULEMENT sur panne, garde son état (`MagasinBBO`), et est supervisé
    par HEARTBEAT + garde anti-orphelin interne (il sort si la session du lanceur a changé) ;
  * chaque message HL et Binance est horodaté DÈS SA RÉCEPTION avec **la même horloge MONOTONE locale**
    (`time.monotonic_ns()`). L'âge et la synchro se calculent sur CETTE horloge, jamais sur les
    timestamps exchange (skew entre venues). *Sans ça, un décalage d'horloge ressemble à un edge.*
  * on conserve AUSSI les timestamps EXCHANGE quand ils existent, les UPDATE IDs (Binance `u`), le
    compte de RECONNEXIONS et les TROUS de données — pour que la qualité soit auditable, pas supposée.

Le lead-lag se mesure ENSUITE sur ces snapshots (`lead_lag_shadow.py`), en shadow, jamais un ordre.
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
TAPE = Path("runtime") / "data" / "bbo_tape.jsonl"     # chaque message BBO (monotone) -> lead-lag fin
HEARTBEAT = Path("runtime") / "data" / "bbo_heartbeat.json"
MARQUEUR = Path("runtime") / "data" / "lanceur_session_marqueur.txt"
AGE_MAX_MS = 750.0                 # au-delà (horloge MONOTONE), quote périmée -> rejet
FENETRE_SYNCHRO_MS = 250.0         # HL et Binance frais à moins de ça l'un de l'autre (monotone)
GAP_MS = 5000.0                    # aucun message d'une venue pendant ça = TROU de données noté

_EXCEPTIONS = {"PEPE": "1000PEPEUSDT", "SHIB": "1000SHIBUSDT", "BONK": "1000BONKUSDT",
               "FLOKI": "1000FLOKIUSDT", "LUNC": "1000LUNCUSDT", "SATS": "1000SATSUSDT",
               "RATS": "1000RATSUSDT", "XEC": "1000XECUSDT", "WHYPE": None, "HYPE": None}


def symbole_binance(coin_hl: str) -> str | None:
    """Symbole perp Binance correspondant EXACTEMENT au coin HL, ou None si non mappable (refus)."""
    c = str(coin_hl or "").upper().strip()
    if not c:
        return None
    if c in _EXCEPTIONS:
        return _EXCEPTIONS[c]
    if c.startswith("K") and len(c) > 1 and c[1:].isalpha():
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
    """WS HL `bbo` -> {coin, bid, ask, bid_sz, ask_sz, ts_ex}. Autre message -> None."""
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
    """WS Binance `<sym>@bookTicker` -> {symbol, bid, ask, bid_sz, ask_sz, ts_ex, update_id}."""
    d = msg.get("data") if isinstance(msg, dict) and "data" in msg else msg
    if not isinstance(d, dict) or "s" not in d:
        return None
    b, a = _f(d.get("b")), _f(d.get("a"))
    if b is None or a is None or a < b:
        return None
    return {"symbol": str(d.get("s")).upper(), "bid": b, "ask": a,
            "bid_sz": _f(d.get("B")) or 0.0, "ask_sz": _f(d.get("A")) or 0.0,
            "ts_ex": float(d.get("T") or d.get("E") or 0.0), "update_id": d.get("u")}


def parser_aggtrade_binance(msg: Any) -> dict | None:
    """WS Binance `<sym>@aggTrade` -> {symbol, px, sz, side, ts_ex}. Le CHOC exécutable (Flo : détecter
    le choc sur les TRADES, pas le mid). `m`=True -> l'agressif est le VENDEUR (l'acheteur est maker)."""
    d = msg.get("data") if isinstance(msg, dict) and "data" in msg else msg
    if not isinstance(d, dict) or d.get("e") != "aggTrade" or "p" not in d:
        return None
    px = _f(d.get("p"))
    if px is None:
        return None
    return {"symbol": str(d.get("s")).upper(), "px": px, "sz": _f(d.get("q")) or 0.0,
            "side": "SELL" if d.get("m") else "BUY", "ts_ex": float(d.get("T") or 0.0)}


class MagasinBBO:
    """Dernier BBO de chaque venue par coin, horodaté sur l'horloge MONOTONE de réception. Ne produit
    un snapshot SYNCHRONISÉ que si les DEUX venues sont FRAÎCHES (âge monotone < AGE_MAX) et proches."""

    def __init__(self, *, age_max_ms: float = AGE_MAX_MS, fenetre_ms: float = FENETRE_SYNCHRO_MS):
        self.hl: dict[str, dict] = {}
        self.bin: dict[str, dict] = {}
        self.age_max_ms = age_max_ms
        self.fenetre_ms = fenetre_ms

    def maj_hl(self, q: dict, *, recu_mono_ns: int) -> None:
        self.hl[q["coin"]] = {**q, "recu_ns": recu_mono_ns}

    def maj_binance(self, q: dict, coin_hl: str, *, recu_mono_ns: int) -> None:
        self.bin[coin_hl] = {**q, "recu_ns": recu_mono_ns}

    def snapshot(self, coin: str, *, now_mono_ns: int, ts_wall_ms: float) -> dict | None:
        """Snapshot synchronisé FRAIS, âges/synchro sur l'horloge MONOTONE. None si rejeté."""
        h, b = self.hl.get(coin), self.bin.get(coin)
        if not h or not b:
            return None
        age_h = (now_mono_ns - h["recu_ns"]) / 1e6
        age_b = (now_mono_ns - b["recu_ns"]) / 1e6
        if age_h > self.age_max_ms or age_b > self.age_max_ms:
            return None                                        # quote périmée -> rejet
        desync = abs(h["recu_ns"] - b["recu_ns"]) / 1e6
        if desync > self.fenetre_ms:
            return None                                        # pas assez synchrones -> rejet
        hmid, bmid = (h["bid"] + h["ask"]) / 2, (b["bid"] + b["ask"]) / 2
        return {"coin": coin, "ts_ms": int(ts_wall_ms),
                "hl_bid": h["bid"], "hl_ask": h["ask"], "bin_bid": b["bid"], "bin_ask": b["ask"],
                "hl_mid": hmid, "bin_mid": bmid, "ecart_mid_bps": round(1e4 * (hmid - bmid) / bmid, 3),
                "taille_top_usd": round(min(h["bid_sz"] * hmid, b["bid_sz"] * bmid), 2),
                "ts_ex_hl": h.get("ts_ex"), "ts_ex_bin": b.get("ts_ex"), "update_id_bin": b.get("update_id"),
                "recu_mono_hl_ns": h["recu_ns"], "recu_mono_bin_ns": b["recu_ns"],
                "age_hl_ms": round(age_h, 2), "age_bin_ms": round(age_b, 2), "desync_ms": round(desync, 2),
                "read_only": True, "real_execution": False}


def mesurer_lead_lag(series: list[tuple[float, float, float]], *, lag_ms: float) -> float | None:
    """Corrélation Δ(mid Binance) à t vs Δ(mid HL) à t+lag, sur (ts_mono_ms, hl_mid, bin_mid).
    > 0 croissant avec lag -> Binance MÈNE HL. None si pas assez de points."""
    s = sorted(series)
    if len(s) < 30:
        return None
    import bisect
    ts = [x[0] for x in s]
    dbin, dhl = [], []
    for i in range(1, len(s)):
        db = s[i][2] - s[i - 1][2]
        j = bisect.bisect_left(ts, s[i][0] + lag_ms)
        if j <= 0 or j >= len(s):
            continue
        dbin.append(db); dhl.append(s[j][1] - s[j - 1][1])
    if len(dbin) < 20:
        return None
    import statistics as st
    mb, mh = st.mean(dbin), st.mean(dhl)
    num = sum((dbin[k] - mb) * (dhl[k] - mh) for k in range(len(dbin)))
    den = (sum((x - mb) ** 2 for x in dbin) * sum((x - mh) ** 2 for x in dhl)) ** 0.5
    return round(num / den, 4) if den > 0 else None


# ─────────────────────────────── boucle WS PERSISTANTE (asyncio) ───────────────────────────────

async def _boucle(root: Path, coins: list[str]) -> None:  # pragma: no cover (I/O réseau)
    import asyncio
    import websockets
    mag = MagasinBBO()
    sym = {c: symbole_binance(c) for c in coins if symbole_binance(c)}
    from hl_observer.collection import collecte_fiable as CF
    cache = CF.CacheDedup()
    #: TAPE BRUTE par message (horloge MONOTONE) — indispensable pour un lead-lag à 50/100 ms : un
    #: snapshot échantillonné à 250 ms ne peut PAS mesurer une réaction sous 250 ms. On enregistre
    #: chaque BBO reçu ; `lead_lag_shadow` reconstruit ensuite la réaction HL à n'importe quel horizon.
    tape: list[dict] = []
    stats = {"ecrits": 0, "rejets": 0, "reconnexions_hl": 0, "reconnexions_bin": 0, "trous": 0,
             "dernier_hl_ns": 0, "dernier_bin_ns": 0, "debut_mono_ns": time.monotonic_ns()}
    marqueur0 = MARQUEUR.read_text(encoding="utf-8").strip() if MARQUEUR.exists() else ""

    async def hl():
        while True:
            try:
                async with websockets.connect(WS_HL, ping_interval=20) as ws:
                    for c in sym:
                        await ws.send(json.dumps({"method": "subscribe",
                                                  "subscription": {"type": "bbo", "coin": c}}))
                    async for raw in ws:
                        r = time.monotonic_ns()
                        if stats["dernier_hl_ns"] and (r - stats["dernier_hl_ns"]) / 1e6 > GAP_MS:
                            stats["trous"] += 1
                        stats["dernier_hl_ns"] = r
                        q = parser_bbo_hl(json.loads(raw))
                        if q and q["coin"] in sym:
                            mag.maj_hl(q, recu_mono_ns=r)
                            tape.append({"venue": "HL", "coin": q["coin"], "recu_ns": r,
                                         "mid": (q["bid"] + q["ask"]) / 2, "bid": q["bid"], "ask": q["ask"],
                                         "ts_wall_ms": time.time() * 1000, "ts_ex": q["ts_ex"]})
            except Exception:  # noqa: BLE001 — reconnecte SEULEMENT sur panne
                stats["reconnexions_hl"] += 1
                await asyncio.sleep(1.0)

    async def binance():
        # bookTicker (entrée exécutable) ET aggTrade (détection du CHOC) sur une seule connexion.
        streams = "/".join(["%s@bookTicker" % s.lower() for s in sym.values()]
                           + ["%s@aggTrade" % s.lower() for s in sym.values()])
        inv = {s.upper(): c for c, s in sym.items()}
        while True:
            try:
                async with websockets.connect("%s?streams=%s" % (WS_BINANCE, streams), ping_interval=20) as ws:
                    async for raw in ws:
                        r = time.monotonic_ns()
                        if stats["dernier_bin_ns"] and (r - stats["dernier_bin_ns"]) / 1e6 > GAP_MS:
                            stats["trous"] += 1
                        stats["dernier_bin_ns"] = r
                        m = json.loads(raw)
                        q = parser_bookticker_binance(m)
                        if q and q["symbol"] in inv:
                            mag.maj_binance(q, inv[q["symbol"]], recu_mono_ns=r)
                            tape.append({"venue": "BIN", "coin": inv[q["symbol"]], "recu_ns": r,
                                         "mid": (q["bid"] + q["ask"]) / 2, "bid": q["bid"], "ask": q["ask"],
                                         "ts_wall_ms": time.time() * 1000, "ts_ex": q["ts_ex"],
                                         "update_id": q.get("update_id")})
                            continue
                        t = parser_aggtrade_binance(m)
                        if t and t["symbol"] in inv:                # le CHOC exécutable
                            tape.append({"venue": "BIN_TRADE", "coin": inv[t["symbol"]], "recu_ns": r,
                                         "px": t["px"], "sz": t["sz"], "side": t["side"],
                                         "ts_wall_ms": time.time() * 1000, "ts_ex": t["ts_ex"]})
            except Exception:  # noqa: BLE001
                stats["reconnexions_bin"] += 1
                await asyncio.sleep(1.0)

    async def ecrire_et_superviser():
        while True:
            await asyncio.sleep(0.25)
            now_ns = time.monotonic_ns()
            snaps = [s for c in sym if (s := mag.snapshot(c, now_mono_ns=now_ns, ts_wall_ms=time.time() * 1000))]
            # une paire connue mais rejetée (périmée/désynchro) = donnée rejetée -> on la compte
            stats["rejets"] += sum(1 for c in sym if (mag.hl.get(c) and mag.bin.get(c)) and c not in {s["coin"] for s in snaps})
            if snaps:
                propres = CF.collecter_proprement(snaps, source="bbo_hl_bin",
                                                  champs_cle=("coin", "ts_ms"), cache=cache)
                stats["ecrits"] += CF.append_jsonl(root / SORTIE, propres)
            if tape:                                           # flush de la TAPE brute (lead-lag fin)
                CF.append_jsonl(root / TAPE, list(tape))
                tape.clear()
            duree_s = (now_ns - stats["debut_mono_ns"]) / 1e9
            hb = {"ts": time.time(), "duree_continue_s": round(duree_s, 1), **stats,
                  "taux_rejet": round(stats["rejets"] / max(1, stats["ecrits"] + stats["rejets"]), 4)}
            CF.ecrire_atomique(root / HEARTBEAT, json.dumps(hb, ensure_ascii=False))
            marq = MARQUEUR.read_text(encoding="utf-8").strip() if MARQUEUR.exists() else marqueur0
            if marq != marqueur0:                              # anti-orphelin : la session a changé -> stop
                return

    await asyncio.gather(hl(), binance(), ecrire_et_superviser())


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import asyncio
    p = argparse.ArgumentParser(description="Collecteur BBO rapide HL/Binance (PERSISTANT, lecture seule).")
    p.add_argument("--root", default=".")
    p.add_argument("--coins", default="BTC,ETH,SOL,INJ,DASH,NEO,AVAX,LINK")
    a = p.parse_args(argv)
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]
    try:                                                     # 🔴 sans `websockets`, RIEN ne se collecte
        import websockets  # noqa: F401
    except ImportError:
        print("[bbo] MODULE `websockets` MANQUANT -> lance:  pip install websockets  (collecteur inactif "
              "tant qu'il n'est pas installe).", flush=True)
        return 0
    print("[bbo] demarrage PERSISTANT : %d coins mappes, WS HL bbo + Binance bookTicker/aggTrade..."
          % len(coins), flush=True)
    try:
        asyncio.run(_boucle(Path(a.root), coins))            # PERSISTANT : sort seulement sur fin de session
    except KeyboardInterrupt:
        return 0
    except Exception as exc:                                 # noqa: BLE001 — une panne DOIT etre visible
        import traceback
        print("[bbo] ARRET sur exception: %r" % exc, flush=True)
        traceback.print_exc()
        return 1
    print("[bbo] boucle terminee (fin de session).", flush=True)
    return 0


def resume(root: str | Path = ".") -> dict[str, Any]:
    """État du BBO pour le rapport : durée continue, événements propres, taux de rejet, reconnexions."""
    p = Path(root) / HEARTBEAT
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"duree_continue_s": 0, "ecrits": 0, "taux_rejet": None, "verdict": "PAS_ENCORE_LANCE"}


__all__ = ["symbole_binance", "parser_bbo_hl", "parser_bookticker_binance", "MagasinBBO",
           "mesurer_lead_lag", "resume", "AGE_MAX_MS", "FENETRE_SYNCHRO_MS", "GAP_MS", "SORTIE"]
