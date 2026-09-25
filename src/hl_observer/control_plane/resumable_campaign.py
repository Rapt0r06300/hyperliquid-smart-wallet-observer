"""Fail-closed resumable campaign protocol for GitHub-hosted workers."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
import secrets
from typing import Any, Mapping

SCHEMA_VERSION = "alina.resumable_campaign.v1"
CAMPAIGN_KINDS = frozenset({"market_collection","copy_vault_collection","official_archive_collection","event_intelligence_collection","replay","backtest","module_pnl_proof"})
ACTIVE_STATES = frozenset({"PENDING","RUNNING","CONTINUATION_REQUIRED"})
TERMINAL_STATES = frozenset({"COMPLETE","FAILED","UNAVAILABLE","PARTIAL","REJECT"})
ALL_STATES = ACTIVE_STATES | TERMINAL_STATES
_ALLOWED = {"PENDING":{"RUNNING","FAILED","UNAVAILABLE","REJECT"},"RUNNING":{"CONTINUATION_REQUIRED","COMPLETE","FAILED","UNAVAILABLE","PARTIAL","REJECT"},"CONTINUATION_REQUIRED":{"RUNNING","FAILED","UNAVAILABLE","PARTIAL","REJECT"}}
NON_RETRYABLE = frozenset({"SCHEMA","DIGEST","SAFETY","PROVENANCE","QUALITY","NONDETERMINISTIC","REPLAY_INCOMPATIBLE"})
RETRYABLE = frozenset({"INFRASTRUCTURE","TEMPORARY_EXTERNAL"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False)

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
    schema_version: str = SCHEMA_VERSION
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


def validate_manifest(m: CampaignManifest) -> None:
    if m.schema_version != SCHEMA_VERSION: raise ValueError("unsupported schema")
    if m.kind not in CAMPAIGN_KINDS: raise ValueError("unknown campaign kind")
    if m.status not in ALL_STATES: raise ValueError("invalid status")
    if not m.paper_only or not m.read_only or m.real_execution: raise ValueError("unsafe execution flags")
    for name in ("code_sha","config_sha256","work_plan_sha256"):
        if not getattr(m,name): raise ValueError(f"missing pinned {name}")
    if _parse_ts(m.expires_at) <= _parse_ts(m.created_at): raise ValueError("invalid expiry")
    if m.chunk_index < 0 or m.attempts < 0: raise ValueError("negative counters")
    for out in m.outputs:
        if out.get("quality_status") == "SAFE" and not out.get("replay_compatible", False):
            raise ValueError("SAFE output must be replay compatible")
        if out.get("quality_status") == "SAFE" and out.get("evidence_status") != "SAFE":
            raise ValueError("SAFE output lacks SAFE evidence")


def transition(m: CampaignManifest, target: str, reason: str, *, now: str | None = None) -> CampaignManifest:
    validate_manifest(m)
    if m.status in TERMINAL_STATES: raise ValueError("terminal manifest is immutable")
    if target not in _ALLOWED.get(m.status, set()): raise ValueError(f"invalid transition {m.status}->{target}")
    old = m.status
    m.status = target; m.status_reason = reason; m.updated_at = now or _now()
    m.history.append({"at":m.updated_at,"from":old,"to":target,"reason":reason})
    validate_manifest(m); return m


def work_unit_id(m: CampaignManifest, partition: Mapping[str, Any]) -> str:
    return sha256_json({"kind":m.kind,"code_sha":m.code_sha,"config":m.config_sha256,"dataset":m.dataset_generation,"partition":dict(partition)})


def complete_work_unit(m: CampaignManifest, unit_id: str, result_sha256: str, result: Mapping[str, Any]) -> bool:
    prior = m.completed_units.get(unit_id)
    if prior:
        if prior.get("sha256") != result_sha256: raise ValueError("work-unit checksum collision")
        return False
    m.completed_units[unit_id] = {"sha256":result_sha256,"result":dict(result)}
    m.updated_at = _now(); return True


def acquire_lease(m: CampaignManifest, owner_run_id: str, ttl_s: int, *, now: str | None = None) -> str:
    from datetime import timedelta
    current = _parse_ts(now or _now())
    if m.lease and _parse_ts(m.lease["expires_at"]) > current: raise ValueError("active lease")
    token = secrets.token_urlsafe(32)
    expires = current + timedelta(seconds=max(60, ttl_s))
    m.lease = {"owner_run_id":str(owner_run_id),"lease_token_sha256":hashlib.sha256(token.encode()).hexdigest(),"acquired_at":current.isoformat().replace("+00:00","Z"),"expires_at":expires.isoformat().replace("+00:00","Z")}
    return token


def verify_lease(m: CampaignManifest, token: str, *, now: str | None = None) -> bool:
    if not m.lease: return False
    current = _parse_ts(now or _now())
    return current < _parse_ts(m.lease["expires_at"]) and secrets.compare_digest(m.lease["lease_token_sha256"], hashlib.sha256(token.encode()).hexdigest())


def release_lease(m: CampaignManifest, token: str) -> None:
    if not verify_lease(m, token): raise ValueError("stale lease")
    m.lease = None; m.updated_at = _now()


def classify_failure(category: str) -> bool:
    if category in NON_RETRYABLE: return False
    if category in RETRYABLE: return True
    return False


def mark_continuation(m: CampaignManifest, reason: str, *, progressed: bool, next_due_at: str | None = None) -> CampaignManifest:
    limits = StopLimits(**m.limits)
    m.chunk_index += 1; m.attempts += 1
    m.no_progress_count = 0 if progressed else m.no_progress_count + 1
    if m.chunk_index >= limits.max_chunks or m.attempts >= limits.max_attempts or m.no_progress_count >= limits.max_no_progress:
        return transition(m, "FAILED", "stop_limit_reached")
    transition(m, "CONTINUATION_REQUIRED", reason); m.next_due_at = next_due_at; m.lease = None; return m


def mark_terminal(m: CampaignManifest, status: str, reason: str) -> CampaignManifest:
    if status not in TERMINAL_STATES: raise ValueError("not terminal")
    m.lease = None; return transition(m, status, reason)


def select_due_campaigns(items: list[CampaignManifest], *, now: str | None = None) -> list[CampaignManifest]:
    current = _parse_ts(now or _now()); due=[]
    for m in items:
        if m.status not in ACTIVE_STATES: continue
        if _parse_ts(m.expires_at) <= current: continue
        if m.lease and _parse_ts(m.lease["expires_at"]) > current: continue
        if m.next_due_at and _parse_ts(m.next_due_at) > current: continue
        due.append(m)
    return sorted(due, key=lambda x:x.campaign_id)
