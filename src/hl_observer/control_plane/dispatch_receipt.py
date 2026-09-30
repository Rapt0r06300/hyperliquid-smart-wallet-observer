"""Deterministic cross-repository dispatch receipts for Alina SmartFlow."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping


DISPATCH_STATUSES = frozenset({"DISPATCHED", "RUNNING", "COMPLETE", "FAILED", "BLOCKED", "CANCELLED"})
TERMINAL_DISPATCH_STATUSES = frozenset({"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"})

from hl_observer.control_plane.phase_state import sha256_json, parse_iso_utc

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def generate_request_id(
    operator_intent: str,
    main_code_sha: str,
    requested_phase_epoch: int,
    campaign_kind: str,
    normalized_config: Mapping[str, Any],
) -> str:
    payload = {
        "operator_intent": operator_intent,
        "main_code_sha": main_code_sha,
        "requested_phase_epoch": requested_phase_epoch,
        "campaign_kind": campaign_kind,
        "config": dict(normalized_config),
    }
    return sha256_json(payload)


@dataclass(frozen=True)
class DispatchReceipt:
    request_id: str
    campaign_id: str
    main_code_sha: str
    dataset_repo_sha: str
    creation_phase: str
    phase_epoch: int
    source_collection_epoch: int | None
    workflow_run_id: str | None
    dispatched_at_utc: str
    status: str = "DISPATCHED"
    terminal_at_utc: str | None = None
    failure_code: str | None = None
    terminal_evidence_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_digest(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DispatchReceipt:
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown dispatch receipt fields: {sorted(unknown)}")
        payload = dict(raw)
        # v1 receipts had no lifecycle fields. Preserve their meaning while
        # upgrading them into the explicit v2 state machine.
        if "status" not in payload:
            payload["status"] = "COMPLETE" if payload.get("terminal_evidence_digest") else "DISPATCHED"
        if payload.get("status") == "COMPLETE" and "terminal_at_utc" not in payload:
            payload["terminal_at_utc"] = payload.get("dispatched_at_utc")
        return cls(**payload)


def validate_dispatch_receipt(receipt: DispatchReceipt) -> None:
    """Fail closed on incomplete or contradictory cross-repository identity."""
    if not receipt.request_id or not receipt.campaign_id:
        raise ValueError("dispatch receipt requires request_id and campaign_id")
    if not _SHA40.fullmatch(str(receipt.main_code_sha or "").lower()):
        raise ValueError("dispatch receipt requires an exact main repository SHA")
    if not _SHA40.fullmatch(str(receipt.dataset_repo_sha or "").lower()):
        raise ValueError("dispatch receipt requires an exact dataset repository SHA")
    if receipt.creation_phase not in {"IDLE", "COLLECT", "ANALYZE"}:
        raise ValueError("dispatch receipt has invalid creation phase")
    if not isinstance(receipt.phase_epoch, int) or receipt.phase_epoch < 1:
        raise ValueError("dispatch receipt has invalid phase epoch")
    if receipt.creation_phase == "ANALYZE":
        if not isinstance(receipt.source_collection_epoch, int) or isinstance(receipt.source_collection_epoch, bool) or receipt.source_collection_epoch < 1:
            raise ValueError("analysis dispatch requires source collection epoch")
    elif receipt.source_collection_epoch is not None:
        raise ValueError("non-analysis dispatch must not bind a source collection epoch")
    parse_iso_utc(receipt.dispatched_at_utc)
    if receipt.status not in DISPATCH_STATUSES:
        raise ValueError(f"dispatch receipt has invalid status: {receipt.status}")
    is_terminal = receipt.status in TERMINAL_DISPATCH_STATUSES
    if is_terminal != (receipt.terminal_at_utc is not None):
        raise ValueError("terminal dispatch status requires terminal_at_utc, and non-terminal status forbids it")
    if receipt.terminal_at_utc is not None:
        parse_iso_utc(receipt.terminal_at_utc)
    if receipt.status == "FAILED" and not receipt.failure_code:
        raise ValueError("failed dispatch receipt requires failure_code")
    if receipt.status != "FAILED" and receipt.failure_code is not None:
        raise ValueError("failure_code is only valid for FAILED dispatches")
    if receipt.status == "COMPLETE" and not _SHA256.fullmatch(str(receipt.terminal_evidence_digest or "").lower()):
        raise ValueError("complete dispatch receipt requires an exact terminal evidence digest")
    if receipt.status != "COMPLETE" and receipt.terminal_evidence_digest is not None:
        raise ValueError("terminal evidence digest is only valid for COMPLETE dispatches")
