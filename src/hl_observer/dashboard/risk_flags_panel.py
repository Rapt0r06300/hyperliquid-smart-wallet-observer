"""Read-only dashboard payload for risk flags."""

from __future__ import annotations

from typing import Iterable


def build_risk_flags_panel(flags: Iterable[object]) -> dict[str, object]:
    rows = []
    blocked = 0
    for flag in flags:
        if hasattr(flag, "__dict__"):
            row = dict(flag.__dict__)
        elif isinstance(flag, dict):
            row = dict(flag)
        else:
            row = {"value": str(flag)}
        if row.get("blocked") is True:
            blocked += 1
        rows.append(row)
    return {"title": "Risk flags", "rows": rows, "blocked_count": blocked, "paper_only": True}


__all__ = ["build_risk_flags_panel"]
