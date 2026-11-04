"""Fail-closed resumable campaign protocol for GitHub-hosted workers."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import secrets
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from hl_observer.strategies.active_scope import require_active_strategy

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


def _is_exact_int(value: Any, *, minimum: int = 0) -> bool:
    """Return true only for a real integer, never for bool or coercible text."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value.lower())
    )


def require_campaign_economic_scope(m: CampaignManifest) -> str | None:
    """Require an explicit canonical active family before executing ANALYZE work."""
    if (
        m.schema_version != SCHEMA_VERSION_V2
        or m.creation_phase != "ANALYZE"
        or m.kind not in ANALYZE_CAMPAIGN_KINDS
    ):
        return None
    cursor = m.cursor if isinstance(m.cursor, Mapping) else {}
    family = cursor.get("strategy_family")
    if not isinstance(family, str) or not family.strip():
        raise ValueError(
            f"DISABLED_BY_SCOPE:campaign={m.campaign_id}:missing_strategy_family"
        )
    try:
        canonical = require_active_strategy(family)
    except ValueError as exc:
        raise ValueError(
            f"DISABLED_BY_SCOPE:campaign={m.campaign_id}:{exc}"
        ) from exc
    if family != canonical:
        raise ValueError(
            f"DISABLED_BY_SCOPE:campaign={m.campaign_id}:noncanonical_family={family}"
        )
    return canonical


def _require_mutable_manifest(m: CampaignManifest) -> None:
    if m.schema_version == SCHEMA_VERSION_V1:
        raise ValueError("V1 manifest is immutable; historical evidence is read-only")

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
    def from_dict(cls, raw: Mapping[str, Any]) -> CampaignManifest:
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
    if m.paper_only is not True or m.read_only is not True or m.real_execution is not False:
        raise ValueError("unsafe execution flags")
    for name in ("code_sha", "config_sha256", "work_plan_sha256"):
        if not getattr(m, name):
            raise ValueError(f"missing pinned {name}")
    if _parse_ts(m.expires_at) <= _parse_ts(m.created_at):
        raise ValueError("invalid expiry")
    for name in (
        "chunk_index",
        "attempts",
        "consecutive_failures",
        "no_progress_count",
    ):
        if not _is_exact_int(getattr(m, name), minimum=0):
            raise ValueError(f"invalid non-negative counter: {name}")
    if not isinstance(m.limits, Mapping):
        raise ValueError("limits must be a mapping")
    for name in (
        "max_attempts",
        "max_chunks",
        "max_wall_clock_s",
        "max_consecutive_failures",
        "max_no_progress",
    ):
        if not _is_exact_int(m.limits.get(name), minimum=1):
            raise ValueError(f"invalid positive stop limit: {name}")

    # Schema V2 Specific Validations
    if m.schema_version == SCHEMA_VERSION_V2:
        # The retired external data repository is never a valid operational
        # source. V1 legacy manifests remain readable for audit, but V2
        # workers must not consume or create cross-repository campaigns.
        canonical = "Rapt0r06300/hyperliquid-smart-wallet-observer"
        if m.code_repo != canonical or m.dataset_repo != canonical:
            raise ValueError("V2 campaign must use the canonical Alina repository")
        if m.creation_phase not in ("COLLECT", "ANALYZE", "IDLE"):
            raise ValueError("V2 manifest must specify valid creation_phase")
        if m.creation_phase == "COLLECT" and m.kind not in COLLECT_CAMPAIGN_KINDS:
            raise ValueError("COLLECT manifest has analysis-only or unknown kind")
        if m.creation_phase == "ANALYZE" and m.kind not in ANALYZE_CAMPAIGN_KINDS:
            raise ValueError("ANALYZE manifest has collection-only or unknown kind")
        if m.creation_phase == "IDLE":
            raise ValueError("V2 campaign cannot be created in IDLE")
        if not _is_exact_int(m.phase_epoch, minimum=1):
            raise ValueError("V2 manifest requires positive integer phase_epoch")
        if m.creation_phase == "ANALYZE":
            if not _is_exact_int(m.source_collection_epoch, minimum=1):
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
    _require_mutable_manifest(m)
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
    _require_mutable_manifest(m)
    validate_manifest(m)
    if not isinstance(unit_id, str) or not unit_id.strip():
        raise ValueError("work-unit id must be a non-empty string")
    if not _is_sha256_hex(result_sha256):
        raise ValueError("work-unit result_sha256 must be a SHA-256 digest")
    if not isinstance(result, Mapping):
        raise ValueError("work-unit result must be a mapping")
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
    if not _is_exact_int(ttl_s, minimum=1):
        raise ValueError("lease ttl_s must be a positive integer")
    current = _parse_ts(now or _now())

    # V1 manifests remain readable as historical evidence but cannot be executed.
    _require_mutable_manifest(m)

    require_campaign_economic_scope(m)

    # Phase/Epoch Guard for V2
    if m.schema_version == SCHEMA_VERSION_V2:
        if expected_phase is not None and m.creation_phase != expected_phase:
            raise ValueError(f"Phase mismatch: manifest={m.creation_phase}, current={expected_phase}")
        if expected_epoch is not None and m.phase_epoch != expected_epoch:
            # A claimed pre-transition unit may finish, but no old-epoch
            # campaign may acquire a fresh lease in a later COLLECT epoch.
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
    _require_mutable_manifest(m)
    if not verify_lease(m, token):
        raise ValueError("stale lease")
    m.lease = None
    m.updated_at = _now()


