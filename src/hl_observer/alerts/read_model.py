"""Bounded deterministic read model derived only from canonical alert events."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urldefrag

from hl_observer.alerts.freshness import project_alert_freshness

READ_MODEL_SCHEMA = "hypersmart.alert_read_model.v1"
_MAX_SUMMARY_CHARS = 4_000


class AlertReadModelError(ValueError):
    """Raised when canonical input cannot produce a trustworthy read model."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _stream_hash(events: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for event in events:
        digest.update(_canonical_bytes(event))
        digest.update(b"\n")
    return digest.hexdigest()


def _family(event: Mapping[str, Any]) -> str:
    payload = event.get("payload")
    candidate: object | None = None
    if isinstance(payload, Mapping):
        candidate = payload.get("alert_family", payload.get("family"))
    normalized = str(candidate or "").strip().upper()
    return normalized[:128] if normalized else str(event["category"])


def _alert_summary(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(event["event_id"]),
        "ledger_sequence": int(event["ledger_sequence"]),
        "source_id": str(event["source_id"]),
        "category": str(event["category"]),
        "family": _family(event),
        "headline": str(event["headline"]),
        "entity_ids": list(event.get("entity_ids") or []),
        "normalized_tickers": list(event.get("normalized_tickers") or []),
        "deterministic_score": event.get("deterministic_score"),
        "source_health_state": str(event["source_health_state"]),
        "freshness_state": str(event["freshness_state"]),
        "observed_at_ms": int(event["observed_at_ms"]),
        "source_timestamp_ms": (
            int(event["source_event_time_ms"])
            if event.get("source_event_time_ms") is not None
            else None
        ),
        "last_successful_refresh_ms": int(event["fetched_at_ms"]),
        "admitted_at_ms": int(event["admitted_at_ms"]),
        "expires_at_ms": event.get("expires_at_ms"),
        "revision_of": event.get("revision_of"),
        "retracts": event.get("retracts"),
        "payload_hash": str(event["payload_hash"]),
        "policy_version": str(event["policy_version"]),
        "ingestion_code_sha": str(event["ingestion_code_sha"]),
    }


def _bounded_index(
    events: Sequence[Mapping[str, Any]],
    *,
    keys: Callable[[Mapping[str, Any]], Sequence[str]],
    limit: int,
) -> dict[str, Any]:
    buckets: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for event in events:
        sequence = int(event["ledger_sequence"])
        event_id = str(event["event_id"])
        for key in sorted(set(keys(event))):
            normalized = str(key).strip()
            if normalized:
                buckets[normalized].append((sequence, event_id))
    ranked = sorted(
        buckets,
        key=lambda key: (-max(sequence for sequence, _ in buckets[key]), key),
    )
    retained = ranked[:limit]
    materialized: dict[str, dict[str, Any]] = {}
    for key in sorted(retained):
        members = sorted(buckets[key], reverse=True)
        selected = members[:limit]
        materialized[key] = {
            "total_alerts": len(members),
            "returned_alerts": len(selected),
            "omitted_alerts": max(0, len(members) - len(selected)),
            "event_ids": [event_id for _, event_id in selected],
        }
    return {
        "total_buckets": len(buckets),
        "returned_buckets": len(materialized),
        "omitted_buckets": max(0, len(buckets) - len(materialized)),
        "buckets": materialized,
    }


