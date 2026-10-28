"""Causal Copy-Vault signal preparation extracted from executable replay."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.backtesting.copy_vault_protocol import (
    COPYABLE_ENTRY_ACTIONS,
    METAORDER_GAP_MS,
    canonical_copy_vault_coin,
    canonical_metaorder_id,
    expected_open_direction,
)
from hl_observer.ops.echec_silencieux import noter as _noter_echec

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _source_evidence_reference(row: Mapping[str, Any], *, event_id: str) -> dict[str, Any] | None:
    dataset_id = row.get("source_dataset_id")
    shard_sha256 = row.get("source_shard_sha256")
    raw_sha256 = row.get("source_raw_sha256")
    catalog_sha256 = row.get("source_catalog_sha256")
    received_at_ms = row.get("received_at_ms", row.get("observed_at_ms"))
    event_ts_ms = row.get("ts_ms")
    if (
        not isinstance(dataset_id, str)
        or not dataset_id.strip()
        or not isinstance(shard_sha256, str)
        or _SHA256_RE.fullmatch(shard_sha256) is None
        or not isinstance(raw_sha256, str)
        or _SHA256_RE.fullmatch(raw_sha256) is None
        or isinstance(event_ts_ms, bool)
        or not isinstance(event_ts_ms, int)
        or event_ts_ms <= 0
        or isinstance(received_at_ms, bool)
        or not isinstance(received_at_ms, int)
        or received_at_ms < event_ts_ms
    ):
        return None
    safe_binding_verified = bool(
        isinstance(catalog_sha256, str)
        and _SHA256_RE.fullmatch(catalog_sha256) is not None
        and row.get("source_quality_status") == "SAFE"
        and row.get("source_manifest_verified") is True
        and row.get("source_replay_compatible") is True
    )
    forward_allowed = bool(
        row.get("source") == "LIVE_WS"
        and row.get("is_snapshot") is False
        and received_at_ms >= event_ts_ms
    )
    return {
        "dataset_id": dataset_id.strip(),
        "shard_sha256": shard_sha256.lower(),
        "raw_frame_sha256": raw_sha256.lower(),
        "source_catalog_sha256": catalog_sha256.lower() if safe_binding_verified else None,
        "quality": "SAFE" if safe_binding_verified else None,
        "manifest_verified": safe_binding_verified,
        "replay_compatible": safe_binding_verified,
        "event_id": event_id,
        "event_ts_ms": event_ts_ms,
        "received_at_ms": received_at_ms,
        "source": str(row.get("source") or ""),
        "forward_evidence_allowed": forward_allowed,
    }


def _event_identity(row: Mapping[str, Any]) -> str:
    existing = str(row.get("event_id") or row.get("fill_id") or "").strip()
    if existing:
        return existing
    material = (
        str(row.get("vault") or ""),
        int(row.get("ts_ms") or 0),
        canonical_copy_vault_coin(row.get("coin")),
        int(row.get("direction") or 0),
        str(row.get("oid") or ""),
        str(row.get("hash") or ""),
        float(row.get("taille_usd") or 0.0),
    )
    return hashlib.sha256(repr(material).encode("utf-8")).hexdigest()


def cluster_metaorders(
    entries: Iterable[Mapping[str, Any]], *, gap_ms: int = METAORDER_GAP_MS
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collapse sliced fills without using later slices as independent trades."""
    canonical: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_events = 0
    input_events = 0
    invalid_events = 0
    non_entry_events = 0
    direction_contradictions = 0
    source_evidence_missing = 0
    for raw in entries:
        input_events += 1
        try:
            ts_ms = int(raw.get("ts_ms") or 0)
            direction = int(raw.get("direction") or 0)
            coin = canonical_copy_vault_coin(raw.get("coin"))
            vault = str(raw.get("vault") or "")
        except (TypeError, ValueError, OverflowError):
            invalid_events += 1
            continue
        if ts_ms <= 0 or direction not in (-1, 1) or not coin or not vault:
            invalid_events += 1
            continue
        action = str(raw.get("action") or "").strip().upper()
        expected_direction = expected_open_direction(raw)
        if action not in COPYABLE_ENTRY_ACTIONS or expected_direction is None:
            non_entry_events += 1
            continue
        if direction != expected_direction:
            direction_contradictions += 1
            continue
        event_id = _event_identity(raw)
        if event_id in seen:
            duplicate_events += 1
            continue
        seen.add(event_id)
        observed_at_ms: int | None = None
        try:
            candidate = int(raw.get("observed_at_ms") or 0)
            if candidate >= ts_ms:
                observed_at_ms = candidate
        except (TypeError, ValueError, OverflowError) as exc:
            _noter_echec("backtesting/copy_vault_executable.py:observed_at_ms", exc)
        causal_live = (
            raw.get("source") == "LIVE_WS"
            and raw.get("is_snapshot") is False
            and observed_at_ms is not None
        )
        canonical.append({
            **dict(raw),
            "event_id": event_id,
            "ts_ms": ts_ms,
            "observed_at_ms": observed_at_ms,
            "causal_forward_eligible": causal_live,
            "direction": direction,
            "action": action,
            "coin": coin,
            "vault": vault,
        })
    canonical.sort(key=lambda row: (row["ts_ms"], row["event_id"]))

    active: dict[tuple[str, str, int], dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []
    for row in canonical:
        key = (row["vault"], row["coin"], row["direction"])
        cluster = active.get(key)
        if (
            cluster is None
            or row["action"] == "OPEN"
            or row["ts_ms"] - cluster["last_fill_ts_ms"] > int(gap_ms)
        ):
            if cluster is not None:
                completed.append(cluster)
            cluster = {
                "vault": row["vault"],
                "coin": row["coin"],
                "direction": row["direction"],
                "first_fill_ts_ms": row["ts_ms"],
                "signal_ts_ms": (
                    row["observed_at_ms"]
                    if row["causal_forward_eligible"]
                    else row["ts_ms"]
                ),
                "signal_source": row.get("source") or "REST_BACKFILL",
                "causal_forward_eligible": row["causal_forward_eligible"],
                "last_fill_ts_ms": row["ts_ms"],
                "fill_count": 0,
                "leader_notional_usd": 0.0,
                "move_frac_audit_sum": 0.0,
                "member_event_ids": [],
                "member_events": [],
                "source_evidence_refs": [],
                "source_evidence_missing_count": 0,
                "source_evidence_unverified_count": 0,
            }
            cluster["first_event_id"] = row["event_id"]
            cluster["metaorder_id"] = canonical_metaorder_id(
                vault=cluster["vault"],
                coin=cluster["coin"],
                direction=cluster["direction"],
                signal_ts_ms=cluster["signal_ts_ms"],
                first_event_id=cluster["first_event_id"],
            )
            active[key] = cluster
        cluster["last_fill_ts_ms"] = row["ts_ms"]
        cluster["fill_count"] += 1
        cluster["leader_notional_usd"] += max(0.0, float(row.get("taille_usd") or 0.0))
        cluster["move_frac_audit_sum"] += max(0.0, float(row.get("move_frac") or 0.0))
        cluster["member_event_ids"].append(row["event_id"])
        evidence_ref = _source_evidence_reference(row, event_id=row["event_id"])
        if evidence_ref is None:
            source_evidence_missing += 1
            cluster["source_evidence_missing_count"] += 1
        else:
            if evidence_ref.get("quality") != "SAFE":
                cluster["source_evidence_unverified_count"] += 1
            if evidence_ref not in cluster["source_evidence_refs"]:
                cluster["source_evidence_refs"].append(evidence_ref)
        cluster["member_events"].append({
            "event_id": row["event_id"],
            "ts_ms": row["ts_ms"],
            "observed_at_ms": row["observed_at_ms"],
            "source": row.get("source") or "REST_BACKFILL",
            "causal_forward_eligible": row["causal_forward_eligible"],
            "action": row["action"],
            "source_dataset_id": row.get("source_dataset_id"),
            "source_shard_sha256": row.get("source_shard_sha256"),
            "source_raw_sha256": row.get("source_raw_sha256"),
            "source_catalog_sha256": row.get("source_catalog_sha256"),
            "source_quality_status": row.get("source_quality_status"),
            "source_manifest_verified": row.get("source_manifest_verified") is True,
            "source_replay_compatible": row.get("source_replay_compatible") is True,
            "taille_usd": max(0.0, float(row.get("taille_usd") or 0.0)),
            "cumulative_leader_notional_usd": cluster["leader_notional_usd"],
        })
    completed.extend(active.values())

    for cluster in completed:
        cluster["leader_notional_usd"] = round(cluster["leader_notional_usd"], 8)
        cluster["move_frac_audit_sum"] = round(cluster["move_frac_audit_sum"], 10)
        cluster["source_evidence_refs"].sort(
            key=lambda item: (item["event_ts_ms"], item["dataset_id"], item["event_id"])
        )
        cluster["source_evidence_status"] = (
            "COMPLETE"
            if cluster["source_evidence_missing_count"] == 0
            and len(cluster["source_evidence_refs"]) == cluster["fill_count"]
            else "INCOMPLETE"
        )
        cluster["source_safe_evidence_status"] = (
            "SAFE_CAUSAL_COMPLETE"
            if cluster["source_evidence_status"] == "COMPLETE"
            and cluster["source_evidence_unverified_count"] == 0
            and len({ref.get("source_catalog_sha256") for ref in cluster["source_evidence_refs"]}) == 1
            and all(ref.get("forward_evidence_allowed") is True for ref in cluster["source_evidence_refs"])
            else "INCOMPLETE_OR_UNVERIFIED"
        )
    completed.sort(key=lambda row: (row["signal_ts_ms"], row["metaorder_id"]))
    return completed, {
        "input_events": input_events,
        "canonical_events": len(canonical),
        "invalid_events_rejected": invalid_events,
        "non_entry_events_rejected": non_entry_events,
        "action_direction_contradictions_rejected": direction_contradictions,
        "duplicate_events_rejected": duplicate_events,
        "metaorders": len(completed),
        "sliced_fills_collapsed": max(0, len(canonical) - len(completed)),
        "signal_policy": "first_fill;later_slices_audit_only",
        "entry_policy": "action_OPEN_or_ADD_and_dir_Open_Long_or_Open_Short",
        "causal_forward_metaorders": sum(
            1 for row in completed if row.get("causal_forward_eligible") is True
        ),
        "source_evidence_refs": sum(len(row["source_evidence_refs"]) for row in completed),
        "source_evidence_missing_events": source_evidence_missing,
        "source_evidence_complete_metaorders": sum(
            row["source_evidence_status"] == "COMPLETE" for row in completed
        ),
        "source_safe_evidence_complete_metaorders": sum(
            row["source_safe_evidence_status"] == "SAFE_CAUSAL_COMPLETE"
            for row in completed
        ),
        "source_evidence_unverified_events": sum(
            int(row.get("source_evidence_unverified_count") or 0) for row in completed
        ),
    }


def select_observed_continuations(
    metaorders: Iterable[Mapping[str, Any]], *, required_observed_fills: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create causal candidates only when the Nth live fill has been observed.

    The candidate depends exclusively on the prefix available at signal time. Later
    slices remain audit material and cannot alter its identity or sizing evidence.
    """
    required = max(2, int(required_observed_fills))
    rows = [dict(row) for row in metaorders]
    selected: list[dict[str, Any]] = []
    rejected_noncausal = 0
    rejected_short = 0
    rejected_nonmonotonic = 0
    for raw in rows:
        members = [dict(row) for row in (raw.get("member_events") or [])]
        if len(members) < required:
            rejected_short += 1
            continue
        prefix = members[:required]
        if not all(
            row.get("causal_forward_eligible") is True
            and str(row.get("source") or "") == "LIVE_WS"
            and int(row.get("observed_at_ms") or 0) >= int(row.get("ts_ms") or 0) > 0
            for row in prefix
        ):
            rejected_noncausal += 1
            continue
        observed_times = [int(row["observed_at_ms"]) for row in prefix]
        if observed_times != sorted(observed_times):
            rejected_nonmonotonic += 1
            continue
        confirmation = prefix[-1]
        signal_ts_ms = int(confirmation["observed_at_ms"])
        candidate = {
            **dict(raw),
            "signal_ts_ms": signal_ts_ms,
            "signal_source": "LIVE_WS",
            "causal_forward_eligible": True,
            "confirmation_fill_count": required,
            "confirmation_event_id": str(confirmation["event_id"]),
            "leader_notional_usd_at_signal": round(
                float(confirmation.get("cumulative_leader_notional_usd") or 0.0), 8
            ),
            "confirmation_burst_ms": max(observed_times) - min(observed_times),
            "member_event_ids_at_signal": [str(row["event_id"]) for row in prefix],
            "continuation_policy": f"enter_after_{required}_observed_live_fills",
        }
        candidate["metaorder_id"] = canonical_metaorder_id(
            vault=str(candidate["vault"]),
            coin=str(candidate["coin"]),
            direction=int(candidate["direction"]),
            signal_ts_ms=signal_ts_ms,
            first_event_id=str(confirmation["event_id"]),
        )
        selected.append(candidate)
    selected.sort(key=lambda row: (int(row["signal_ts_ms"]), str(row["metaorder_id"])))
    return selected, {
        "required_observed_fills": required,
        "input_metaorders": len(rows),
        "selected_continuations": len(selected),
        "insufficient_fill_prefix_rejected": rejected_short,
        "noncausal_prefix_rejected": rejected_noncausal,
        "nonmonotonic_observation_rejected": rejected_nonmonotonic,
        "signal_policy": f"Nth_observed_live_fill_prefix_only;N={required}",
        "decision_time_feature_fields": [
            "confirmation_fill_count",
            "leader_notional_usd_at_signal",
            "confirmation_burst_ms",
            "member_event_ids_at_signal",
        ],
    }


def select_causal_protocol_inputs(
    metaorders: Iterable[Mapping[str, Any]],
    books_by_coin: Mapping[str, Iterable[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Separate certifiable live evidence from historical audit material."""
    all_metaorders = [dict(row) for row in metaorders]
    causal_metaorders = [
        row
        for row in all_metaorders
        if row.get("causal_forward_eligible") is True
        and str(row.get("signal_source") or "") == "LIVE_WS"
    ]
    causal_metaorders.sort(
        key=lambda row: (int(row.get("signal_ts_ms") or 0), str(row.get("metaorder_id") or ""))
    )
    wanted_coins = {
        canonical_copy_vault_coin(row.get("coin")) for row in causal_metaorders
    }
    total_book_rows = 0
    causal_book_rows = 0
    causal_books: dict[str, list[dict[str, Any]]] = {}
    for raw_coin, raw_rows in books_by_coin.items():
        coin = canonical_copy_vault_coin(raw_coin)
        rows = [dict(row) for row in raw_rows]
        total_book_rows += len(rows)
        if coin not in wanted_coins:
            continue
        selected = [row for row in rows if row.get("causal_observation") is True]
        selected.sort(key=lambda row: int(row.get("ts_ms") or 0))
        if selected:
            causal_books[coin] = selected
            causal_book_rows += len(selected)
    return causal_metaorders, causal_books, {
        "protocol_scope": "LIVE_WS_SIGNALS_AND_CAUSAL_HYPERLIQUID_L2_ONLY",
        "all_metaorders": len(all_metaorders),
        "causal_protocol_metaorders": len(causal_metaorders),
        "historical_or_noncausal_metaorders_excluded": (
            len(all_metaorders) - len(causal_metaorders)
        ),
        "all_loaded_book_rows": total_book_rows,
        "causal_protocol_book_rows": causal_book_rows,
        "historical_or_noncausal_book_rows_excluded": total_book_rows - causal_book_rows,
        "causal_protocol_coins": len(causal_books),
    }
