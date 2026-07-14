"""V26 L1 — Cache runtime des taux de funding par coin (rolling, thread-safe).

Alimenté par la couche collecte (REST /info ou WS) via ``push``; lu par les vetos
d'entrée (``signals.v26_entry_vetos``) via ``recent_rates``. Vide = état honnête :
aucun taux fabriqué, les lecteurs reçoivent une liste vide et NE BLOQUENT PAS
(inconnu ≠ refus, cf. FUNDING_UNKNOWN). Read-only / paper — aucune donnée privée,
aucun ordre.
"""

from __future__ import annotations

import threading
import time
from collections import deque

_MAX_SAMPLES_PER_COIN = 512

_lock = threading.Lock()
_store: dict[str, deque[tuple[float, float]]] = {}


def push(coin: str, rate: float, ts: float | None = None) -> None:
    """Enregistre un taux de funding observé (donnée publique réelle uniquement)."""
    key = (coin or "").strip().upper()
    if not key:
        return
    try:
        r = float(rate)
    except (TypeError, ValueError):
        return
    if r != r or r in (float("inf"), float("-inf")):  # NaN/Inf → refus silencieux
        return
    t = float(ts) if ts is not None else time.time()
    with _lock:
        dq = _store.get(key)
        if dq is None:
            dq = deque(maxlen=_MAX_SAMPLES_PER_COIN)
            _store[key] = dq
        dq.append((t, r))


def recent_rates(coin: str, *, window_s: float = 24 * 3600.0, now: float | None = None) -> list[float]:
    """Taux dans la fenêtre glissante, ordre chronologique. Vide si inconnu."""
    key = (coin or "").strip().upper()
    if not key:
        return []
    cutoff = (float(now) if now is not None else time.time()) - float(window_s)
    with _lock:
        dq = _store.get(key)
        if not dq:
            return []
        return [r for (t, r) in dq if t >= cutoff]


def sample_count(coin: str) -> int:
    key = (coin or "").strip().upper()
    with _lock:
        dq = _store.get(key)
        return len(dq) if dq else 0


def clear(coin: str | None = None) -> None:
    """Purge (tests / reset). ``None`` = tout."""
    with _lock:
        if coin is None:
            _store.clear()
        else:
            _store.pop((coin or "").strip().upper(), None)


def known_coins() -> list[str]:
    """Tous les marches vus par le poller funding (~230 chez Hyperliquid).

    Publie pour le BALAYAGE du carnet L2 : pour repondre a « existe-t-il un marche dont le spread
    depasse les 3 bps de frais maker ? », il faut voir TOUS les marches, pas les 8 majors.
    Cette liste est deja en memoire -- elle n'etait simplement pas exposee. Zero requete en plus.
    """
    with _lock:
        return sorted(_store.keys())


__all__ = ["push", "recent_rates", "sample_count", "clear", "known_coins"]