def _source_health(
    events: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    latest: dict[str, Mapping[str, Any]] = {}
    gap_count: dict[str, int] = defaultdict(int)
    observation_count: dict[str, int] = defaultdict(int)
    for event in events:
        source_id = str(event["source_id"])
        latest[source_id] = event
        gap_count[source_id] += int(event.get("producer_gap_size", 0))
        observation_count[source_id] += 1
    ranked = sorted(
        latest,
        key=lambda source_id: (
            -int(latest[source_id]["ledger_sequence"]),
            source_id,
        ),
    )
    retained = ranked[:limit]
    sources: dict[str, dict[str, Any]] = {}
    for source_id in sorted(retained):
        event = latest[source_id]
        gaps = gap_count[source_id]
        slots = observation_count[source_id] + gaps
        sources[source_id] = {
            "event_id": str(event["event_id"]),
            "ledger_sequence": int(event["ledger_sequence"]),
            "declared_health_state": str(event["source_health_state"]),
            "declared_freshness_state": str(event["freshness_state"]),
            "last_observed_at_ms": int(event["observed_at_ms"]),
            "last_successful_refresh_ms": int(event["fetched_at_ms"]),
            "last_admitted_at_ms": int(event["admitted_at_ms"]),
            "observation_count": observation_count[source_id],
            "gap_count": gaps,
            "missed_poll_or_gap_rate": round(gaps / slots, 6) if slots else 0.0,
        }
    return {
        "total_sources": len(latest),
        "returned_sources": len(sources),
        "omitted_sources": max(0, len(latest) - len(sources)),
        "sources": sources,
    }


def _conflict_refs(event: Mapping[str, Any]) -> list[str]:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return []
    raw = payload.get("conflicts_with")
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, (list, tuple)):
        return sorted({str(value).strip() for value in raw if str(value).strip()})
    return []


def _unresolved_corrections_conflicts(
    events: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    by_id = {str(event["event_id"]): event for event in events}
    superseded = {
        str(reference)
        for event in events
        for reference in (event.get("revision_of"), event.get("retracts"))
        if reference is not None
    }
    active = set(by_id) - superseded
    revisions: dict[str, list[str]] = defaultdict(list)
    items: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event["event_id"])
        revision_of = event.get("revision_of")
        if revision_of is not None:
            revisions[str(revision_of)].append(event_id)
            if str(revision_of) not in by_id:
                items.append(
                    {
                        "kind": "MISSING_CORRECTION_TARGET",
                        "event_ids": [event_id],
                        "missing_event_id": str(revision_of),
                    }
                )
        for reference in _conflict_refs(event):
            if reference not in by_id:
                items.append(
                    {
                        "kind": "MISSING_CONFLICT_REFERENCE",
                        "event_ids": [event_id],
                        "missing_event_id": reference,
                    }
                )
            elif event_id in active and reference in active:
                items.append(
                    {
                        "kind": "EXPLICIT_ACTIVE_CONFLICT",
                        "event_ids": sorted((event_id, reference)),
                    }
                )
    for target_id, revision_ids in revisions.items():
        active_revisions = sorted(
            (event_id for event_id in revision_ids if event_id in active),
            key=lambda event_id: int(by_id[event_id]["ledger_sequence"]),
        )
        if len(active_revisions) > 1:
            items.append(
                {
                    "kind": "MULTIPLE_ACTIVE_REVISIONS",
                    "target_event_id": target_id,
                    "event_ids": active_revisions,
                }
            )
    unique = {
        hashlib.sha256(_canonical_bytes(item)).hexdigest(): item for item in items
    }
    ordered = [unique[key] for key in sorted(unique)]
    selected = ordered[:limit]
    return {
        "total_items": len(ordered),
        "returned_items": len(selected),
        "omitted_items": max(0, len(ordered) - len(selected)),
        "items": selected,
    }


