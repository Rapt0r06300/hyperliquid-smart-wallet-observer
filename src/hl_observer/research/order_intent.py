"""ALPHA — L4 / ORDER-INTENT (P5) : reconstruction du cycle de vie + features d'intention.

La recherche HL récente montre que des commandes sont « en vol » AVANT que le spread ne bouge visiblement.
Pour l'exploiter il faut le flux L4 (chaque ORDER / MODIFY / CANCEL / FILL par order_id). Ce module construit
l'interface complète : reconstruction du cycle `ORDER→MODIFY→CHASE→PARTIAL→FILL/CANCEL` et les features :
**persistence, cancel ratio, replace ratio, chase velocity, size escalation, distance-to-touch, queue,
eventual fill**. Testé sur synthétique ; la MESURE réelle est `BLOCKED_EXTERNAL` tant que le flux L4 n'est
pas collecté (absent des données actuelles). Dès qu'il arrive, `experience_intent` mesure sans rien changer.

Schéma L4 attendu : `{"order_id", "ts_ms", "type" ∈ {NEW,MODIFY,CANCEL,PARTIAL,FILL}, "coin", "side"
∈ {BUY,SELL}, "px", "sz", "mid"?}`. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"
BLOCKED = "BLOCKED_EXTERNAL"
TYPES = ("NEW", "MODIFY", "CANCEL", "PARTIAL", "FILL")


def _finite_number(value: Any, *, minimum: float | None = None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or (minimum is not None and parsed < minimum):
        return None
    return parsed


def reconstruire_cycles(events: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Groupe les événements L4 par order_id et trie chaque cycle par temps."""
    cycles: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if not isinstance(e, Mapping):
            continue
        oid = e.get("order_id")
        ts_ms = _finite_number(e.get("ts_ms"), minimum=0.0)
        typ = str(e.get("type", "")).strip().upper()
        if oid is None or not str(oid).strip() or ts_ms is None or typ not in TYPES:
            continue
        normalized = dict(e)
        normalized["order_id"] = str(oid).strip()
        normalized["ts_ms"] = ts_ms
        normalized["type"] = typ
        cycles.setdefault(normalized["order_id"], []).append(normalized)
    for oid in cycles:
        cycles[oid].sort(key=lambda s: s.get("ts_ms", 0))
    return cycles


def cycle_features(states: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Features d'un cycle d'ordre unique (liste d'états triés)."""
    if not states:
        return {"statut": UNMEASURABLE}
    types = [str(s.get("type", "")).strip().upper() for s in states]
    ts = [v for s in states if (v := _finite_number(s.get("ts_ms"), minimum=0.0)) is not None]
    pxs = [v for s in states if (v := _finite_number(s.get("px"), minimum=0.0)) is not None]
    szs = [v for s in states if (v := _finite_number(s.get("sz"), minimum=0.0)) is not None]
    side = str(states[0].get("side", "")).upper()
    persistence_ms = (max(ts) - min(ts)) if len(ts) >= 2 else 0.0
    n_modify = types.count("MODIFY")
    eventual_fill = ("FILL" in types)
    partial = ("PARTIAL" in types)
    size_escalation = (szs[-1] / szs[0]) if len(szs) >= 2 and szs[0] > 0 else UNMEASURABLE
    # chase velocity : vitesse de déplacement du prix VERS le touch (buy monte, sell descend), bps/s
    chase = UNMEASURABLE
    if len(pxs) >= 2 and persistence_ms > 0 and pxs[0] > 0:
        sens = 1.0 if side == "BUY" else -1.0
        chase = sens * (pxs[-1] - pxs[0]) / pxs[0] * 1e4 / (persistence_ms / 1000.0)
    # distance-to-touch initiale (bps) si mid fourni
    m0 = _finite_number(states[0].get("mid"), minimum=0.0)
    dist_touch = (abs(pxs[0] - m0) / m0 * 1e4) if (pxs and m0 is not None and m0 > 0) else UNMEASURABLE
    # queue (taille devant) si fournie
    queue = _finite_number(states[0].get("queue_ahead"), minimum=0.0)
    if queue is None:
        queue = UNMEASURABLE
    return {"persistence_ms": persistence_ms, "n_modify": n_modify, "eventual_fill": eventual_fill,
            "partial": partial, "size_escalation": size_escalation, "chase_velocity_bps_s": chase,
            "distance_to_touch_bps": dist_touch, "queue_ahead": queue, "statut": "MEASURABLE"}


def agreger_wallet(cycles: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Ratios d'intention agrégés : cancel ratio, replace ratio, fill ratio sur l'ensemble des ordres."""
    n = len(cycles)
    if n == 0:
        return {"statut": UNMEASURABLE}
    cancels = replaces = fills = 0
    for states in cycles.values():
        types = [str(s.get("type")) for s in states]
        if "CANCEL" in types and "FILL" not in types:
            cancels += 1
        if types.count("MODIFY") >= 1:
            replaces += 1
        if "FILL" in types:
            fills += 1
    return {"n_ordres": n, "cancel_ratio": round(cancels / n, 4), "replace_ratio": round(replaces / n, 4),
            "fill_ratio": round(fills / n, 4), "statut": "MEASURABLE"}


def experience_intent(events: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Teste FILL_ONLY / INTENT_ONLY / WALLET+INTENT / INTENT+STATE+FLOW. `BLOCKED_EXTERNAL` sans flux L4."""
    if not events:
        return {"verdict": BLOCKED, "raison": "flux node/L4 absent — interface prête, mesure impossible sans le flux",
                "tests_prevus": ["FILL_ONLY", "INTENT_ONLY", "WALLET+INTENT", "INTENT+STATE+FLOW"],
                "real_execution": False}
    cycles = reconstruire_cycles(events)
    agg = agreger_wallet(cycles)
    feats = {oid: cycle_features(st) for oid, st in cycles.items()}
    return {"verdict": "MEASURABLE", "n_cycles": len(cycles), "agrege": agg,
            "exemple_features": next(iter(feats.values()), None), "real_execution": False}


def adapter_l4_absent() -> dict[str, Any]:
    return {"statut": BLOCKED, "manque": "flux node/L4 (ORDER/MODIFY/CANCEL/PARTIAL/FILL)"}


__all__ = ["reconstruire_cycles", "cycle_features", "agreger_wallet", "experience_intent",
           "adapter_l4_absent", "UNMEASURABLE", "BLOCKED", "TYPES"]
