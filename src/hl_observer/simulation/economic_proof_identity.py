"""Canonical cross-family identities for economic proof events.

A proof row must carry two independently canonical identities:

* exact execution identity, bound to the concrete paper execution;
* underlying source/opportunity lineage, bound to the observed episode.

Both are required. Strategy labels, PnL and OOS/forward labels cannot evade
cross-family reuse detection.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

PROOF_SEGMENTS = frozenset({"oos", "forward"})
SCHEMA = "hypersmart.cross_family_proof_identity.v2"
_EXECUTION_ID_KEYS = ("execution_id", "trade_id", "paper_trade_id", "fill_id", "episode_id")
_LINEAGE_ID_KEYS = ("source_lineage_id", "source_event_id", "source_trade_id", "opportunity_id", "event_id", "checkpoint_id")


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
    sens = _number(row.get("sens"))
    if sens is not None and sens != 0:
        return 1 if sens > 0 else -1
    basis = _number(row.get("basis_in_bps"))
    if basis is not None and basis != 0:
        return 1 if basis > 0 else -1
    return None


def _identity_value(row: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def canonical_trade_event(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return exact and lineage identities, or None if proof is incomplete."""
    coin = str(row.get("coin") or row.get("symbol") or row.get("instrument") or "").strip().upper()
    direction = _direction(row)
    entry_ms = _timestamp_ms(row, role="entry")
    exit_ms = _timestamp_ms(row, role="exit")
    execution_id = _identity_value(row, _EXECUTION_ID_KEYS)
    lineage_id = _identity_value(row, _LINEAGE_ID_KEYS)
    if not coin or direction not in (-1, 1) or entry_ms is None or exit_ms is None or exit_ms <= entry_ms or execution_id is None or lineage_id is None:
        return None
    execution_material = {"coin": coin, "direction": direction, "entry_ts_ms": entry_ms, "exit_ts_ms": exit_ms, "execution_id": execution_id}
    lineage_material = {"coin": coin, "direction": direction, "source_lineage_id": lineage_id}
    return {
        **execution_material,
        "source_lineage_id": lineage_id,
        "global_event_id": _sha256(execution_material),
        "source_lineage_hash": _sha256(lineage_material),
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
    exact_ids = [str(row["global_event_id"]) for row in events]
    lineage_ids = [str(row["source_lineage_hash"]) for row in events]
    exact_duplicates = len(exact_ids) - len(set(exact_ids))
    lineage_duplicates = len(lineage_ids) - len(set(lineage_ids))
    return {
        "schema": SCHEMA, "proof_rows": proof_rows, "canonical_events": len(events),
        "missing_identity_rows": missing, "duplicate_global_events": exact_duplicates,
        "duplicate_source_lineages": lineage_duplicates,
        "complete": proof_rows > 0 and missing == 0 and exact_duplicates == 0 and lineage_duplicates == 0 and len(events) == proof_rows,
        "events": events,
    }


def audit_family_event_sets(families: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Reject exact-execution and source-lineage reuse across all families."""
    exact_ids_by_family: dict[str, set[str]] = {}
    lineage_ids_by_family: dict[str, set[str]] = {}
    intra_family_duplicates: dict[str, int] = {}
    intra_family_lineage_duplicates: dict[str, int] = {}
    complete = True
    for family, audit in families.items():
        events = audit.get("events") if isinstance(audit.get("events"), list) else []
        exact_ids = [str(row.get("global_event_id") or "") for row in events if isinstance(row, Mapping) and row.get("global_event_id")]
        lineage_ids = [str(row.get("source_lineage_hash") or "") for row in events if isinstance(row, Mapping) and row.get("source_lineage_hash")]
        name = str(family)
        exact_ids_by_family[name] = set(exact_ids)
        lineage_ids_by_family[name] = set(lineage_ids)
        intra_family_duplicates[name] = len(exact_ids) - len(set(exact_ids))
        intra_family_lineage_duplicates[name] = len(lineage_ids) - len(set(lineage_ids))
        if audit.get("complete") is not True or intra_family_duplicates[name] or intra_family_lineage_duplicates[name]:
            complete = False

    pairwise: dict[str, dict[str, Any]] = {}
    names = sorted(exact_ids_by_family)
    total_exact_collisions = 0
    total_lineage_collisions = 0
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            exact_overlap = sorted(exact_ids_by_family[left] & exact_ids_by_family[right])
            lineage_overlap = sorted(lineage_ids_by_family[left] & lineage_ids_by_family[right])
            total_exact_collisions += len(exact_overlap)
            total_lineage_collisions += len(lineage_overlap)
            pairwise[left + "__" + right] = {
                "collision_count": len(exact_overlap),
                "collision_ids": exact_overlap,
                "source_lineage_collision_count": len(lineage_overlap),
                "source_lineage_collision_ids": lineage_overlap,
            }

    no_reuse = bool(complete and total_exact_collisions == 0 and total_lineage_collisions == 0 and not any(intra_family_duplicates.values()) and not any(intra_family_lineage_duplicates.values()))
    return {
        "schema": SCHEMA, "complete": complete, "no_reuse": no_reuse,
        "total_cross_family_collisions": total_exact_collisions,
        "total_cross_family_source_lineage_collisions": total_lineage_collisions,
        "intra_family_duplicate_global_events": intra_family_duplicates,
        "intra_family_duplicate_source_lineages": intra_family_lineage_duplicates,
        "pairwise": pairwise,
    }


__all__ = ["PROOF_SEGMENTS", "SCHEMA", "audit_family_event_sets", "canonical_trade_event", "proof_events"]
