"""V26 reliquat — Cache de snapshots carnet (l2Book PUBLIC) + coûts live walk-the-book.

Deux morceaux :

* ``compute_book_costs(levels_bid, levels_ask, notional_usd)`` — pur : spread bps
  (best bid/ask) + slippage bps à la taille (walk-the-book, repo 30 rustjesty).
* Cache {coin → (spread_bps, slip_bps, ts)} alimenté par un poller PUBLIC opt-in
  (``HYPERSMART_V26_BOOK_POLLER=1``) qui interroge ``/info {"type":"l2Book"}`` pour
  les coins récemment vus par le moteur (EdgeTrendRecorder), à cadence prudente.

``live_costs_for(coin)`` ne retourne une valeur QUE si le flag consommation
(``HYPERSMART_V26_LIVE_BOOK_COSTS=1``) est actif ET l'entrée fraîche — sinon None
(le scorer garde ses constantes V25). Lecture publique seule, jamais un ordre.
"""

from __future__ import annotations

import json
import os
import threading
import time

CONSUME_FLAG = "HYPERSMART_V26_LIVE_BOOK_COSTS"
POLLER_FLAG = "HYPERSMART_V26_BOOK_POLLER"
INTERVAL_ENV = "HYPERSMART_V26_BOOK_POLL_INTERVAL_S"
MAX_COINS_ENV = "HYPERSMART_V26_BOOK_POLL_MAX_COINS"
FRESH_ENV = "HYPERSMART_V26_BOOK_FRESH_S"
NOTIONAL_ENV = "HYPERSMART_V26_BOOK_COST_NOTIONAL_USD"
URL_ENV = "HYPERSMART_V26_FUNDING_INFO_URL"   # même endpoint /info que le funding
DEFAULT_INFO_URL = "https://api.hyperliquid.xyz/info"

_DEF = {INTERVAL_ENV: 30.0, MAX_COINS_ENV: 12.0, FRESH_ENV: 90.0, NOTIONAL_ENV: 50.0}

_lock = threading.Lock()
_cache: dict[str, tuple[float, float, float]] = {}   # coin -> (spread_bps, slip_bps, ts)
_started_lock = threading.Lock()
_started = False


def _f(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    try:
        return float(e.get(name, _DEF[name]) or _DEF[name])
    except (TypeError, ValueError):
        return float(_DEF[name])


def _on(flag: str, env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(flag, "0")).strip().lower() in ("1", "true", "yes", "on")


def compute_book_costs(
    levels_bid: list[tuple[float, float]],
    levels_ask: list[tuple[float, float]],
    notional_usd: float,
) -> tuple[float, float] | None:
    """(spread_bps, slippage_bps au notionnel) depuis des niveaux [(px, sz), ...].

    Walk-the-book côté ask (achat) — repo 30 : avg_price vs best, en bps.
    Carnet vide/invalide ⇒ None (jamais de coût inventé).
    """
    try:
        if not levels_bid or not levels_ask:
            return None
        best_bid, best_ask = float(levels_bid[0][0]), float(levels_ask[0][0])
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            return None
        mid = (best_bid + best_ask) / 2.0
        spread_bps = (best_ask - best_bid) / mid * 10_000.0
        # walk-the-book : quantité acquise niveau par niveau pour le notionnel visé
        qty = 0.0
        remain_usd2 = max(1e-9, float(notional_usd))
        for px, sz in levels_ask:
            px, sz = float(px), float(sz)
            take_usd = min(remain_usd2, px * sz)
            qty += take_usd / px
            remain_usd2 -= take_usd
            if remain_usd2 <= 0:
                break
        if remain_usd2 > 0:
            qty += remain_usd2 / float(levels_ask[-1][0])
        avg_px = float(notional_usd) / qty if qty > 0 else best_ask
        slip_bps = max(0.0, (avg_px - best_ask) / best_ask * 10_000.0)
        return round(spread_bps, 4), round(slip_bps, 4)
    except Exception:
        return None


def push_costs(coin: str, spread_bps: float, slip_bps: float, ts: float | None = None) -> None:
    key = (coin or "").strip().upper()
    if not key:
        return
    with _lock:
        _cache[key] = (float(spread_bps), float(slip_bps), float(ts) if ts is not None else time.time())


def live_costs_for(coin: str, env: dict | None = None, now: float | None = None) -> tuple[float, float] | None:
    """(spread_bps, slip_bps) si flag consommation actif ET entrée fraîche, sinon None."""
    if not _on(CONSUME_FLAG, env):
        return None
    key = (coin or "").strip().upper()
    with _lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    spread, slip, ts = entry
    t = float(now) if now is not None else time.time()
    if t - ts > _f(FRESH_ENV, env):
        return None  # périmé -> constantes V25 (jamais de coût vieux)
    return spread, slip


def parse_l2book(payload: object) -> tuple[list[tuple[float, float]], list[tuple[float, float]]] | None:
    """Extrait ([(bid_px, sz)...], [(ask_px, sz)...]) du retour public l2Book."""
    try:
        levels = payload.get("levels")  # type: ignore[union-attr]
        bids = [(float(l["px"]), float(l["sz"])) for l in levels[0]]
        asks = [(float(l["px"]), float(l["sz"])) for l in levels[1]]
        if not bids or not asks:
            return None
        return bids, asks
    except Exception:
        return None


def poll_once(coins: list[str], *, opener=None, env: dict | None = None) -> int:
    """Un cycle : l2Book public pour chaque coin -> coûts -> cache. Retourne nb maj."""
    n = 0
    notional = _f(NOTIONAL_ENV, env)
    e = env if env is not None else os.environ
    target = str(e.get(URL_ENV, "") or DEFAULT_INFO_URL)
    for coin in coins:
        try:
            body = json.dumps({"type": "l2Book", "coin": coin}).encode("utf-8")
            if opener is not None:
                raw = opener(target, body, 10.0)
            else:  # pragma: no cover — réseau réel, opt-in runtime seulement
                import urllib.request

                req = urllib.request.Request(
                    target, data=body, headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    raw = resp.read()
            parsed = parse_l2book(json.loads(raw.decode("utf-8")))
            if parsed is None:
                continue
            costs = compute_book_costs(parsed[0], parsed[1], notional)
            if costs is None:
                continue
            push_costs(coin, costs[0], costs[1])
            n += 1
        except Exception:
            continue
    return n


def _loop(interval_s: float) -> None:  # pragma: no cover — boucle démon runtime
    while True:
        try:
            from hl_observer.signals.v26_entry_vetos import DEFAULT_EDGE_TREND_RECORDER

            coins = DEFAULT_EDGE_TREND_RECORDER.coins()[: int(_f(MAX_COINS_ENV))]
            if coins:
                poll_once(coins)
        except Exception:
            pass
        time.sleep(max(10.0, interval_s))


def ensure_started(env: dict | None = None) -> bool:
    """Démarre le poller carnet UNE fois si opt-in. Sinon no-op (aucun réseau)."""
    global _started
    if not _on(POLLER_FLAG, env):
        return False
    with _started_lock:
        if _started:
            return True
        t = threading.Thread(target=_loop, args=(_f(INTERVAL_ENV, env),), daemon=True, name="v26-book-poller")
        t.start()
        _started = True
        return True


def clear() -> None:
    with _lock:
        _cache.clear()


__all__ = [
    "CONSUME_FLAG", "POLLER_FLAG", "compute_book_costs", "push_costs",
    "live_costs_for", "parse_l2book", "poll_once", "ensure_started", "clear",
]