def classify_failure(category: str) -> bool:
    return category in RETRYABLE


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
    _require_mutable_manifest(m)
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
    _require_mutable_manifest(m)
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
    # Shell workflows commonly represent an absent optional stage as an empty
    # string.  Treat it as absent at the domain boundary so COLLECT/ANALYZE
    # selection remains fail-closed without rejecting an otherwise valid wave.
    current_analysis_stage = current_analysis_stage or None
    if current_phase not in (None, "COLLECT", "ANALYZE"):
        raise ValueError("invalid current phase")
    if current_epoch is not None and not _is_exact_int(current_epoch, minimum=1):
        raise ValueError("current_epoch must be a positive integer")
    if current_analysis_stage is not None and current_analysis_stage not in set(ANALYSIS_STAGE_BY_KIND.values()):
        raise ValueError("invalid current analysis stage")
    current = _parse_ts(now or _now())
    buckets: dict[str, list[CampaignManifest]] = {kind: [] for kind in CAMPAIGN_KIND_ORDER}
    for m in items:
        def refuse(reason: str) -> None:
            logging.warning(
                "campaign_refused id=%s reason=%s manifest_phase=%s manifest_epoch=%s "
                "source_collection_epoch=%s analysis_stage=%s current_phase=%s "
                "current_epoch=%s current_analysis_stage=%s",
                m.campaign_id,
                reason,
                m.creation_phase,
                m.phase_epoch,
                m.source_collection_epoch,
                m.analysis_stage,
                current_phase,
                current_epoch,
                current_analysis_stage,
            )

        try:
            validate_manifest(m)
        except (TypeError, ValueError, KeyError) as exc:
            refuse(f"INVALID_MANIFEST:{exc}")
            continue
        # V1 remains readable evidence but is never executable after cutover.
        if m.schema_version != SCHEMA_VERSION_V2:
            refuse("LEGACY_SCHEMA_READ_ONLY")
            continue
        try:
            require_campaign_economic_scope(m)
        except ValueError as exc:
            refuse(f"DISABLED_BY_SCOPE:{exc}")
            continue
        if m.status not in ACTIVE_STATES:
            refuse(f"STATUS_NOT_ACTIVE:{m.status}")
            continue
        if _parse_ts(m.expires_at) <= current:
            refuse("EXPIRED")
            continue
        if m.lease and _parse_ts(m.lease["expires_at"]) > current:
            refuse("LEASE_ACTIVE")
            continue
        if m.next_due_at and _parse_ts(m.next_due_at) > current:
            refuse("NOT_DUE")
            continue

        # V2 phase/epoch gating
        if m.schema_version == SCHEMA_VERSION_V2:
            if current_phase is not None and m.creation_phase != current_phase:
                refuse("PHASE_MISMATCH")
                continue
            if current_epoch is not None and m.phase_epoch != current_epoch:
                # Prior-epoch campaigns are audit evidence, not live work.
                # Do not requeue them while another COLLECT epoch runs.
                refuse("PHASE_EPOCH_MISMATCH")
                continue
            if current_phase == "COLLECT" and m.kind not in COLLECT_CAMPAIGN_KINDS:
                refuse("COLLECT_KIND_NOT_ALLOWED")
                continue
            if current_phase == "ANALYZE" and m.kind not in ANALYZE_CAMPAIGN_KINDS:
                refuse("ANALYZE_KIND_NOT_ALLOWED")
                continue
            if (
                current_phase == "ANALYZE"
                and current_analysis_stage is not None
                and ANALYSIS_STAGE_BY_KIND.get(m.kind) != current_analysis_stage
            ):
                refuse("ANALYSIS_STAGE_MISMATCH")
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


def _campaign_base(status: str, **values: Any) -> dict[str, Any]:
    """Return paper/read-only campaign evidence without changing a manifest."""
    return {"status": status, "paper_read_only": True, "real_execution": False, "manifest_mutation": False, "closure_allowed": False, **values}


