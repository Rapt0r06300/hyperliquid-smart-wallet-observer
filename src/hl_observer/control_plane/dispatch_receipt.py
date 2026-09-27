"""Deterministic cross-repository dispatch receipts for Alina SmartFlow."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from hl_observer.control_plane.phase_state import sha256_json, canonical_json, _now


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
        return cls(**dict(raw))


def validate_dispatch_receipt(receipt: DispatchReceipt) -> None:
    """Fail closed on incomplete or contradictory cross-repository identity."""
    if not receipt.request_id or not receipt.campaign_id:
        raise ValueError("dispatch receipt requires request_id and campaign_id")
    if not receipt.main_code_sha or not receipt.dataset_repo_sha:
        raise ValueError("dispatch receipt requires both repository SHAs")
    if receipt.creation_phase not in {"IDLE", "COLLECT", "ANALYZE"}:
        raise ValueError("dispatch receipt has invalid creation phase")
    if not isinstance(receipt.phase_epoch, int) or receipt.phase_epoch < 1:
        raise ValueError("dispatch receipt has invalid phase epoch")
    if receipt.creation_phase == "ANALYZE":
        if not isinstance(receipt.source_collection_epoch, int) or receipt.source_collection_epoch < 1:
            raise ValueError("analysis dispatch requires source collection epoch")
    if not receipt.dispatched_at_utc.endswith("Z"):
        raise ValueError("dispatch timestamp must be UTC")
