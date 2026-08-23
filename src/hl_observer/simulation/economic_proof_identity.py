"""Canonical cross-family identities for economic proof events.

The final 3/3 certificate must not credit the same observable market episode to
multiple strategy families merely because their native ``trade_id`` formats
differ.  This module deliberately derives a family-agnostic identity from the
executed instrument, economic direction and entry/exit wall-clock times.

Only OOS and forward rows are proof-eligible.  Missing identity material is
reported explicitly so the final gate can fail closed rather than guess.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

PROOF_SEGMENTS = frozenset({"oos", "forward"})
SCHEMA = "hypersmart.cross_family_proof_identity.v1"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _timestamp_ms(row: Mapping[str, Any], *, role: str) -> int | None:
    keys = {
        "entry": ("entry_ts_ms", "ts_in", "entry_ts_ns"),
        "exit": ("exit_ts_ms", "ts_out", "exit_ts_ns"),
    }[role]
    for key in keys:
        value = _number(row.get(key))
        if value is None or value <= 0:
            continue
        if key.endswith("_ns"):
            value /= 1_000_000.0
        # Canonicalise to recorded millisecond precision.  Copy/Cross already
        # use ms while the certified Lead-Lag ledger stores ns.
        return int(round(value))
    return None


def _direction(row: Mapping[str, Any]) -> int | None:
    raw = row.get("direction")
    if isinstance(raw, str):
        normalized = raw.strip().upper()
        if normalized in {"LONG", "BUY", "B", "+1", "1"}:
            return 1
        if normalized in {"SHORT", "SELL", "S", "-1"}:
            return -1
    value = _number(raw)
    if value is not None and value != 0:
        return 1 if value > 0 else -1

    # Cross-Venue v2/v3 stores the economic orientation in the signed basis
    # when the native ``sens`` field is absent from the public trade row.
    sens = _number(row.get("sens"))
    if sens is not None and sens != 0:
        return 1 if sens > 0 else -1
    basis = _number(row.get("basis_in_bps"))
    if basis is not None and basis != 0:
        return 1 if basis > 0 else -1
    return None


def canonical_trade_event(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return one stable family-agnostic proof identity, or ``None``.

    Native IDs, strategy name, segment and PnL are intentionally absent from
    identity material.  Therefore relabelling an episode or moving it between
    OOS/forward cannot evade collision detection.
    """

    coin = str(row.get("coin") or row.get("symbol") or row.get("instrument") or "").strip().upper()
    direction = _direction(row)
    entry_ms = _timestamp_ms(row, role="entry")
    exit_ms = _timestamp_ms(row, role="exit")
    if not coin or direction not in (-1, 1) or entry_ms is None or exit_ms is None:
        return None
    if exit_ms <= entry_ms:
        return None
    material = {
        "coin": coin,
        "direction": direction,
        "entry_ts_ms": entry_ms,
        "exit_ts_ms": exit_ms,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        **material,
        "global_event_id": hashlib.sha256(encoded).hexdigest(),
    }


def proof_events(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Canonicalise OOS/forward rows and audit missing/duplicate identities."""

    events: list[dict[str, Any]] = []
    missing = 0
    proof_rows = 0
    for raw in rows:
        segment = str(raw.get("walk_forward_segment") or raw.get("segment") or "").strip().lower()
        if segment not in PROOF_SEGMENTS:
            continue
        proof_rows += 1
        event = canonical_trade_event(raw)
        if event is None:
            missing += 1
            continue
        events.append({**event, "segment": segment})

    ids = [str(row["global_event_id"]) for row in events]
    duplicates = len(ids) - len(set(ids))
    return {
        "schema": SCHEMA,
        "proof_rows": proof_rows,
        "canonical_events": len(events),
        "missing_identity_rows": missing,
        "duplicate_global_events": duplicates,
        "complete": proof_rows > 0 and missing == 0 and duplicates == 0 and len(events) == proof_rows,
        "events": events,
    }


def audit_family_event_sets(families: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Reject intra-family and pairwise cross-family proof reuse."""

    ids_by_family: dict[str, set[str]] = {}
    intra_family_duplicates: dict[str, int] = {}
    complete = True
    for family, audit in families.items():
        events = audit.get("events") if isinstance(audit.get("events"), list) else []
        ids = [
            str(row.get("global_event_id") or "")
            for row in events
            if isinstance(row, Mapping) and row.get("global_event_id")
        ]
        ids_by_family[str(family)] = set(ids)
        duplicate_count = len(ids) - len(set(ids))
        intra_family_duplicates[str(family)] = duplicate_count
        if audit.get("complete") is not True or duplicate_count:
            complete = False

    pairwise: dict[str, dict[str, Any]] = {}
    family_names = sorted(ids_by_family)
    total_cross_collisions = 0
    for index, left in enumerate(family_names):
        for right in family_names[index + 1 :]:
            overlap = sorted(ids_by_family[left] & ids_by_family[right])
            total_cross_collisions += len(overlap)
            pairwise[f"{left}__{right}"] = {
                "collision_count": len(overlap),
                "collision_ids": overlap,
            }

    no_reuse = bool(
        complete
        and total_cross_collisions == 0
        and not any(intra_family_duplicates.values())
    )
    return {
        "schema": SCHEMA,
        "complete": complete,
        "no_reuse": no_reuse,
        "total_cross_family_collisions": total_cross_collisions,
        "intra_family_duplicate_global_events": intra_family_duplicates,
        "pairwise": pairwise,
    }


__all__ = [
    "PROOF_SEGMENTS",
    "SCHEMA",
    "audit_family_event_sets",
    "canonical_trade_event",
    "proof_events",
]
