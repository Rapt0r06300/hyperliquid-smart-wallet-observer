"""Per-field freshness metadata for shared runtime status files."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

STATUS_FIELD_META_KEY = "status_field_meta"


@dataclass(frozen=True, slots=True)
class ComponentSLA:
    component: str
    max_age_ms: int
    required: bool = True


def component_health(
    payload: dict[str, Any],
    sla: ComponentSLA,
    *,
    current_ms: int,
    session_id: str,
) -> dict[str, Any]:
    meta = payload.get(STATUS_FIELD_META_KEY)
    stamp = meta.get(sla.component) if isinstance(meta, dict) else None
    if not isinstance(stamp, dict):
        status = "MISSING" if sla.required else "OPTIONAL_MISSING"
        return {**asdict(sla), "status": status, "age_ms": None, "error": "STATUS_FIELD_MISSING"}
    try:
        updated_at_ms = int(stamp["updated_at_ms"])
        age_ms = int(current_ms) - updated_at_ms
    except (KeyError, TypeError, ValueError):
        return {
            **asdict(sla),
            "status": "READ_ERROR",
            "age_ms": None,
            "error": "STATUS_TIMESTAMP_INVALID",
        }
    stamped_session = str(stamp.get("session_id") or "")
    if session_id and stamped_session != session_id:
        return {
            **asdict(sla),
            "status": "SESSION_MISMATCH",
            "age_ms": age_ms,
            "error": f"{stamped_session}!={session_id}",
        }
    return {
        **asdict(sla),
        "status": "HEALTHY" if 0 <= age_ms <= sla.max_age_ms else "STALE",
        "age_ms": age_ms,
        "error": None if 0 <= age_ms <= sla.max_age_ms else "SLA_EXCEEDED",
    }


def stamp_status_fields(
    payload: dict[str, Any],
    fields: Iterable[str],
    *,
    producer: str,
    session_id: str,
    updated_at_ms: int,
) -> None:
    meta = payload.get(STATUS_FIELD_META_KEY)
    if not isinstance(meta, dict):
        meta = {}
    for field in fields:
        meta[str(field)] = {
            "updated_at_ms": int(updated_at_ms),
            "producer": str(producer),
            "session_id": str(session_id),
        }
    payload[STATUS_FIELD_META_KEY] = meta


def status_field_is_fresh(
    payload: dict[str, Any],
    field: str,
    *,
    current_ms: int,
    session_id: str,
    max_age_ms: int,
) -> bool:
    meta = payload.get(STATUS_FIELD_META_KEY)
    if not isinstance(meta, dict):
        return False
    stamp = meta.get(str(field))
    if not isinstance(stamp, dict):
        return False
    try:
        updated_at_ms = int(stamp["updated_at_ms"])
    except (KeyError, TypeError, ValueError):
        return False
    stamped_session = str(stamp.get("session_id") or "")
    if session_id and stamped_session != session_id:
        return False
    age_ms = int(current_ms) - updated_at_ms
    return 0 <= age_ms <= max(0, int(max_age_ms))


__all__ = [
    "STATUS_FIELD_META_KEY",
    "ComponentSLA",
    "component_health",
    "stamp_status_fields",
    "status_field_is_fresh",
]
