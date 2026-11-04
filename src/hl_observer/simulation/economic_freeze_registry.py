"""Immutable economic freeze discovery and reuse.

A forward proof is meaningless if every evaluation creates a fresh freeze after
all available data have already been observed.  This module therefore treats the
FIRST compatible family freeze as the durable boundary: later campaign runs
reuse it, and only observations strictly newer than ``frozen_at_ms`` may count
as physical forward evidence.

Pure local filesystem logic.  No network and no execution surface.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .economic_campaigns import REPORT_DIR
from .economic_objective import canonical_family

SCHEMA = "hypersmart.economic_parameter_freeze.v1"
_SHA256_HEX = frozenset("0123456789abcdef")


def parameter_hash(parameters: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(parameters), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be a 64-character SHA-256 digest")
    digest = value.lower()
    if any(char not in _SHA256_HEX for char in digest):
        raise ValueError(f"{field_name} must be a hexadecimal SHA-256 digest")
    return digest


def build_immutable_freeze_revision(
    previous_freeze: Mapping[str, Any],
    *,
    data_sha256: str,
    config_sha256: str,
    seed: int,
    costs: Mapping[str, Any],
    frozen_at_ms: int,
) -> dict[str, Any]:
    """Build an append-only revision without mutating the prior freeze.

    A revision is a new immutable evidence boundary, never an in-place edit of
    the incumbent freeze.  The material hash binds the predecessor, data,
    configuration, seed, costs and timestamp so any change is auditable.
    """
    if not isinstance(previous_freeze, Mapping) or not previous_freeze:
        raise ValueError("previous_freeze must be a non-empty mapping")
    predecessor = previous_freeze.get("freeze_hash")
    if predecessor is None:
        predecessor = hashlib.sha256(
            json.dumps(dict(previous_freeze), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
    predecessor = _sha256_digest(predecessor, "previous_freeze_hash")
    data_sha256 = _sha256_digest(data_sha256, "data_sha256")
    config_sha256 = _sha256_digest(config_sha256, "config_sha256")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if not isinstance(frozen_at_ms, int) or isinstance(frozen_at_ms, bool) or frozen_at_ms <= 0:
        raise ValueError("frozen_at_ms must be a positive integer")
    if not isinstance(costs, Mapping) or not costs:
        raise ValueError("costs must be a non-empty mapping")
    normalized_costs: dict[str, float] = {}
    for key, value in costs.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("cost names must be non-empty strings")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("costs must be finite numbers") from exc
        if not math.isfinite(number):
            raise ValueError("costs must be finite numbers")
        normalized_costs[key] = number
    try:
        revision = int(previous_freeze.get("revision") or 1) + 1
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("previous revision must be an integer") from exc
    material = {
        "previous_freeze_hash": predecessor,
        "data_sha256": data_sha256,
        "config_sha256": config_sha256,
        "seed": seed,
        "costs": normalized_costs,
        "frozen_at_ms": frozen_at_ms,
        "paper_only": True,
        "real_execution": False,
    }
    freeze_hash = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": SCHEMA,
        "family": previous_freeze.get("family"),
        "revision": revision,
        "freeze_hash": freeze_hash,
        "supersedes_freeze_hash": predecessor,
        "data_sha256": data_sha256,
        "config_sha256": config_sha256,
        "seed": seed,
        "costs": normalized_costs,
        "frozen_at_ms": frozen_at_ms,
        "selected_before_final_evaluation": True,
        "parameters": dict(previous_freeze.get("parameters") or {}),
        "parameters_sha256": previous_freeze.get("parameters_sha256"),
        "paper_only": True,
        "real_execution": False,
    }


def _valid(payload: object, family: str) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(
        payload.get("schema_version") == SCHEMA
        and canonical_family(payload.get("family")) == canonical_family(family)
        and payload.get("selected_before_final_evaluation") is True
        and isinstance(payload.get("parameters"), dict)
        and isinstance(payload.get("parameters_sha256"), str)
        and len(str(payload.get("parameters_sha256"))) == 64
        and int(payload.get("frozen_at_ms") or 0) > 0
    )


def list_freezes(root: str | Path, family: str) -> list[dict[str, Any]]:
    """Return valid freezes ordered by the physical freeze timestamp."""
    project_root = Path(root).resolve()
    normalized = canonical_family(family)
    directory = project_root / REPORT_DIR / "freezes" / normalized
    if not directory.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        if not _valid(payload, normalized):
            continue
        # Recompute the hash. A manually edited/corrupt freeze must never be reused.
        if parameter_hash(payload["parameters"]) != payload["parameters_sha256"]:
            continue
        row = dict(payload)
        try:
            row["path"] = path.relative_to(project_root).as_posix()
        except ValueError:
            row["path"] = str(path)
        rows.append(row)
    return sorted(rows, key=lambda row: (int(row["frozen_at_ms"]), str(row.get("campaign_id") or "")))


def first_freeze(root: str | Path, family: str) -> dict[str, Any] | None:
    rows = list_freezes(root, family)
    return rows[0] if rows else None


def first_compatible_freeze(
    root: str | Path,
    family: str,
    parameters: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the earliest immutable freeze with exactly the requested parameters."""
    expected = parameter_hash(parameters)
    for row in list_freezes(root, family):
        if row.get("parameters_sha256") == expected and dict(row.get("parameters") or {}) == dict(parameters):
            return row
    return None


def reuse_or_create_freeze(
    root: str | Path,
    family: str,
    parameters: Mapping[str, Any],
    datasets: Mapping[str, Any],
) -> dict[str, Any]:
    """Reuse the first compatible physical boundary, otherwise create it once.

    Dataset provenance is intentionally *not* part of compatibility.  A freeze
    records the data that existed when parameters were selected; later runs are
    expected to see a larger/different dataset while keeping that original
    timestamp and parameter choice immutable.  This is what makes genuinely
    post-freeze forward evidence possible instead of moving the boundary on
    every evaluation.
    """
    existing = first_compatible_freeze(root, family, parameters)
    if existing is not None:
        return existing

    # Local import avoids an import cycle at module import time:
    # economic_campaigns owns the physical writer and imports no registry code.
    from .economic_campaigns import freeze_parameters

    return freeze_parameters(root, family, parameters, datasets)


def split_pre_post_freeze(
    rows: list[Mapping[str, Any]],
    freeze: Mapping[str, Any],
    *,
    timestamp_key: str = "ts_ms",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Strict physical partition. Events exactly at the boundary are pre-freeze."""
    boundary = int(freeze.get("frozen_at_ms") or 0)
    if boundary <= 0:
        raise ValueError("invalid frozen_at_ms")
    pre: list[dict[str, Any]] = []
    post: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        try:
            ts = int(row.get(timestamp_key) or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if ts > boundary:
            post.append(row)
        else:
            pre.append(row)
    return pre, post


__all__ = [
    "SCHEMA",
    "build_immutable_freeze_revision",
    "first_compatible_freeze",
    "first_freeze",
    "list_freezes",
    "parameter_hash",
    "reuse_or_create_freeze",
    "split_pre_post_freeze",
]
