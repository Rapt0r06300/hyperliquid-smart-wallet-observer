"""Bounded leases for standalone read-only collection campaigns.

The normal launcher owns collectors through its session marker.  Economic
evidence campaigns can run without the UI, but they must never create immortal
background processes.  A lease gives those campaigns an explicit owner and an
expiry while preserving the launcher's existing anti-orphan contract.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "hypersmart.collector_lease.v1"
PURPOSE = "economic_evidence_collection"
DEFAULT_RELPATH = Path("runtime") / "data" / "economic_collection_lease.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def create_lease(
    root: str | Path,
    *,
    duration_s: float,
    now: float | None = None,
    token: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create or replace one bounded campaign lease atomically."""

    if not 30.0 <= float(duration_s) <= 7 * 24 * 60 * 60:
        raise ValueError("collector lease duration must be between 30s and 7 days")
    root_path = Path(root).resolve()
    issued_s = time.time() if now is None else float(now)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "purpose": PURPOSE,
        "lease_id": "lease-" + secrets.token_hex(8),
        "token": token or secrets.token_hex(24),
        "root": str(root_path),
        "issued_at_ms": int(issued_s * 1000),
        "expires_at_ms": int((issued_s + float(duration_s)) * 1000),
        "paper_read_only": True,
        "real_execution": False,
    }
    path = root_path / DEFAULT_RELPATH
    _atomic_write(path, payload)
    return path, payload


def validate_lease(
    lease_file: str | Path,
    token: str,
    root: str | Path,
    *,
    now: float | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Validate schema, owner, root and expiry; fail closed on every anomaly."""

    if not str(lease_file or "").strip() or not str(token or "").strip():
        return False, "COLLECTOR_LEASE_MISSING", None
    try:
        path = Path(lease_file).resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False, "COLLECTOR_LEASE_UNREADABLE", None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return False, "COLLECTOR_LEASE_SCHEMA_INVALID", None
    if payload.get("purpose") != PURPOSE:
        return False, "COLLECTOR_LEASE_PURPOSE_INVALID", payload
    if payload.get("paper_read_only") is not True or payload.get("real_execution") is not False:
        return False, "COLLECTOR_LEASE_SAFETY_INVALID", payload
    if not secrets.compare_digest(str(payload.get("token") or ""), str(token)):
        return False, "COLLECTOR_LEASE_REPLACED", payload
    if Path(str(payload.get("root") or "")).resolve() != Path(root).resolve():
        return False, "COLLECTOR_LEASE_ROOT_MISMATCH", payload
    try:
        expires_at_ms = int(payload["expires_at_ms"])
    except (KeyError, TypeError, ValueError):
        return False, "COLLECTOR_LEASE_EXPIRY_INVALID", payload
    current_ms = int((time.time() if now is None else float(now)) * 1000)
    if expires_at_ms <= current_ms:
        return False, "COLLECTOR_LEASE_EXPIRED", payload
    return True, "", payload


def public_lease(payload: dict[str, Any]) -> dict[str, Any]:
    """Return report-safe lease metadata without the bearer token."""

    return {key: value for key, value in payload.items() if key != "token"}


__all__ = [
    "DEFAULT_RELPATH",
    "PURPOSE",
    "SCHEMA_VERSION",
    "create_lease",
    "public_lease",
    "validate_lease",
]
