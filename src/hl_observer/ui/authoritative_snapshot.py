"""Authoritative snapshot (V12, repo 05): full HTTP source-of-truth snapshot.

Wraps the current dashboard state with the event-log revision + a content checksum so the
client can reconcile patches against an authoritative baseline. Pure; no fabrication.
"""

from __future__ import annotations

import json
from hashlib import sha256


def build_authoritative_snapshot(state: dict, *, revision: int, now_ms: int | None = None) -> dict:
    blob = json.dumps(state, sort_keys=True, default=str)
    return {
        "authoritative": True,
        "revision": int(revision),
        "checksum": sha256(blob.encode("utf-8")).hexdigest()[:16],
        "generated_at_ms": int(now_ms) if now_ms is not None else None,
        "state": state,
    }


__all__ = ["build_authoritative_snapshot"]
