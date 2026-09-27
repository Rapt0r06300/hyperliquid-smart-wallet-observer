"""Authoritative Phase State Schema (Version 1) for Alina SmartFlow."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import hashlib
from typing import Any, Mapping

SCHEMA_VERSION = 1
VALID_PHASES = frozenset({"IDLE", "COLLECT", "ANALYZE"})
VALID_ANALYSIS_STAGES = frozenset({"DRAIN", "QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD", "DONE", None})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def parse_iso_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"Timestamp must be UTC ISO-8601 ending in Z, got: {value}")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo != timezone.utc:
        raise ValueError(f"Timestamp timezone must be UTC, got: {dt.tzinfo}")
    return dt


@dataclass
class AlinaPhaseState:
    schema_version: int = SCHEMA_VERSION
    phase: str = "IDLE"
    epoch: int = 1
    requested_at_utc: str = field(default_factory=_now)
    collection_started_at_utc: str | None = None
    collection_cutoff_at_utc: str | None = None
    source_collection_epoch: int | None = None
    analysis_stage: str | None = None
    requested_by: str = "operator"
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_digest(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AlinaPhaseState:
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown phase state fields: {sorted(unknown)}")

        # Check required fields presence in dict if loading from external JSON
        for req in ("schema_version", "phase", "epoch", "requested_at_utc", "requested_by"):
            if req not in raw:
                raise ValueError(f"Missing required phase state field: {req}")

        obj = cls(**dict(raw))
        validate_phase_state(obj)
        return obj


def validate_phase_state(state: AlinaPhaseState) -> None:
    if state.schema_version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported phase schema version: {state.schema_version}")

    if state.phase not in VALID_PHASES:
        raise ValueError(f"Invalid phase: {state.phase}, must be one of {VALID_PHASES}")

    if not isinstance(state.epoch, int) or state.epoch < 1:
        raise ValueError(f"Epoch must be positive integer, got: {state.epoch}")

    parse_iso_utc(state.requested_at_utc)

    if state.collection_started_at_utc is not None:
        parse_iso_utc(state.collection_started_at_utc)

    if state.collection_cutoff_at_utc is not None:
        parse_iso_utc(state.collection_cutoff_at_utc)

    if state.analysis_stage not in VALID_ANALYSIS_STAGES:
        raise ValueError(f"Invalid analysis_stage: {state.analysis_stage}")

    # Phase-specific invariants
    if state.phase == "COLLECT":
        if state.collection_started_at_utc is None:
            raise ValueError("COLLECT phase requires collection_started_at_utc")
        if state.collection_cutoff_at_utc is not None:
            raise ValueError("COLLECT phase must have null collection_cutoff_at_utc")
        if state.source_collection_epoch is not None:
            raise ValueError("COLLECT phase must have null source_collection_epoch")
        if state.analysis_stage is not None:
            raise ValueError("COLLECT phase must have null analysis_stage")

    elif state.phase == "ANALYZE":
        if state.source_collection_epoch is None or not isinstance(state.source_collection_epoch, int) or state.source_collection_epoch < 1:
            raise ValueError("ANALYZE phase requires a valid positive integer source_collection_epoch")
        if state.collection_cutoff_at_utc is None:
            raise ValueError("ANALYZE phase requires collection_cutoff_at_utc")
        if state.analysis_stage is None:
            raise ValueError("ANALYZE phase requires an explicit analysis_stage")

    elif state.phase == "IDLE":
        if state.analysis_stage is not None:
            raise ValueError("IDLE phase must have null analysis_stage")
