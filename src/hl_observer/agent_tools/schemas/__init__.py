"""Agent tool output JSON schemas (V12, repo 08): contracts for read-only agent tools.

Lightweight, dependency-free validation (no `jsonschema` import). A schema is a dict
``{field: type}`` with a ``_required`` tuple. ``validate`` checks presence + type only.
Read-only: schemas describe *outputs the agent may READ*, never actions it may take.
"""

from __future__ import annotations

DECISION_SCHEMA = {
    "_required": ("accepted", "reason", "context_only"),
    "accepted": bool, "reason": str, "context_only": bool,
}

NO_TRADE_SCHEMA = {
    "_required": ("code", "message"),
    "code": str, "message": str,
}

SOURCE_HEALTH_SCHEMA = {
    "_required": ("source", "usable", "age_ms"),
    "source": str, "usable": bool, "age_ms": int,
}

SCHEMAS = {
    "decision": DECISION_SCHEMA,
    "no_trade": NO_TRADE_SCHEMA,
    "source_health": SOURCE_HEALTH_SCHEMA,
}


def validate(obj: dict, schema: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for key in schema.get("_required", ()):
        if key not in obj:
            errors.append(f"missing:{key}")
    for key, typ in schema.items():
        if key == "_required" or key not in obj:
            continue
        if not isinstance(obj[key], typ):
            errors.append(f"type:{key}")
    return (not errors), errors


__all__ = ["SCHEMAS", "DECISION_SCHEMA", "NO_TRADE_SCHEMA", "SOURCE_HEALTH_SCHEMA", "validate"]
