"""Runtime bridge for the generated 120-idea wiring status.

The static idea registry describes the intended contract. This module is the
runtime truth surface: it consumes the generated status artifact when present,
rejects malformed or incomplete artifacts, and never upgrades structural
evidence into economic proof.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXPECTED_IDS = tuple(range(1, 121))
ALLOWED_STATUSES = {
    "IMPLEMENTED_AND_WIRED",
    "IMPLEMENTED_BUT_PARTIAL",
    "IMPLEMENTED_BUT_NOT_WIRED",
    "BROKEN",
    "MISSING",
    "NOT_APPLICABLE",
}


class EventIntelligenceStatusError(ValueError):
    """Raised when the generated status artifact is not canonical."""


def load_status(path: str | Path = "docs/event-intelligence-120-status.json") -> dict[str, Any]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EventIntelligenceStatusError(f"status artifact unavailable: {target}") from exc
    if payload.get("schema_version") != "alina.event_intelligence_status.v2":
        raise EventIntelligenceStatusError("unsupported event-intelligence status schema")
    items = payload.get("items")
    if not isinstance(items, list) or [item.get("id") for item in items] != list(EXPECTED_IDS):
        raise EventIntelligenceStatusError("status artifact must contain ordered ids 1..120")
    for item in items:
        if not isinstance(item, dict) or item.get("status") not in ALLOWED_STATUSES:
            raise EventIntelligenceStatusError("status artifact contains an invalid item")
        if not isinstance(item.get("evidence_files"), list):
            raise EventIntelligenceStatusError("status artifact is missing evidence files")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise EventIntelligenceStatusError("status artifact is missing summary")
    calculated = {status: sum(item["status"] == status for item in items) for status in ALLOWED_STATUSES}
    if any(int(summary.get(status, 0)) != count for status, count in calculated.items()):
        raise EventIntelligenceStatusError("status summary does not match item statuses")
    return payload


def wiring_contract(path: str | Path = "docs/event-intelligence-120-status.json") -> dict[str, Any]:
    payload = load_status(path)
    summary = dict(payload["summary"])
    missing = (
        int(summary.get("MISSING", 0))
        + int(summary.get("BROKEN", 0))
        + int(summary.get("IMPLEMENTED_BUT_NOT_WIRED", 0))
    )
    partial = int(summary.get("IMPLEMENTED_BUT_PARTIAL", 0))
    return {
        "schema": "alina.event_intelligence_wiring.v1",
        "status_registry_digest": payload.get("registry_digest"),
        "idea_count": len(payload["items"]),
        "summary": summary,
        "wiring_complete": missing == 0 and partial == 0,
        "economic_proof_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


__all__ = ["EventIntelligenceStatusError", "load_status", "wiring_contract"]