def _campaign_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _campaign_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _campaign_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def campaign_state_safety_receipt(manifest: Any) -> dict[str, Any]:
    try:
        candidate = manifest if isinstance(manifest, CampaignManifest) else CampaignManifest.from_dict(manifest)
        validate_manifest(candidate)
    except (TypeError, ValueError):
        return _campaign_base("REJECTED", verdict="CAMPAIGN_MANIFEST_INVALID", fail_closed=True)
    return _campaign_base("PROVEN", verdict="CAMPAIGN_MANIFEST_VALID", campaign_id=candidate.campaign_id, status_value=candidate.status, fail_closed=False)


def scoreboard_to_resumable_boundary_receipt(scoreboard_result: Any, campaign_manifest: Any) -> dict[str, Any]:
    """Admit scoreboard evidence to a resumable campaign without promoting it."""
    from hl_observer.simulation.scoreboard_promotion import scoreboard_promotion_safety_receipt

    scoreboard = scoreboard_promotion_safety_receipt(scoreboard_result)
    campaign = campaign_state_safety_receipt(campaign_manifest)
    valid = (
        scoreboard.get("status") == "PROVEN"
        and scoreboard.get("paper_read_only") is True
        and scoreboard.get("real_execution") is False
        and scoreboard.get("promotion") == "DISABLED_UNTIL_REVIEW"
        and scoreboard.get("fail_closed") is False
        and campaign.get("status") == "PROVEN"
        and campaign.get("paper_read_only") is True
        and campaign.get("real_execution") is False
        and campaign.get("manifest_mutation") is False
        and campaign.get("fail_closed") is False
    )
    return _campaign_base(
        "PROVEN" if valid else "REJECTED",
        verdict="SCOREBOARD_CAMPAIGN_BOUNDARY_SAFE" if valid else "SCOREBOARD_CAMPAIGN_BOUNDARY_REJECTED",
        scoreboard_status=scoreboard.get("status"),
        campaign_status=campaign.get("status"),
        promotion_disabled=True,
        phase_mutation=False,
        fail_closed=not valid,
    )


def native_venue_to_campaign_boundary_receipt(
    venue_result: Any,
    campaign_manifest: Any,
) -> dict[str, Any]:
    """Admit Bybit public capabilities to a resumable paper campaign."""
    from hl_observer.venues.bybit import venue_capability_safety_receipt

    venue = venue_capability_safety_receipt(venue_result)
    campaign = campaign_state_safety_receipt(campaign_manifest)
    valid = (
        venue.get("status") == "PROVEN"
        and venue.get("paper_read_only") is True
        and venue.get("real_execution") is False
        and venue.get("network_execution") is False
        and campaign.get("status") == "PROVEN"
        and campaign.get("paper_read_only") is True
        and campaign.get("real_execution") is False
        and campaign.get("manifest_mutation") is False
        and campaign.get("fail_closed") is False
    )
    return _campaign_base(
        "PROVEN" if valid else "REJECTED",
        verdict="NATIVE_VENUE_CAMPAIGN_BOUNDARY_SAFE" if valid else "NATIVE_VENUE_CAMPAIGN_BOUNDARY_REJECTED",
        venue_status=venue.get("status"),
        campaign_status=campaign.get("status"),
        network_execution=False,
        manifest_mutation=False,
        promotion_disabled=True,
        fail_closed=not valid,
    )


def campaign_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and field in row and row[field] not in (None, "")
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_FIELD_PRESENT" if valid else "CAMPAIGN_FIELD_MISSING", field=field, fail_closed=not valid)


def campaign_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and field in row and row[field] is not None
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_FIELD_NON_NULL" if valid else "CAMPAIGN_FIELD_NULL", field=field, fail_closed=not valid)


def campaign_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = row.get(field) if isinstance(row, Mapping) else None
    bool_is_int = expected_type is int and isinstance(value, bool)
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and isinstance(expected_type, type) and isinstance(value, expected_type) and not bool_is_int
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_FIELD_TYPE_VALID" if valid else "CAMPAIGN_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def campaign_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _campaign_finite(value)
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_VALUE_FINITE" if valid else "CAMPAIGN_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def campaign_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _campaign_integer(event_ts_ms) and _campaign_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_EVENT_WITHIN_CUTOFF" if valid else "CAMPAIGN_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def campaign_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _campaign_integer(event_ts_ms) and _campaign_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_EVENT_AGE_VALID" if valid else "CAMPAIGN_EVENT_TOO_OLD", fail_closed=not valid)


def campaign_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(isinstance(value, str) and value.strip() for value in values) and len(values) == len(set(values))
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_EVENTS_UNIQUE" if valid else "CAMPAIGN_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def campaign_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _campaign_integer(attempts) and _campaign_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_RETRY_BOUNDED" if valid else "CAMPAIGN_RETRY_UNSAFE", fail_closed=not valid)


