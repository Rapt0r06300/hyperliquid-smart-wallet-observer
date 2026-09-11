from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable

from hl_observer.ops.echec_silencieux import noter as _noter_echec


SCHEMA_VERSION = 1
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TaskType(str, Enum):
    AUTO = "AUTO"
    DETERMINISTIC_GATE = "DETERMINISTIC_GATE"
    HUMAN_DECISION = "HUMAN_DECISION"


class Transition(str, Enum):
    STOP = "STOP"
    PAUSE = "PAUSE"
    KILL = "KILL"
    DEMOTE = "DEMOTE"


class AutonomousAction(str, Enum):
    READ_PUBLIC_DATA = "read_public_data"
    RUN_TESTS = "run_tests"
    RUN_REPLAY = "run_replay"
    CREATE_HYPOTHESIS_DRAFT = "create_hypothesis_draft"
    MODIFY_BOUNDED_RESEARCH_CODE = "modify_bounded_research_code"
    WRITE_REPORT = "write_report"
    CREATE_EXPERIMENT = "create_experiment"
    COMMIT_PERMITTED_WORK = "commit_permitted_work"
    RETRY_RECOVER = "retry_recover"
    UPDATE_TASK_STATE = "update_task_state"


@dataclass(slots=True)
class OwnershipLease:
    task_id: str
    owner: str
    token_hash: str
    lease_started: datetime
    lease_expires: datetime
    released_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HandoffReceipt:
    task_id: str
    old_owner: str
    new_owner: str
    released_at: datetime
    acquired_at: datetime


@dataclass(frozen=True, slots=True)
class DoneContractEvidence:
    code: bool
    real_call_path: bool
    valid_input: bool
    effect_or_decision: bool
    artifact_or_ledger: bool
    tests: bool
    evidence: bool
    commit_sha: str


@dataclass(slots=True)
class TaskGraphNode:
    task_id: str
    owner: str
    contributors: tuple[str, ...]
    status: str
    dependencies: tuple[str, ...]
    handoff_from: str | None
    handoff_to: str | None
    reason: str
    evidence_required: tuple[str, ...]
    done_contract: str
    budget: str
    lease: OwnershipLease
    commit_sha: str | None
    task_type: TaskType
    transition: Transition | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    if not token:
        raise ValueError("ownership token must not be empty")
    return sha256(token.encode("utf-8")).hexdigest()


def acquire_ownership(
    task_id: str,
    owner: str,
    *,
    now: datetime,
    ttl_seconds: int,
    token: str,
) -> OwnershipLease:
    if not task_id or not owner:
        raise ValueError("task_id and owner are required")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    started = _utc(now)
    return OwnershipLease(
        task_id=task_id,
        owner=owner,
        token_hash=_token_hash(token),
        lease_started=started,
        lease_expires=started + timedelta(seconds=ttl_seconds),
    )


def can_mutate_task(
    lease: OwnershipLease,
    *,
    owner: str,
    token: str,
    now: datetime,
) -> bool:
    current = _utc(now)
    if lease.released_at is not None:
        return False
    if current < lease.lease_started or current >= lease.lease_expires:
        return False
    if owner != lease.owner or not token:
        return False
    return _token_hash(token) == lease.token_hash


def transfer_ownership(
    lease: OwnershipLease,
    *,
    current_owner: str,
    current_token: str,
    new_owner: str,
    now: datetime,
    ttl_seconds: int,
    new_token: str,
) -> tuple[OwnershipLease, HandoffReceipt]:
    released = _utc(now)
    if not can_mutate_task(
        lease,
        owner=current_owner,
        token=current_token,
        now=released,
    ):
        raise PermissionError("active ownership credential required")
    lease.released_at = released
    new_lease = acquire_ownership(
        lease.task_id,
        new_owner,
        now=released,
        ttl_seconds=ttl_seconds,
        token=new_token,
    )
    return new_lease, HandoffReceipt(
        task_id=lease.task_id,
        old_owner=lease.owner,
        new_owner=new_owner,
        released_at=released,
        acquired_at=released,
    )


def assert_autonomous_action_allowed(action: AutonomousAction | str) -> None:
    try:
        AutonomousAction(action)
    except (TypeError, ValueError) as exc:
        raise PermissionError(f"action outside autonomous envelope: {action}") from exc


def validate_done_contract(evidence: DoneContractEvidence) -> list[str]:
    missing: list[str] = []
    for field_name in (
        "code",
        "real_call_path",
        "valid_input",
        "effect_or_decision",
        "artifact_or_ledger",
        "tests",
        "evidence",
    ):
        if not getattr(evidence, field_name):
            missing.append(field_name)
    if not _SHA40.fullmatch(evidence.commit_sha):
        missing.append("commit_sha")
    return missing


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _utc(value).isoformat()


def _lease_to_dict(lease: OwnershipLease) -> dict[str, object]:
    return {
        "task_id": lease.task_id,
        "owner": lease.owner,
        "token_hash": lease.token_hash,
        "lease_started": _iso(lease.lease_started),
        "lease_expires": _iso(lease.lease_expires),
        "released_at": _iso(lease.released_at),
    }


