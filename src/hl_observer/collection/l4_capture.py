"""CHANTIER #4 — L4 / ORDER INTENT : capture le cycle intention → modify/chase → partial → fill/cancel
DÈS QUE le flux node/L4 est disponible (au lieu d'attendre que le fill public ait déjà eu lieu).

Ingère les événements L4 (NEW/MODIFY/CANCEL/PARTIAL/FILL par order_id), les écrit en JSONL canonique
append-only, puis reconstruit les cycles et features via research.order_intent (déjà testé). Sans flux L4
→ BLOCKED_EXTERNAL (interface prête, aucune intention fabriquée). 0 réseau ici, 0 ordre réel.

Schéma L4 attendu : {"order_id", "ts_ms", "type" ∈ {NEW,MODIFY,CANCEL,PARTIAL,FILL}, "coin", "side" ∈
{BUY,SELL}, "px", "sz", "mid"?, "queue_ahead"?}.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from contextlib import nullcontext
from typing import Any

from hl_observer.research.order_intent import BLOCKED, TYPES, experience_intent

_CHAMPS = ("order_id", "ts_ms", "type", "coin", "side", "px", "sz", "mid", "queue_ahead")


def _finite_number(value: Any, *, minimum: float | None = None) -> float | None:
    """Return a finite numeric value, otherwise None (never coerce bad evidence)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or (minimum is not None and parsed < minimum):
        return None
    return parsed


def event_canonique(e: Mapping[str, Any]) -> dict[str, Any] | None:
    """Parse un événement L4 brut → canonique. None si order_id/type manquant ou type inconnu (jamais supposé)."""
    if not isinstance(e, Mapping):
        return None
    oid = e.get("order_id", e.get("oid"))
    typ = str(e.get("type", "")).strip().upper()
    coin = str(e.get("coin", "")).strip().upper()
    side = str(e.get("side", "")).strip().upper()
    ts_ms = _finite_number(e.get("ts_ms"), minimum=0.0)
    px = _finite_number(e.get("px"), minimum=0.0)
    sz = _finite_number(e.get("sz"), minimum=0.0)
    mid = e.get("mid")
    queue_ahead = e.get("queue_ahead")
    if (
        oid is None or not str(oid).strip() or typ not in TYPES or not coin or side not in {"BUY", "SELL"}
        or ts_ms is None or px is None or sz is None
        or (mid is not None and _finite_number(mid, minimum=0.0) is None)
        or (queue_ahead is not None and _finite_number(queue_ahead, minimum=0.0) is None)
    ):
        return None
    return {
        k: e.get(k) for k in _CHAMPS
    } | {
        "order_id": str(oid).strip(),
        "ts_ms": ts_ms,
        "type": typ,
        "coin": coin,
        "side": side,
        "px": px,
        "sz": sz,
    }


def capturer(events: Iterable[Mapping[str, Any]] | None, out_path: str | None = None) -> dict[str, Any]:
    """Écrit les événements L4 canoniques (si out_path) puis mesure via experience_intent. Sans flux → BLOCKED."""
    if not events:
        return {"verdict": BLOCKED, "raison": "flux node/L4 absent — collecteur prêt, mesure impossible sans flux",
                "real_execution": False}
    canon: list[dict[str, Any]] = []
    quarantaine = 0
    with (open(out_path, "a", encoding="utf-8") if out_path else nullcontext()) as fh:
        for raw in events:
            ce = event_canonique(raw)
            if ce is None:                                # type inconnu / order_id absent -> quarantaine, jamais supposé
                quarantaine += 1
                continue
            canon.append(ce)
            if fh:
                fh.write(json.dumps(ce, ensure_ascii=False) + "\n")
    res = experience_intent(canon)
    res["n_captures"] = len(canon)
    res["quarantaine"] = quarantaine
    return res


__all__ = ["event_canonique", "capturer", "BLOCKED"]
