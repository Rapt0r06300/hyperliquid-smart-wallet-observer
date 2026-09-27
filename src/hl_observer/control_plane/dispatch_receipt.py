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
