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
    if owner != lease.owner:
        return False
    return _token_hash(token) == lease.token_hash


def transfer_ownership(
    lease: OwnershipLease,
    *,
    new_owner: str,
    now: datetime,
    ttl_seconds: int,
    new_token: str,
) -> tuple[OwnershipLease, HandoffReceipt]:
    released = _utc(now)
    if lease.released_at is not None:
        raise ValueError("ownership lease already released")
    if released < lease.lease_started:
        raise ValueError("handoff cannot predate lease")
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


def load_task_graph(path: str | Path) -> list[TaskGraphNode]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported task graph schema")
    rows = payload.get("tasks")
    if not isinstance(rows, list):
        raise ValueError("task graph tasks must be a list")
    nodes: list[TaskGraphNode] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("lease"), dict):
            raise ValueError("invalid task graph node")
        raw_lease = row["lease"]
        lease = OwnershipLease(
            task_id=str(raw_lease["task_id"]),
            owner=str(raw_lease["owner"]),
            token_hash=str(raw_lease["token_hash"]),
            lease_started=_parse_datetime(raw_lease["lease_started"]),  # type: ignore[arg-type]
            lease_expires=_parse_datetime(raw_lease["lease_expires"]),  # type: ignore[arg-type]
            released_at=_parse_datetime(raw_lease.get("released_at")),
        )
        if lease.lease_started is None or lease.lease_expires is None:
            raise ValueError("lease timestamps are required")
        transition = row.get("transition")
        nodes.append(TaskGraphNode(
            task_id=str(row["task_id"]),
            owner=str(row["owner"]),
            contributors=tuple(str(value) for value in row.get("contributors", [])),
            status=str(row["status"]),
            dependencies=tuple(str(value) for value in row.get("dependencies", [])),
            handoff_from=None if row.get("handoff_from") is None else str(row["handoff_from"]),
            handoff_to=None if row.get("handoff_to") is None else str(row["handoff_to"]),
            reason=str(row.get("reason", "")),
            evidence_required=tuple(str(value) for value in row.get("evidence_required", [])),
            done_contract=str(row.get("done_contract", "")),
            budget=str(row.get("budget", "")),
            lease=lease,
            commit_sha=None if row.get("commit_sha") is None else str(row["commit_sha"]),
            task_type=TaskType(str(row["task_type"])),
            transition=None if transition is None else Transition(str(transition)),
        ))
    return nodes