def _node_to_dict(node: TaskGraphNode) -> dict[str, object]:
    return {
        "task_id": node.task_id,
        "owner": node.owner,
        "contributors": list(node.contributors),
        "status": node.status,
        "dependencies": list(node.dependencies),
        "handoff_from": node.handoff_from,
        "handoff_to": node.handoff_to,
        "reason": node.reason,
        "evidence_required": list(node.evidence_required),
        "done_contract": node.done_contract,
        "budget": node.budget,
        "lease": _lease_to_dict(node.lease),
        "commit_sha": node.commit_sha,
        "task_type": node.task_type.value,
        "transition": None if node.transition is None else node.transition.value,
    }


def write_task_graph_atomic(path: str | Path, nodes: Iterable[TaskGraphNode]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tasks": [_node_to_dict(node) for node in nodes],
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, destination)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError as exc:
            _noter_echec("hl_observer/ops/task_graph_contract.py:atomic_cleanup", exc)
        raise


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid persisted timestamp")
    parsed = datetime.fromisoformat(value)
    return _utc(parsed)


def _parse_string_list(row: dict[str, object], field: str) -> tuple[str, ...]:
    value = row.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return tuple(value)


def _parse_string_scalar(row: dict[str, object], field: str, *, default: str = "") -> str:
    value = row.get(field, default)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _parse_optional_string_scalar(row: dict[str, object], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def load_task_graph(path: str | Path) -> list[TaskGraphNode]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported task graph schema")
    rows = payload.get("tasks")
    if not isinstance(rows, list):
        raise ValueError("task graph tasks must be a list")
    nodes: list[TaskGraphNode] = []
    seen_task_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("lease"), dict):
            raise ValueError("invalid task graph node")
        raw_lease = row["lease"]
        raw_task_id = row.get("task_id")
        if not isinstance(raw_task_id, str):
            raise ValueError("task_id must be a string")
        node_task_id = raw_task_id
        if not node_task_id:
            raise ValueError("task_id must not be empty")
        if node_task_id in seen_task_ids:
            raise ValueError(f"duplicate task_id: {node_task_id}")
        seen_task_ids.add(node_task_id)
        raw_owner = row.get("owner")
        if not isinstance(raw_owner, str):
            raise ValueError("owner must be a string")
        node_owner = raw_owner
        if not node_owner:
            raise ValueError("owner must not be empty")
        raw_lease_task_id = raw_lease.get("task_id")
        if not isinstance(raw_lease_task_id, str):
            raise ValueError("task_id must be a string")
        raw_lease_owner = raw_lease.get("owner")
        if not isinstance(raw_lease_owner, str):
            raise ValueError("owner must be a string")
        raw_token_hash = raw_lease.get("token_hash")
        if not isinstance(raw_token_hash, str):
            raise ValueError("token_hash must be a string")
        lease = OwnershipLease(
            task_id=raw_lease_task_id,
            owner=raw_lease_owner,
            token_hash=raw_token_hash,
            lease_started=_parse_datetime(raw_lease["lease_started"]),  # type: ignore[arg-type]
            lease_expires=_parse_datetime(raw_lease["lease_expires"]),  # type: ignore[arg-type]
            released_at=_parse_datetime(raw_lease.get("released_at")),
        )
        if lease.lease_started is None or lease.lease_expires is None:
            raise ValueError("lease timestamps are required")
        if lease.lease_expires <= lease.lease_started:
            raise ValueError("lease expiration must be after start")
        if lease.task_id != node_task_id:
            raise ValueError("lease task_id does not match node task_id")
        if lease.owner != node_owner:
            raise ValueError("lease owner does not match node owner")
        if not _SHA256.fullmatch(lease.token_hash):
            raise ValueError("token_hash must be an exact 64-character lowercase hex SHA-256")
        raw_commit_sha = row.get("commit_sha")
        if raw_commit_sha is not None and (
            not isinstance(raw_commit_sha, str) or not _SHA40.fullmatch(raw_commit_sha)
        ):
            raise ValueError("commit_sha must be an exact 40-character lowercase hex SHA")
        transition = row.get("transition")
        nodes.append(TaskGraphNode(
            task_id=node_task_id,
            owner=node_owner,
            contributors=_parse_string_list(row, "contributors"),
            status=_parse_string_scalar(row, "status"),
            dependencies=_parse_string_list(row, "dependencies"),
            handoff_from=_parse_optional_string_scalar(row, "handoff_from"),
            handoff_to=_parse_optional_string_scalar(row, "handoff_to"),
            reason=_parse_string_scalar(row, "reason"),
            evidence_required=_parse_string_list(row, "evidence_required"),
            done_contract=_parse_string_scalar(row, "done_contract"),
            budget=_parse_string_scalar(row, "budget"),
            lease=lease,
            commit_sha=raw_commit_sha,
            task_type=TaskType(str(row["task_type"])),
            transition=None if transition is None else Transition(str(transition)),
        ))
    return nodes
