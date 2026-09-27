"""Fail-closed resumable campaign protocol for GitHub-hosted workers."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
import secrets
from typing import Any, Mapping

SCHEMA_VERSION = "alina.resumable_campaign.v1"
SCHEMA_VERSION_V1 = "alina.resumable_campaign.v1"
SCHEMA_VERSION_V2 = "alina.resumable_campaign.v2"
SUPPORTED_SCHEMAS = frozenset({SCHEMA_VERSION_V1, SCHEMA_VERSION_V2})

COLLECT_CAMPAIGN_KINDS = frozenset({
    "market_collection", "copy_vault_collection",
    "official_archive_collection", "event_intelligence_collection",
})
ANALYZE_CAMPAIGN_KINDS = frozenset({
    "replay", "backtest", "oos", "forward_paper",
    "module_pnl_proof", "scoreboard",
})
CAMPAIGN_KINDS = COLLECT_CAMPAIGN_KINDS | ANALYZE_CAMPAIGN_KINDS
CAMPAIGN_KIND_ORDER = (
    "scoreboard", "module_pnl_proof", "forward_paper", "oos",
    "backtest", "replay", "market_collection", "copy_vault_collection",
    "event_intelligence_collection", "official_archive_collection",
)
ACTIVE_STATES = frozenset({"PENDING", "RUNNING", "CONTINUATION_REQUIRED", "STUCK"})
TERMINAL_STATES = frozenset({"COMPLETE", "FAILED", "UNAVAILABLE", "PARTIAL", "REJECT"})
ALL_STATES = ACTIVE_STATES | TERMINAL_STATES
_ALLOWED = {
    "PENDING": {"RUNNING", "FAILED", "UNAVAILABLE", "REJECT"},
    "RUNNING": {"CONTINUATION_REQUIRED", "STUCK", "COMPLETE", "FAILED", "UNAVAILABLE", "PARTIAL", "REJECT"},
    "CONTINUATION_REQUIRED": {"RUNNING", "STUCK", "FAILED", "UNAVAILABLE", "PARTIAL", "REJECT"},
    "STUCK": {"RUNNING", "FAILED", "UNAVAILABLE", "PARTIAL", "REJECT"},
}
NON_RETRYABLE = frozenset({
    "SCHEMA", "DIGEST", "SAFETY", "PROVENANCE", "QUALITY",
    "NONDETERMINISTIC", "REPLAY_INCOMPATIBLE",
})
RETRYABLE = frozenset({"INFRASTRUCTURE", "TEMPORARY_EXTERNAL"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class StopLimits:
    max_attempts: int = 12
    max_chunks: int = 24
    max_wall_clock_s: int = 86400
    max_consecutive_failures: int = 4
    max_no_progress: int = 3


@dataclass
class CampaignManifest:
    campaign_id: str
    kind: str
    code_repo: str
    code_sha: str
    dataset_repo: str
    dataset_generation: str
    config_sha256: str
    work_plan_sha256: str
    expires_at: str
    schema_version: str = SCHEMA_VERSION_V1
    status: str = "PENDING"
    status_reason: str = "created"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    chunk_index: int = 0
    attempts: int = 0
    consecutive_failures: int = 0
    no_progress_count: int = 0
    next_due_at: str | None = None
    cursor: dict[str, Any] = field(default_factory=dict)
    completed_units: dict[str, dict[str, Any]] = field(default_factory=dict)
    lease: dict[str, Any] | None = None
    outputs: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    paper_only: bool = True
    read_only: bool = True
    real_execution: bool = False
    limits: dict[str, int] = field(default_factory=lambda: asdict(StopLimits()))
    creation_phase: str | None = None
    phase_epoch: int | None = None
    source_collection_epoch: int | None = None
    collection_cutoff_at_utc: str | None = None
    dataset_selection_id: str | None = None
    checkpoint_lineage: list[dict[str, Any]] = field(default_factory=list)
    terminal_evidence_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CampaignManifest":
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown manifest fields: {sorted(unknown)}")
        obj = cls(**dict(raw))
        validate_manifest(obj)
        return obj