def campaign_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    values = list(outputs)
    valid = bool(values) and len({canonical_json(value) for value in values}) == 1
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_REPLAY_DETERMINISTIC" if valid else "CAMPAIGN_REPLAY_DIVERGED", fail_closed=not valid)


def campaign_stage_order_receipt(*, creation_phase: Any, analysis_stage: Any, drained: bool) -> dict[str, Any]:
    valid = creation_phase == "ANALYZE" and analysis_stage in set(ANALYSIS_STAGE_BY_KIND.values()) and drained is True
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_STAGE_AFTER_DRAIN" if valid else "CAMPAIGN_STAGE_BEFORE_DRAIN", fail_closed=not valid)


def campaign_collect_authorization_receipt(*, kind: Any, automatic: bool, authorized: bool) -> dict[str, Any]:
    valid = kind in COLLECT_CAMPAIGN_KINDS and isinstance(automatic, bool) and ((automatic is False and authorized is False) or (automatic is True and authorized is True))
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_COLLECT_AUTHORIZED" if valid else "CAMPAIGN_COLLECT_UNAUTHORIZED", fail_closed=not valid)


def campaign_request_replay_receipt(*, request_ids: Sequence[Any], accepted_request_ids: Sequence[Any]) -> dict[str, Any]:
    requests = list(request_ids)
    accepted = list(accepted_request_ids)
    valid = bool(requests) and len(requests) == len(set(requests)) and len(accepted) == len(set(accepted)) and set(accepted).issubset(requests)
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_REQUESTS_IDEMPOTENT" if valid else "CAMPAIGN_REQUEST_REPLAYED", fail_closed=not valid)


def campaign_epoch_receipt(*, observed_epoch: Any, current_epoch: Any) -> dict[str, Any]:
    valid = _campaign_integer(observed_epoch) and _campaign_integer(current_epoch) and observed_epoch == current_epoch
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_EPOCH_CURRENT" if valid else "CAMPAIGN_EPOCH_STALE", fail_closed=not valid)


def campaign_hash_receipt(*, expected_sha: Any, actual_sha: Any) -> dict[str, Any]:
    valid = _campaign_sha(expected_sha) and _campaign_sha(actual_sha) and expected_sha == actual_sha
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_SHA_MATCH" if valid else "CAMPAIGN_SHA_MISMATCH", fail_closed=not valid)


def campaign_lease_receipt(*, worker_id: Any, lease_owner: Any, lease_expires_at_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = isinstance(worker_id, str) and bool(worker_id.strip()) and worker_id == lease_owner and _campaign_integer(lease_expires_at_ms) and _campaign_integer(now_ms) and now_ms < lease_expires_at_ms
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_LEASE_ACTIVE" if valid else "CAMPAIGN_LEASE_EXPIRED_OR_MISMATCHED", fail_closed=not valid)


def campaign_single_owner_receipt(*, owner_ids: Sequence[Any]) -> dict[str, Any]:
    owners = list(owner_ids)
    valid = len(owners) == 1 and isinstance(owners[0], str) and bool(owners[0].strip())
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_SINGLE_OWNER" if valid else "CAMPAIGN_SPLIT_BRAIN", fail_closed=not valid)


def campaign_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    required = list(required_fields)
    valid = isinstance(checkpoint, Mapping) and bool(required) and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required) and checkpoint.get("saved") is True
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_CHECKPOINT_COMPLETE" if valid else "CAMPAIGN_CHECKPOINT_PARTIAL", fail_closed=not valid)


def campaign_runner_receipt(*, runner_label: Any) -> dict[str, Any]:
    normalized = runner_label.strip().lower() if isinstance(runner_label, str) else ""
    valid = bool(normalized) and "self-hosted" not in normalized and "self_hosted" not in normalized and "localhost" not in normalized and normalized in {"ubuntu-latest", "windows-latest", "macos-latest", "github-hosted"}
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_GITHUB_HOSTED" if valid else "CAMPAIGN_RUNNER_FORBIDDEN", fail_closed=not valid)


def campaign_done_coverage_receipt(*, status: Any, coverage_status: Any, required_proofs: Sequence[Any], completed_proofs: Sequence[Any]) -> dict[str, Any]:
    required = set(required_proofs)
    completed = set(completed_proofs)
    valid = status == "COMPLETE" and coverage_status == "PROVEN" and bool(required) and required.issubset(completed)
    return _campaign_base("PROVEN" if valid else "REJECTED", verdict="CAMPAIGN_DONE_COVERAGE_COMPLETE" if valid else "CAMPAIGN_DONE_WITHOUT_COVERAGE", fail_closed=not valid)
