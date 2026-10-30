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
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from hl_observer.research.order_intent import BLOCKED, TYPES, experience_intent

_CHAMPS = ("order_id", "ts_ms", "type", "coin", "side", "px", "sz", "mid", "queue_ahead")


def event_canonique(e: Mapping[str, Any]) -> dict[str, Any] | None:
    """Parse un événement L4 brut → canonique. None si order_id/type manquant ou type inconnu (jamais supposé)."""
    if not isinstance(e, Mapping):
        return None
    oid = e.get("order_id", e.get("oid"))
    typ = str(e.get("type", "")).strip().upper()
    if oid is None or not str(oid).strip() or typ not in TYPES:
        return None
    ts_ms = e.get("ts_ms")
    px = e.get("px")
    sz = e.get("sz")
    side = str(e.get("side", "")).strip().upper()
    coin = str(e.get("coin", "")).strip()
    numeric = (ts_ms, px, sz)
    if (
        not coin
        or side not in {"BUY", "SELL"}
        or any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(float(value)) for value in numeric)
        or float(px) <= 0
        or float(sz) <= 0
    ):
        return None
    for field in ("mid", "queue_ahead"):
        value = e.get(field)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or (field == "mid" and float(value) <= 0)
            or (field == "queue_ahead" and float(value) < 0)
        ):
            return None
    return {k: e.get(k) for k in _CHAMPS} | {
        "order_id": str(oid), "type": typ, "coin": coin, "side": side,
    }


def capturer(events: Iterable[Mapping[str, Any]] | None, out_path: str | None = None) -> dict[str, Any]:
    """Écrit les événements L4 canoniques (si out_path) puis mesure via experience_intent. Sans flux → BLOCKED."""
    if not events:
        return {"verdict": BLOCKED, "raison": "flux node/L4 absent — collecteur prêt, mesure impossible sans flux",
                "real_execution": False}
    canon: list[dict[str, Any]] = []
    quarantaine = 0
    with ExitStack() as stack:
        fh = (
            stack.enter_context(Path(out_path).open("a", encoding="utf-8"))
            if out_path else None
        )
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