def _research_summaries(
    events: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for event in reversed(events):
        payload = event.get("payload")
        raw = payload.get("research_summary") if isinstance(payload, Mapping) else None
        if raw is None:
            continue
        if isinstance(raw, str):
            canonical = raw.strip()
            kind = "TEXT"
        elif isinstance(raw, Mapping):
            canonical = _canonical_bytes(dict(raw)).decode("utf-8")
            kind = "JSON"
        else:
            continue
        if not canonical:
            continue
        summaries.append(
            {
                "event_id": str(event["event_id"]),
                "ledger_sequence": int(event["ledger_sequence"]),
                "source_id": str(event["source_id"]),
                "kind": kind,
                "summary_preview": canonical[:_MAX_SUMMARY_CHARS],
                "summary_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "truncated": len(canonical) > _MAX_SUMMARY_CHARS,
                "authoritative": False,
            }
        )
    selected = summaries[:limit]
    return {
        "total_summaries": len(summaries),
        "returned_summaries": len(selected),
        "omitted_summaries": max(0, len(summaries) - len(selected)),
        "summaries": selected,
    }


def _lineage_tokens(event: Mapping[str, Any]) -> set[tuple[str, str]]:
    tokens: set[tuple[str, str]] = set()

    def add_receipt(receipt: object) -> None:
        if not isinstance(receipt, Mapping):
            return
        uri = str(receipt.get("source_uri") or "").strip()
        content_hash = str(
            receipt.get("source_content_hash") or receipt.get("content_hash") or ""
        ).strip().lower()
        if uri:
            tokens.add(("SOURCE_URI", urldefrag(uri)[0]))
        if len(content_hash) == 64 and all(c in "0123456789abcdef" for c in content_hash):
            tokens.add(("CONTENT_HASH", content_hash))

    add_receipt(event.get("source_receipt"))
    refs = event.get("evidence_refs")
    if isinstance(refs, list):
        for receipt in refs:
            add_receipt(receipt)
    return tokens


def _source_lineage(
    events: Sequence[Mapping[str, Any]],
    *,
    returned_event_ids: set[str],
    limit: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    count = len(events)
    parents = list(range(count))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    token_owners: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, event in enumerate(events):
        for token in _lineage_tokens(event):
            token_owners[token].append(index)
    for owners in token_owners.values():
        for owner in owners[1:]:
            union(owners[0], owner)

    members_by_root: dict[int, list[int]] = defaultdict(list)
    for index in range(count):
        members_by_root[find(index)].append(index)
    reasons_by_root: dict[int, set[str]] = defaultdict(set)
    for (kind, _value), owners in token_owners.items():
        if len(owners) > 1:
            reasons_by_root[find(owners[0])].add(f"SHARED_{kind}")

    full_groups: list[dict[str, Any]] = []
    annotations: dict[str, dict[str, Any]] = {}
    for indexes in members_by_root.values():
        full_ids = [str(events[index]["event_id"]) for index in indexes]
        full_sources = sorted({str(events[index]["source_id"]) for index in indexes})
        returned_indexes = [
            index
            for index in sorted(
                indexes,
                key=lambda item: int(events[item]["ledger_sequence"]),
                reverse=True,
            )
            if str(events[index]["event_id"]) in returned_event_ids
        ]
        returned_ids = [str(events[index]["event_id"]) for index in returned_indexes]
        returned_sources = sorted(
            {str(events[index]["source_id"]) for index in returned_indexes}
        )
        group_id = hashlib.sha256(
            "\n".join(sorted(full_ids)).encode("utf-8")
        ).hexdigest()
        correlated = len(indexes) > 1
        group = {
            "group_id": group_id,
            "lineage_state": "CORRELATED" if correlated else "LINEAGE_UNKNOWN",
            "correlation_reasons": sorted(reasons_by_root[find(indexes[0])]),
            "total_alerts": len(indexes),
            "returned_alerts": len(returned_ids),
            "omitted_alerts": len(indexes) - len(returned_ids),
            "event_ids": returned_ids,
            "total_sources": len(full_sources),
            "returned_sources": len(returned_sources),
            "omitted_sources": len(full_sources) - len(returned_sources),
            "source_ids": returned_sources,
            "latest_ledger_sequence": max(
                int(events[index]["ledger_sequence"]) for index in indexes
            ),
        }
        full_groups.append(group)
        for event_id in full_ids:
            annotations[event_id] = {
                "group_id": group_id,
                "lineage_state": group["lineage_state"],
                "independence_state": "NOT_PROVEN",
                "corroboration_weight_upper_bound": round(1.0 / len(indexes), 12),
            }
    ranked = sorted(
        full_groups,
        key=lambda group: (-int(group["latest_ledger_sequence"]), str(group["group_id"])),
    )
    selected = [group for group in ranked if group["returned_alerts"] > 0][:limit]
    for group in selected:
        group.pop("latest_ledger_sequence", None)
    correlated_alerts = sum(
        int(group["total_alerts"])
        for group in full_groups
        if group["lineage_state"] == "CORRELATED"
    )
    unknown_alerts = count - correlated_alerts
    return {
        "independence_state": "NOT_PROVEN",
        "independent_confirmation_count": None,
        "confirmation_count_upper_bound": len(full_groups),
        "total_groups": len(full_groups),
        "returned_groups": len(selected),
        "omitted_groups": len(full_groups) - len(selected),
        "correlated_alert_count": correlated_alerts,
        "unknown_lineage_alert_count": unknown_alerts,
        "groups": selected,
    }, annotations


def build_materialized_alert_read_model(
    events: Sequence[Mapping[str, Any]],
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Build a bounded, replay-stable read model from one canonical prefix."""

    bounded_limit = int(limit)
    if bounded_limit < 1 or bounded_limit > 10_000:
        raise AlertReadModelError("READ_MODEL_LIMIT_INVALID")
    replayed = [dict(event) for event in events]
    seen_ids: set[str] = set()
    for expected_sequence, event in enumerate(replayed, start=1):
        event_id = str(event.get("event_id") or "")
        if (
            int(event.get("ledger_sequence", -1)) != expected_sequence
            or not event_id
            or event_id in seen_ids
        ):
            raise AlertReadModelError("READ_MODEL_CANONICAL_PREFIX_INVALID")
        if event.get("paper_read_only") is not True or event.get("real_execution") is not False:
            raise AlertReadModelError("READ_MODEL_PAPER_READ_ONLY_REQUIRED")
        seen_ids.add(event_id)
    latest = list(reversed(replayed[-bounded_limit:]))
    returned_event_ids = {str(event["event_id"]) for event in latest}
    source_lineage, lineage_annotations = _source_lineage(
        replayed,
        returned_event_ids=returned_event_ids,
        limit=bounded_limit,
    )
    deterministic_freshness = project_alert_freshness(
        replayed,
        projected_at_ms=max(
            (int(event["admitted_at_ms"]) for event in replayed),
            default=0,
        ),
        displayed_at_ms=None,
    )
    return {
        "schema_version": READ_MODEL_SCHEMA,
        "ledger_sequence": len(replayed),
        "ledger_prefix_hash": _stream_hash(replayed),
        "limits": {
            "alerts_per_view": bounded_limit,
            "buckets_per_index": bounded_limit,
            "sources": bounded_limit,
            "conflicts": bounded_limit,
            "research_summaries": bounded_limit,
        },
        "latest_alerts": {
            "total_alerts": len(replayed),
            "returned_alerts": len(latest),
            "omitted_alerts": max(0, len(replayed) - len(latest)),
            "alerts": [
                {
                    **_alert_summary(event),
                    "source_lineage": lineage_annotations[str(event["event_id"])],
                }
                for event in latest
            ],
        },
        "source_lineage": source_lineage,
        "alerts_by_family": _bounded_index(
            replayed,
            keys=lambda event: (_family(event),),
            limit=bounded_limit,
        ),
        "alerts_by_entity": _bounded_index(
            replayed,
            keys=lambda event: tuple(str(value) for value in event.get("entity_ids") or []),
            limit=bounded_limit,
        ),
        "alerts_by_category": _bounded_index(
            replayed,
            keys=lambda event: (str(event["category"]),),
            limit=bounded_limit,
        ),
        "current_source_health": _source_health(replayed, limit=bounded_limit),
        "unresolved_corrections_conflicts": _unresolved_corrections_conflicts(
            replayed,
            limit=bounded_limit,
        ),
        "freshness_metrics": deterministic_freshness["latency_distributions"],
        "research_summaries": _research_summaries(
            replayed,
            limit=bounded_limit,
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


def materialized_read_model_hash(read_model: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(dict(read_model))).hexdigest()


__all__ = [
    "AlertReadModelError",
    "READ_MODEL_SCHEMA",
    "build_materialized_alert_read_model",
    "materialized_read_model_hash",
]
