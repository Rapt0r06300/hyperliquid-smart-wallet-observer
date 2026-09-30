"""Durable, local-only alert spine with one canonical writer.

Producers can only create immutable proposals in their own inbox. A single
deterministic writer validates and appends canonical events, then derives a
mutable dashboard projection from that append-only ledger. The module has no
network, shell, model or trading capability.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.alerts.durability import (
    AlertProducerInbox,
    AlertSpinePaths,
    CanonicalAlertDurabilityMixin,
    SingleWriterFileLock,
    _validate_canonical_event,
    jsonl_append_fsync,
)
from hl_observer.alerts.freshness import project_alert_freshness
from hl_observer.alerts.read_model import (
    build_materialized_alert_read_model,
    materialized_read_model_hash,
)
from hl_observer.alerts.validation import (
    _CODE_SHA_RE as _CODE_SHA_RE,
)
from hl_observer.alerts.validation import (
    _DEFAULT_LEDGER_ROTATE_BYTES as _DEFAULT_LEDGER_ROTATE_BYTES,
)
from hl_observer.alerts.validation import (
    _EPOCH_RE as _EPOCH_RE,
)
from hl_observer.alerts.validation import (
    _FORBIDDEN_ORDER_KEYS as _FORBIDDEN_ORDER_KEYS,
)
from hl_observer.alerts.validation import (
    _MAX_DEDUP_KEY as _MAX_DEDUP_KEY,
)
from hl_observer.alerts.validation import (
    _MAX_ENTITY_COUNT as _MAX_ENTITY_COUNT,
)
from hl_observer.alerts.validation import (
    _MAX_EVIDENCE_REFS as _MAX_EVIDENCE_REFS,
)
from hl_observer.alerts.validation import (
    _MAX_HEADLINE as _MAX_HEADLINE,
)
from hl_observer.alerts.validation import (
    _PRODUCER_RE as _PRODUCER_RE,
)
from hl_observer.alerts.validation import (
    _SEGMENT_RE as _SEGMENT_RE,
)
from hl_observer.alerts.validation import (
    _SHA256_RE as _SHA256_RE,
)
from hl_observer.alerts.validation import (
    EVENT_SCHEMA as EVENT_SCHEMA,
)
from hl_observer.alerts.validation import (
    FRESHNESS_STATES as FRESHNESS_STATES,
)
from hl_observer.alerts.validation import (
    IMMUTABLE_LIFECYCLE_STATES as IMMUTABLE_LIFECYCLE_STATES,
)
from hl_observer.alerts.validation import (
    LEDGER_LATEST_SCHEMA as LEDGER_LATEST_SCHEMA,
)
from hl_observer.alerts.validation import (
    PROJECTION_LIFECYCLE_STATES as PROJECTION_LIFECYCLE_STATES,
)
from hl_observer.alerts.validation import (
    PROJECTION_SCHEMA as PROJECTION_SCHEMA,
)
from hl_observer.alerts.validation import (
    PROPOSAL_SCHEMA as PROPOSAL_SCHEMA,
)
from hl_observer.alerts.validation import (
    SCORE_POLICY_VERSION as SCORE_POLICY_VERSION,
)
from hl_observer.alerts.validation import (
    SCORE_WEIGHTS_BPS as SCORE_WEIGHTS_BPS,
)
from hl_observer.alerts.validation import (
    SOURCE_HEALTH_STATES as SOURCE_HEALTH_STATES,
)
from hl_observer.alerts.validation import (
    AlertSpineError as AlertSpineError,
)
from hl_observer.alerts.validation import (
    AlertValidationError as AlertValidationError,
)
from hl_observer.alerts.validation import (
    CanonicalLedgerCorruption as CanonicalLedgerCorruption,
)
from hl_observer.alerts.validation import (
    WriterBusy as WriterBusy,
)
from hl_observer.alerts.validation import (
    _bounded_strings as _bounded_strings,
)
from hl_observer.alerts.validation import (
    _canonical_bytes as _canonical_bytes,
)
from hl_observer.alerts.validation import (
    _event_identity as _event_identity,
)
from hl_observer.alerts.validation import (
    _event_reference as _event_reference,
)
from hl_observer.alerts.validation import (
    _event_stream_hash as _event_stream_hash,
)
from hl_observer.alerts.validation import (
    _evidence_refs as _evidence_refs,
)
from hl_observer.alerts.validation import (
    _is_within as _is_within,
)
from hl_observer.alerts.validation import (
    _reject_order_capability as _reject_order_capability,
)
from hl_observer.alerts.validation import (
    _score_components as _score_components,
)
from hl_observer.alerts.validation import (
    _score_receipt as _score_receipt,
)
from hl_observer.alerts.validation import (
    _sha256 as _sha256,
)
from hl_observer.alerts.validation import (
    _sha256_bytes as _sha256_bytes,
)
from hl_observer.alerts.validation import (
    _validate_lifecycle_receipt as _validate_lifecycle_receipt,
)
from hl_observer.alerts.validation import (
    _validate_producer_epoch as _validate_producer_epoch,
)
from hl_observer.alerts.validation import (
    _validate_producer_id as _validate_producer_id,
)
from hl_observer.alerts.validation import (
    _validate_proposal as _validate_proposal,
)
from hl_observer.alerts.validation import (
    build_alert_proposal as build_alert_proposal,
)
from hl_observer.collection.collecte_fiable import ecrire_atomique


class CanonicalAlertWriter(CanonicalAlertDurabilityMixin):
    """The only authority allowed to append and project canonical alerts."""

    def __init__(
        self,
        paths: AlertSpinePaths,
        *,
        clock_ms: Callable[[], int] | None = None,
        ledger_rotate_bytes: int = _DEFAULT_LEDGER_ROTATE_BYTES,
        projection_limit: int = 500,
    ) -> None:
        self.paths = paths
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.ledger_rotate_bytes = max(1, int(ledger_rotate_bytes))
        self.projection_limit = max(1, min(10_000, int(projection_limit)))

    def producer(self, producer_id: str) -> AlertProducerInbox:
        return AlertProducerInbox(self.paths.pending_root, producer_id)

    def _pending_paths(self) -> list[Path]:
        if not self.paths.pending_root.is_dir():
            return []
        return sorted(self.paths.pending_root.glob("*/*.json"))

    def _inflight_paths(self) -> list[Path]:
        if not self.paths.inflight_root.is_dir():
            return []
        return sorted(self.paths.inflight_root.glob("*/*.json"))

    def _prepare(
        self,
        pending_path: Path,
        *,
        ledger_sequence: int,
        prior_by_id: Mapping[str, Mapping[str, Any]],
    ) -> Path:
        proposal = _validate_proposal(json.loads(pending_path.read_text(encoding="utf-8")))
        if pending_path.parent.name != proposal["producer_id"]:
            raise AlertValidationError("PRODUCER_INBOX_NAMESPACE_MISMATCH")
        source = proposal["source_receipt"]
        admitted_at_ms = int(self.clock_ms())
        if admitted_at_ms < proposal["verified_at_ms"]:
            raise AlertValidationError("ADMITTED_BEFORE_VERIFIED")
        same_epoch = [
            previous
            for previous in prior_by_id.values()
            if previous.get("producer_id") == proposal["producer_id"]
            and previous.get("producer_epoch") == proposal["producer_epoch"]
        ]
        candidate_identity = {
            "source_id": source["source_id"],
            "dedup_key": proposal["dedup_key"],
            "source_content_hash": source["source_content_hash"],
            "source_event_id": proposal["source_event_id"],
            "revision_of": proposal["revision_of"],
            "retracts": proposal["retracts"],
        }
        candidate_event_id = _sha256(_event_identity(candidate_identity))
        existing = prior_by_id.get(candidate_event_id)
        if existing is not None:
            expected_producer_seq = int(existing["producer_expected_seq"])
            producer_gap_size = int(existing["producer_gap_size"])
        else:
            expected_producer_seq = (
                max(int(previous["producer_seq"]) for previous in same_epoch) + 1
                if same_epoch
                else 0
            )
            if proposal["producer_seq"] < expected_producer_seq:
                raise AlertValidationError("PRODUCER_SEQUENCE_OUT_OF_ORDER")
            producer_gap_size = proposal["producer_seq"] - expected_producer_seq
        event = {
            "schema_version": EVENT_SCHEMA,
            "ledger_sequence": int(ledger_sequence),
            "proposal_id": proposal["proposal_id"],
            "producer_id": proposal["producer_id"],
            "producer_epoch": proposal["producer_epoch"],
            "producer_seq": proposal["producer_seq"],
            "producer_expected_seq": expected_producer_seq,
            "producer_gap_detected": producer_gap_size > 0,
            "producer_gap_size": producer_gap_size,
            "source_receipt": source,
            "source_receipt_hash": proposal["source_receipt_hash"],
            "source_id": source["source_id"],
            "source_uri": source["source_uri"],
            "source_content_hash": source["source_content_hash"],
            "source_event_id": proposal["source_event_id"],
            "source_event_time_ms": proposal["source_event_time_ms"],
            "source_publish_time_ms": proposal["source_publish_time_ms"],
            "source_available_time_ms": proposal["source_available_time_ms"],
            "source_available_time_origin": proposal[
                "source_available_time_origin"
            ],
            "source_available_at_ms": proposal["source_available_time_ms"],
            "availability_lag_ms": (
                proposal["observed_at_ms"] - proposal["source_available_time_ms"]
            ),
            "observed_at_ms": proposal["observed_at_ms"],
            "fetched_at_ms": proposal["fetched_at_ms"],
            "parsed_at_ms": proposal["parsed_at_ms"],
            "parsed_at_origin": proposal["parsed_at_origin"],
            "verified_at_ms": proposal["verified_at_ms"],
            "admitted_at_ms": admitted_at_ms,
            "expires_at_ms": proposal["expires_at_ms"],
            "category": proposal["category"],
            "headline": proposal["headline"],
            "dedup_key": proposal["dedup_key"],
            "dedup_key_origin": proposal["dedup_key_origin"],
            "entity_ids": proposal["entity_ids"],
            "normalized_tickers": proposal["normalized_tickers"],
            "revision_of": proposal["revision_of"],
            "retracts": proposal["retracts"],
            "evidence_refs": proposal["evidence_refs"],
            "source_health_state": proposal["source_health_state"],
            "freshness_state": proposal["freshness_state"],
            "deterministic_score_components": proposal[
                "deterministic_score_components"
            ],
            "deterministic_score": proposal["deterministic_score"],
            "deterministic_score_receipt": proposal[
                "deterministic_score_receipt"
            ],
            "model_opinion": proposal["model_opinion"],
            "economic_admission_state": proposal["economic_admission_state"],
            "order_intent_allowed": proposal["order_intent_allowed"],
            "policy_version": proposal["policy_version"],
            "ingestion_code_sha": proposal["ingestion_code_sha"],
            "payload": proposal["payload"],
            "payload_hash": proposal["payload_hash"],
            "lifecycle_state": "ADMITTED",
            "lifecycle_receipt": [
                {"state": "DETECTED", "at_ms": proposal["observed_at_ms"]},
                {"state": "FETCHED", "at_ms": proposal["fetched_at_ms"]},
                {"state": "VERIFIED", "at_ms": proposal["verified_at_ms"]},
                {"state": "ADMITTED", "at_ms": admitted_at_ms},
            ],
            "paper_read_only": True,
            "real_execution": False,
        }
        event["event_id"] = candidate_event_id
        event = _validate_canonical_event(
            event,
            expected_sequence=ledger_sequence,
            prior_by_id=prior_by_id,
        )
        prepared = {
            "schema_version": "hypersmart.alert_inflight.v1",
            "pending_path": str(pending_path.relative_to(self.paths.pending_root)),
            "event": event,
        }
        target = (
            self.paths.inflight_root
            / proposal["producer_id"]
            / pending_path.name
        )
        ecrire_atomique(
            target,
            json.dumps(prepared, ensure_ascii=False, sort_keys=True) + "\n",
        )
        return target

    def _load_inflight(self, path: Path) -> tuple[Path, dict[str, Any]]:
        prepared = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(prepared, Mapping) or prepared.get("schema_version") != "hypersmart.alert_inflight.v1":
            raise AlertValidationError("INFLIGHT_SCHEMA_INVALID")
        relative = Path(str(prepared.get("pending_path") or ""))
        pending = (self.paths.pending_root / relative).resolve()
        if not _is_within(pending, self.paths.pending_root):
            raise AlertValidationError("INFLIGHT_PENDING_PATH_ESCAPE")
        event = prepared.get("event")
        if not isinstance(event, dict):
            raise AlertValidationError("INFLIGHT_EVENT_INVALID")
        return pending, _validate_canonical_event(event)

    def _acknowledge(self, pending: Path, inflight: Path) -> None:
        relative = pending.relative_to(self.paths.pending_root)
        acknowledged = self.paths.acknowledged_root / relative
        acknowledged.parent.mkdir(parents=True, exist_ok=True)
        if pending.exists():
            if acknowledged.exists():
                if acknowledged.read_bytes() != pending.read_bytes():
                    raise AlertSpineError("ACKNOWLEDGED_PROPOSAL_COLLISION")
                pending.unlink()
            else:
                os.replace(pending, acknowledged)
        elif not acknowledged.is_file():
            raise AlertSpineError("PENDING_AND_ACK_MISSING")
        inflight.unlink(missing_ok=True)

    def process_pending(
        self,
        *,
        max_events: int | None = None,
        after_prepare: Callable[[Mapping[str, Any]], None] | None = None,
        after_append: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        accepted = 0
        deduplicated = 0
        with SingleWriterFileLock(self.paths.writer_lock_path):
            events = self.read_ledger()
            self._validate_cursor(
                self.paths.writer_cursor_path,
                consumer="canonical-writer",
                events=events,
            )
            by_event_id = {str(event["event_id"]): event for event in events}
            while max_events is None or accepted + deduplicated < max_events:
                inflight_paths = self._inflight_paths()
                if inflight_paths:
                    inflight = inflight_paths[0]
                else:
                    pending_paths = self._pending_paths()
                    if not pending_paths:
                        break
                    inflight = self._prepare(
                        pending_paths[0],
                        ledger_sequence=len(events) + 1,
                        prior_by_id=by_event_id,
                    )
                    if after_prepare is not None:
                        _, prepared_event = self._load_inflight(inflight)
                        after_prepare(prepared_event)
                pending, event = self._load_inflight(inflight)
                event = _validate_canonical_event(
                    event,
                    prior_by_id=by_event_id,
                )
                event_id = str(event.get("event_id") or "")
                existing = by_event_id.get(event_id)
                if existing is not None:
                    non_economic_metadata = {
                        "ledger_sequence",
                        "admitted_at_ms",
                        "proposal_id",
                        "producer_id",
                        "producer_epoch",
                        "producer_seq",
                        "producer_expected_seq",
                        "producer_gap_detected",
                        "producer_gap_size",
                        "lifecycle_receipt",
                        "model_opinion",
                    }
                    comparable_existing = {
                        key: value
                        for key, value in existing.items()
                        if key not in non_economic_metadata
                    }
                    comparable_event = {
                        key: value
                        for key, value in event.items()
                        if key not in non_economic_metadata
                    }
                    if comparable_existing != comparable_event:
                        raise CanonicalLedgerCorruption("EVENT_ID_CONTENT_COLLISION")
                    self._acknowledge(pending, inflight)
                    self._write_cursor(
                        self.paths.writer_cursor_path,
                        consumer="canonical-writer",
                        events=events,
                    )
                    deduplicated += 1
                    continue
                if event.get("ledger_sequence") != len(events) + 1:
                    raise CanonicalLedgerCorruption("INFLIGHT_SEQUENCE_STALE")
                jsonl_append_fsync(self.paths.ledger_path, event)
                events.append(event)
                by_event_id[event_id] = event
                self._rotate_ledger_if_needed(events)
                self._write_latest_pointer(events)
                if after_append is not None:
                    after_append(event)
                self._acknowledge(pending, inflight)
                self._write_cursor(
                    self.paths.writer_cursor_path,
                    consumer="canonical-writer",
                    events=events,
                )
                accepted += 1
            self._write_cursor(
                self.paths.writer_cursor_path,
                consumer="canonical-writer",
                events=events,
            )
            self._write_latest_pointer(events)
            projection = self.rebuild_projection(events=events)
        return {
            "schema_version": "hypersmart.alert_writer_run.v1",
            "accepted": accepted,
            "deduplicated": deduplicated,
            "ledger_count": len(events),
            "projection_count": projection["alert_count"],
            "paper_read_only": True,
            "real_execution": False,
        }

    def rebuild_projection(
        self,
        *,
        events: list[dict[str, Any]] | None = None,
        displayed_at_ms: int | None = None,
    ) -> dict[str, Any]:
        replayed = self.read_ledger() if events is None else list(events)
        self._validate_cursor(
            self.paths.projection_cursor_path,
            consumer="dashboard-projection",
            events=replayed,
        )
        projected_at_ms = int(self.clock_ms())
        if any(projected_at_ms < int(event["admitted_at_ms"]) for event in replayed):
            raise AlertValidationError("PROJECTED_BEFORE_ADMITTED")
        if displayed_at_ms is not None:
            displayed_at_ms = int(displayed_at_ms)
            if displayed_at_ms < projected_at_ms:
                raise AlertValidationError("DISPLAYED_BEFORE_PROJECTED")
        states = {
            str(event["event_id"]): (
                "EXPIRED"
                if event.get("expires_at_ms") is not None
                and projected_at_ms >= int(event["expires_at_ms"])
                else "PROJECTED"
            )
            for event in replayed
        }
        for event in replayed:
            revision_of = event.get("revision_of")
            retracts = event.get("retracts")
            if revision_of is not None:
                states[str(revision_of)] = "CORRECTED"
            if retracts is not None:
                states[str(retracts)] = "RETRACTED"
        visible_replayed = replayed[-self.projection_limit :]
        freshness_projection = project_alert_freshness(
            visible_replayed,
            projected_at_ms=projected_at_ms,
            displayed_at_ms=displayed_at_ms,
        )
        projected_alerts = [
            {
                **event,
                "projection_lifecycle_state": states[str(event["event_id"])],
                "effective_freshness_state": freshness_projection[
                    "event_states"
                ][str(event["event_id"])]["effective_freshness_state"],
                "effective_source_health_state": freshness_projection[
                    "event_states"
                ][str(event["event_id"])]["effective_source_health_state"],
                "no_news_conclusion_valid": freshness_projection["event_states"][
                    str(event["event_id"])
                ]["no_news_conclusion_valid"],
            }
            for event in reversed(visible_replayed)
        ]
        telemetry: dict[str, int] = {"projected_at_ms": projected_at_ms}
        if displayed_at_ms is not None:
            telemetry["displayed_at_ms"] = displayed_at_ms
        read_model = build_materialized_alert_read_model(
            replayed,
            limit=self.projection_limit,
        )
        read_model_hash = materialized_read_model_hash(read_model)
        projection = {
            "schema_version": PROJECTION_SCHEMA,
            "last_ledger_sequence": len(replayed),
            "alert_count": len(replayed),
            "returned_alert_count": len(projected_alerts),
            "omitted_alert_count": max(0, len(replayed) - len(projected_alerts)),
            "alerts": projected_alerts,
            "materialized_read_model": read_model,
            "materialized_read_model_hash": read_model_hash,
            "derived_from": str(self.paths.ledger_latest_pointer_path),
            "canonical_projection_hash": read_model_hash,
            "freshness": freshness_projection,
            "projection_telemetry": telemetry,
            "paper_read_only": True,
            "real_execution": False,
        }
        ecrire_atomique(
            self.paths.projection_path,
            json.dumps(projection, ensure_ascii=False, sort_keys=True) + "\n",
        )
        self._write_cursor(
            self.paths.projection_cursor_path,
            consumer="dashboard-projection",
            events=replayed,
        )
        return projection


__all__ = [
    "AlertProducerInbox",
    "AlertSpineError",
    "AlertSpinePaths",
    "AlertValidationError",
    "CanonicalAlertWriter",
    "CanonicalLedgerCorruption",
    "EVENT_SCHEMA",
    "PROJECTION_SCHEMA",
    "PROPOSAL_SCHEMA",
    "SingleWriterFileLock",
    "WriterBusy",
    "build_alert_proposal",
    "jsonl_append_fsync",
]
