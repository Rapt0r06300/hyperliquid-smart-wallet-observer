"""Fail-closed resumable campaign protocol for GitHub-hosted workers."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import re
from typing import Any, Mapping

SCHEMA_VERSION = "alina.resumable_campaign.v1"
SCHEMA_VERSION_V1 = "alina.resumable_campaign.v1"
SCHEMA_VERSION_V2 = "alina.resumable_campaign.v2"
SUPPORTED_SCHEMAS = frozenset({SCHEMA_VERSION_V1, SCHEMA_VERSION_V2})

COLLECT_CAMPAIGN_KINDS = frozenset({"market_collection","copy_vault_collection","official_archive_collection","event_intelligence_collection"})
ANALYZE_CAMPAIGN_KINDS = frozenset({"replay","backtest","oos","forward_paper","module_pnl_proof","scoreboard"})
ANALYSIS_STAGE_BY_KIND = {
    "replay": "REPLAY",
    "backtest": "BACKTEST",
    "oos": "OOS",
    "forward_paper": "FORWARD_PAPER",
    "module_pnl_proof": "PNL_PROOF",
    "scoreboard": "SCOREBOARD",
}
CAMPAIGN_KINDS = frozenset({"market_collection","copy_vault_collection","official_archive_collection","event_intelligence_collection","replay","backtest","oos","forward_paper","module_pnl_proof","scoreboard"})
CAMPAIGN_KIND_ORDER = ("scoreboard","module_pnl_proof","forward_paper","oos","backtest","replay","market_collection","copy_vault_collection","event_intelligence_collection","official_archive_collection")
ACTIVE_STATES = frozenset({"PENDING","RUNNING","CONTINUATION_REQUIRED","STUCK"})
TERMINAL_STATES = frozenset({"COMPLETE","FAILED","UNAVAILABLE","PARTIAL","REJECT"})
ALL_STATES = ACTIVE_STATES | TERMINAL_STATES
_ALLOWED = {
    "PENDING":{"RUNNING","FAILED","UNAVAILABLE","REJECT"},
    "RUNNING":{"CONTINUATION_REQUIRED","STUCK","COMPLETE","FAILED","UNAVAILABLE","PARTIAL","REJECT"},
    "CONTINUATION_REQUIRED":{"RUNNING","STUCK","FAILED","UNAVAILABLE","PARTIAL","REJECT"},
    "STUCK":{"RUNNING","FAILED","UNAVAILABLE","PARTIAL","REJECT"},
}
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

    # Schema V2 fields
    creation_phase: str | None = None
    phase_epoch: int | None = None
    source_collection_epoch: int | None = None
    collection_cutoff_at_utc: str | None = None
    dataset_selection_id: str | None = None
    analysis_stage: str | None = None
    operator_request_id: str | None = None
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


def validate_manifest(m: CampaignManifest) -> None:
    if m.schema_version not in SUPPORTED_SCHEMAS:
        raise ValueError(f"unsupported schema: {m.schema_version}")
    if m.kind not in CAMPAIGN_KINDS:
        raise ValueError("unknown campaign kind")
    if m.operator_request_id is not None and (
        not isinstance(m.operator_request_id, str)
        or not re.fullmatch(r"[0-9a-f]{64}", m.operator_request_id)
    ):
        raise ValueError("invalid operator_request_id")
    if m.status not in ALL_STATES:
        raise ValueError("invalid status")
    if not m.paper_only or not m.read_only or m.real_execution:
        raise ValueError("unsafe execution flags")
    for name in ("code_sha", "config_sha256", "work_plan_sha256"):
        if not getattr(m, name):
            raise ValueError(f"missing pinned {name}")
    if _parse_ts(m.expires_at) <= _parse_ts(m.created_at):
        raise ValueError("invalid expiry")
    if m.chunk_index < 0 or m.attempts < 0:
        raise ValueError("negative counters")

    # Schema V2 Specific Validations
    if m.schema_version == SCHEMA_VERSION_V2:
        if m.creation_phase not in ("COLLECT", "ANALYZE", "IDLE"):
            raise ValueError("V2 manifest must specify valid creation_phase")
        if m.creation_phase == "COLLECT" and m.kind not in COLLECT_CAMPAIGN_KINDS:
            raise ValueError("COLLECT manifest has analysis-only or unknown kind")
        if m.creation_phase == "ANALYZE" and m.kind not in ANALYZE_CAMPAIGN_KINDS:
            raise ValueError("ANALYZE manifest has collection-only or unknown kind")
        if m.creation_phase == "IDLE":
            raise ValueError("V2 campaign cannot be created in IDLE")
        if not isinstance(m.phase_epoch, int) or m.phase_epoch < 1:
            raise ValueError("V2 manifest requires positive integer phase_epoch")
        if m.creation_phase == "ANALYZE":
            if not isinstance(m.source_collection_epoch, int) or m.source_collection_epoch < 1:
                raise ValueError("V2 ANALYZE manifest requires positive integer source_collection_epoch")
            if not m.collection_cutoff_at_utc:
                raise ValueError("V2 ANALYZE manifest requires collection_cutoff_at_utc")
            if not m.dataset_selection_id:
                raise ValueError("V2 ANALYZE manifest requires dataset_selection_id")
            expected_stage = ANALYSIS_STAGE_BY_KIND.get(m.kind)
            if expected_stage and m.analysis_stage not in (None, expected_stage):
                raise ValueError("ANALYZE manifest analysis_stage does not match campaign kind")
        if m.status in TERMINAL_STATES:
            digest = str(m.terminal_evidence_digest or "")
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
                raise ValueError("V2 terminal manifest requires terminal_evidence_digest")

    for out in m.outputs:
        if out.get("quality_status") == "SAFE" and not out.get("replay_compatible", False):
            raise ValueError("SAFE output must be replay compatible")
        if out.get("quality_status") == "SAFE" and out.get("evidence_status") != "SAFE":
            raise ValueError("SAFE output lacks SAFE evidence")


def transition(m: CampaignManifest, target: str, reason: str, *, now: str | None = None) -> CampaignManifest:
    validate_manifest(m)
    if m.status in TERMINAL_STATES:
        raise ValueError("terminal manifest is immutable")
    if target not in _ALLOWED.get(m.status, set()):
        raise ValueError(f"invalid transition {m.status}->{target}")
    old = m.status
    m.status = target
    m.status_reason = reason
    m.updated_at = now or _now()
    m.history.append({"at": m.updated_at, "from": old, "to": target, "reason": reason})
    validate_manifest(m)
    return m


def work_unit_id(m: CampaignManifest, partition: Mapping[str, Any]) -> str:
    return sha256_json({"kind": m.kind, "code_sha": m.code_sha, "config": m.config_sha256, "dataset": m.dataset_generation, "partition": dict(partition)})


def complete_work_unit(m: CampaignManifest, unit_id: str, result_sha256: str, result: Mapping[str, Any]) -> bool:
    prior = m.completed_units.get(unit_id)
    if prior:
        if prior.get("sha256") != result_sha256:
            raise ValueError("work-unit checksum collision")
        return False
    m.completed_units[unit_id] = {"sha256": result_sha256, "result": dict(result)}
    m.updated_at = _now()
    return True


def acquire_lease(
    m: CampaignManifest,
    owner_run_id: str,
    ttl_s: int,
    *,
    expected_phase: str | None = None,
    expected_epoch: int | None = None,
    now: str | None = None,
) -> str:
    current = _parse_ts(now or _now())

    # V1 manifests remain readable as historical evidence, but cannot acquire
    # a lease or mutate durable campaign state after the V2 cutover.
    if m.schema_version == SCHEMA_VERSION_V1:
        raise ValueError("V1 manifest is immutable; migrate to V2 before execution")

    # Phase/Epoch Guard for V2
    if m.schema_version == SCHEMA_VERSION_V2:
        if expected_phase is not None and m.creation_phase != expected_phase:
            raise ValueError(f"Phase mismatch: manifest={m.creation_phase}, current={expected_phase}")
        if expected_epoch is not None and m.phase_epoch != expected_epoch:
            pinned_collect_continuation = (
                expected_phase == "COLLECT"
                and m.creation_phase == "COLLECT"
                and isinstance(m.phase_epoch, int)
                and m.phase_epoch < expected_epoch
            )
            if not pinned_collect_continuation:
                raise ValueError(f"Stale phase epoch: manifest={m.phase_epoch}, current={expected_epoch}")

    if m.lease and _parse_ts(m.lease["expires_at"]) > current:
        raise ValueError("active lease")

    token = secrets.token_urlsafe(32)
    expires = current + timedelta(seconds=max(60, ttl_s))
    m.lease = {
        "owner_run_id": str(owner_run_id),
        "lease_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "acquired_at": current.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
    }
    return token


def verify_lease(m: CampaignManifest, token: str, *, now: str | None = None) -> bool:
    if not m.lease:
        return False
    current = _parse_ts(now or _now())
    return current < _parse_ts(m.lease["expires_at"]) and secrets.compare_digest(m.lease["lease_token_sha256"], hashlib.sha256(token.encode()).hexdigest())


def release_lease(m: CampaignManifest, token: str) -> None:
    if not verify_lease(m, token):
        raise ValueError("stale lease")
    m.lease = None
    m.updated_at = _now()


def classify_failure(category: str) -> bool:
    if category in NON_RETRYABLE:
        return False
    if category in RETRYABLE:
        return True
    return False


def mark_continuation(
    m: CampaignManifest,
    reason: str,
    *,
    progressed: bool,
    next_due_at: str | None = None,
    failure: bool = False,
    checkpoint: Mapping[str, Any] | None = None,
    now: str | None = None,
) -> CampaignManifest:
    limits = StopLimits(**m.limits)
    current = _parse_ts(now or _now())
    m.chunk_index += 1
    m.attempts += 1
    m.no_progress_count = 0 if progressed else m.no_progress_count + 1
    m.consecutive_failures = m.consecutive_failures + 1 if failure else 0
    wall_clock_s = max(0.0, (current - _parse_ts(m.created_at)).total_seconds())

    if checkpoint:
        ckpt_entry = dict(checkpoint)
        ckpt_entry["at"] = current.isoformat().replace("+00:00", "Z")
        ckpt_entry["digest"] = sha256_json(ckpt_entry)
        m.checkpoint_lineage.append(ckpt_entry)

    stop = (
        m.chunk_index >= limits.max_chunks
        or m.attempts >= limits.max_attempts
        or m.no_progress_count >= limits.max_no_progress
        or m.consecutive_failures >= limits.max_consecutive_failures
        or wall_clock_s >= limits.max_wall_clock_s
        or current >= _parse_ts(m.expires_at)
    )
    current_text = current.isoformat().replace("+00:00", "Z")
    if stop:
        if failure:
            transition(m, "STUCK", reason or "bounded_retry_exhausted", now=current_text)
            # A stuck campaign is actionable, not terminal. The controller may retry
            # it after a durable cooldown without spinning in a hot loop.
            m.next_due_at = (current + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        else:
            return mark_terminal(m, "FAILED", "stop_limit_reached")
    else:
        transition(m, "CONTINUATION_REQUIRED", reason, now=current_text)
        m.next_due_at = next_due_at
    m.lease = None
    return m


def mark_terminal(m: CampaignManifest, status: str, reason: str, terminal_digest: str | None = None) -> CampaignManifest:
    if status not in TERMINAL_STATES:
        raise ValueError("not terminal")
    m.lease = None
    m.terminal_evidence_digest = terminal_digest or sha256_json(
        {
            "campaign_id": m.campaign_id,
            "status": status,
            "reason": str(reason),
            "completed_units": m.completed_units,
            "checkpoint_lineage": m.checkpoint_lineage,
        }
    )
    return transition(m, status, reason)


def select_due_campaigns(
    items: list[CampaignManifest],
    *,
    current_phase: str | None = None,
    current_epoch: int | None = None,
    current_analysis_stage: str | None = None,
    now: str | None = None,
) -> list[CampaignManifest]:
    current = _parse_ts(now or _now())
    buckets: dict[str, list[CampaignManifest]] = {kind: [] for kind in CAMPAIGN_KIND_ORDER}
    for m in items:
        # V1 remains readable evidence but is never executable after cutover.
        if m.schema_version != SCHEMA_VERSION_V2:
            continue
        if m.status not in ACTIVE_STATES:
            continue
        if _parse_ts(m.expires_at) <= current:
            continue
        if m.lease and _parse_ts(m.lease["expires_at"]) > current:
            continue
        if m.next_due_at and _parse_ts(m.next_due_at) > current:
            continue

        # V2 phase/epoch gating
        if m.schema_version == SCHEMA_VERSION_V2:
            if current_phase is not None and m.creation_phase != current_phase:
                continue
            if current_epoch is not None and m.phase_epoch != current_epoch:
                if not (
                    current_phase == "COLLECT"
                    and m.creation_phase == "COLLECT"
                    and isinstance(m.phase_epoch, int)
                    and m.phase_epoch < current_epoch
                ):
                    continue
            if current_phase == "COLLECT" and m.kind not in COLLECT_CAMPAIGN_KINDS:
                continue
            if current_phase == "ANALYZE" and m.kind not in ANALYZE_CAMPAIGN_KINDS:
                continue
            if (
                current_phase == "ANALYZE"
                and current_analysis_stage is not None
                and ANALYSIS_STAGE_BY_KIND.get(m.kind) != current_analysis_stage
            ):
                continue

        buckets.setdefault(m.kind, []).append(m)

    for rows in buckets.values():
        rows.sort(key=lambda x: (x.next_due_at or x.created_at, x.created_at, x.campaign_id))

    ordered: list[CampaignManifest] = []
    while any(buckets.values()):
        for kind in CAMPAIGN_KIND_ORDER:
            rows = buckets.get(kind, [])
            if rows:
                ordered.append(rows.pop(0))
    return ordered
