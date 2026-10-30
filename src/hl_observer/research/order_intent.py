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
SIDES = ("BUY", "SELL")


def _finite_number(value: Any, *, positive: bool = False) -> bool:
    """Accept only numeric observations that cannot fabricate a metric."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)):
        return False
    return not positive or float(value) > 0


def _cycle_invalid_reason(states: Sequence[Mapping[str, Any]]) -> str | None:
    """Return a fail-closed reason for an unusable L4 order cycle."""
    if not states:
        return "EMPTY_CYCLE"
    if any(not isinstance(state, Mapping) for state in states):
        return "NON_MAPPING_EVENT"
    types = [str(state.get("type", "")).upper() for state in states]
    if any(event_type not in TYPES for event_type in types):
        return "UNKNOWN_EVENT_TYPE"
    if types[0] != "NEW":
        return "CYCLE_MUST_START_WITH_NEW"
    if types.count("NEW") != 1:
        return "MULTIPLE_NEW_EVENTS"
    timestamps = [state.get("ts_ms") for state in states]
    if any(not _finite_number(value) for value in timestamps):
        return "MISSING_OR_INVALID_SOURCE_TIMESTAMP"
    if any(left > right for left, right in zip(timestamps, timestamps[1:], strict=False)):
        return "NON_MONOTONIC_SOURCE_TIMESTAMP"
    coins = {str(state.get("coin", "")).strip() for state in states}
    # Direct research fixtures historically omitted coin; the canonical L4
    # adapter enforces it before reaching this module.  Do not break those
    # fixtures, but reject a mixed missing/present or cross-coin cycle.
    if ("" in coins and len(coins) > 1) or ("" not in coins and len(coins) != 1):
        return "INCONSISTENT_OR_MISSING_COIN"
    sides = {str(state.get("side", "")).upper() for state in states}
    if sides != {next(iter(sides), "")} or next(iter(sides), "") not in SIDES:
        return "INCONSISTENT_OR_MISSING_SIDE"
    if any(not _finite_number(state.get("px"), positive=True) for state in states):
        return "MISSING_OR_INVALID_PRICE"
    if any(not _finite_number(state.get("sz"), positive=True) for state in states):
        return "MISSING_OR_INVALID_SIZE"
    for state in states:
        for field in ("mid", "queue_ahead"):
            if (
                field in state
                and state[field] is not None
                and not _finite_number(state[field], positive=field == "mid")
            ):
                return f"INVALID_{field.upper()}"
    terminal_seen = False
    for event_type in types:
        if terminal_seen:
            return "EVENT_AFTER_TERMINAL_STATE"
        if event_type in {"CANCEL", "FILL"}:
            terminal_seen = True
    return None


def reconstruire_cycles(events: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Groupe les événements L4 par order_id et trie chaque cycle par temps."""
    cycles: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        oid = e.get("order_id")
        if oid is None:
            continue
        cycles.setdefault(str(oid), []).append(dict(e))
    for oid in cycles:
        cycles[oid].sort(key=lambda s: s.get("ts_ms", 0))
    return cycles


def cycle_features(states: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Features d'un cycle d'ordre unique (liste d'états triés)."""
    invalid_reason = _cycle_invalid_reason(states)
    if invalid_reason is not None:
        return {"statut": UNMEASURABLE, "raison": invalid_reason}
    types = [str(s.get("type")) for s in states]
    ts = [s.get("ts_ms") for s in states if isinstance(s.get("ts_ms"), (int, float))]
    pxs = [s.get("px") for s in states if isinstance(s.get("px"), (int, float))]
    szs = [s.get("sz") for s in states if isinstance(s.get("sz"), (int, float))]
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
    m0 = states[0].get("mid")
    dist_touch = (abs(pxs[0] - m0) / m0 * 1e4) if (pxs and isinstance(m0, (int, float)) and m0 > 0) else UNMEASURABLE
    # queue (taille devant) si fournie
    queue = states[0].get("queue_ahead", UNMEASURABLE)
    return {"persistence_ms": persistence_ms, "n_modify": n_modify, "eventual_fill": eventual_fill,
            "partial": partial, "size_escalation": size_escalation, "chase_velocity_bps_s": chase,
            "distance_to_touch_bps": dist_touch, "queue_ahead": queue, "statut": "MEASURABLE"}


def agreger_wallet(cycles: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Ratios d'intention agrégés : cancel ratio, replace ratio, fill ratio sur l'ensemble des ordres."""
    n = len(cycles)
    if n == 0:
        return {"statut": UNMEASURABLE}
    invalid = {
        oid: reason
        for oid, states in cycles.items()
        if (reason := _cycle_invalid_reason(states)) is not None
    }
    if invalid:
        return {
            "n_ordres": n,
            "n_mesurables": n - len(invalid),
            "n_non_mesurables": len(invalid),
            "statut": UNMEASURABLE,
            "raison": "INVALID_CYCLE_PRESENT",
            "cycles_non_mesurables": invalid,
        }
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
    verdict = "MEASURABLE" if agg.get("statut") == "MEASURABLE" else UNMEASURABLE
    return {"verdict": verdict, "n_cycles": len(cycles), "agrege": agg,
            "exemple_features": next(iter(feats.values()), None), "real_execution": False}


def adapter_l4_absent() -> dict[str, Any]:
    return {"statut": BLOCKED, "manque": "flux node/L4 (ORDER/MODIFY/CANCEL/PARTIAL/FILL)"}


__all__ = ["reconstruire_cycles", "cycle_features", "agreger_wallet", "experience_intent",
           "adapter_l4_absent", "UNMEASURABLE", "BLOCKED", "TYPES"]
