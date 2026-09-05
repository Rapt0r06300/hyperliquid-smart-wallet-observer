"""Fail-closed primitives for promoting vNext TRAIN-only candidates.

This module only binds immutable research evidence and tracks one-shot OOS
consumption. It has no network, exchange, signing, order, or execution surface.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "hypersmart.vnext_freeze_manifest.v1"


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    material = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _freeze_material(
    *,
    family: str,
    candidate_sha256: str,
    dataset_sha256: str,
    config_sha256: str,
    frozen_at_ms: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "family": family,
        "candidate_sha256": candidate_sha256,
        "dataset_sha256": dataset_sha256,
        "config_sha256": config_sha256,
        "frozen_at_ms": frozen_at_ms,
        "paper_read_only": True,
        "real_execution": False,
    }


def build_freeze_manifest(
    *,
    family: str,
    freeze_candidate: Mapping[str, Any],
    dataset_fingerprint: str,
    config: Mapping[str, Any],
    frozen_at_ms: int,
) -> dict[str, Any]:
    """Bind candidate, dataset, config, family, and physical freeze time."""

    normalized_family = str(family).strip().lower()
    if not normalized_family:
        raise ValueError("family is required")
    if not _is_sha256(dataset_fingerprint):
        raise ValueError("dataset_fingerprint must be a full SHA-256")
    timestamp = int(frozen_at_ms)
    if timestamp <= 0:
        raise ValueError("frozen_at_ms must be positive")

    material = _freeze_material(
        family=normalized_family,
        candidate_sha256=_canonical_sha256(freeze_candidate),
        dataset_sha256=dataset_fingerprint.lower(),
        config_sha256=_canonical_sha256(config),
        frozen_at_ms=timestamp,
    )
    return {**material, "freeze_hash": _canonical_sha256(material)}


def verify_freeze_manifest(manifest: Mapping[str, Any]) -> bool:
    """Recompute the binding; any mutation fails closed."""

    if manifest.get("schema_version") != SCHEMA_VERSION:
        return False
    if manifest.get("paper_read_only") is not True or manifest.get("real_execution") is not False:
        return False
    family = manifest.get("family")
    if not isinstance(family, str) or not family.strip():
        return False
    for key in ("candidate_sha256", "dataset_sha256", "config_sha256", "freeze_hash"):
        if not _is_sha256(manifest.get(key)):
            return False
    try:
        timestamp = int(manifest.get("frozen_at_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    if timestamp <= 0:
        return False

    material = _freeze_material(
        family=family,
        candidate_sha256=str(manifest["candidate_sha256"]),
        dataset_sha256=str(manifest["dataset_sha256"]),
        config_sha256=str(manifest["config_sha256"]),
        frozen_at_ms=timestamp,
    )
    expected = _canonical_sha256(material)
    return hmac.compare_digest(expected, str(manifest["freeze_hash"]))


def consume_post_freeze_once(
    state: Mapping[str, Any],
    *,
    freeze_hash: str,
) -> dict[str, Any]:
    """Mark POST_FREEZE OOS consumed exactly once for one immutable freeze."""

    if not _is_sha256(freeze_hash):
        raise ValueError("freeze_hash must be a full SHA-256")
    existing = state.get("consumed_freeze_hash")
    if state.get("post_freeze_oos_consumed") is True:
        if existing == freeze_hash:
            raise RuntimeError("post-freeze OOS already consumed for freeze")
        raise RuntimeError("post-freeze OOS already consumed for a different freeze")
    if existing not in (None, freeze_hash):
        raise RuntimeError("post-freeze OOS state belongs to a different freeze")

    return {
        **dict(state),
        "post_freeze_oos_consumed": True,
        "consumed_freeze_hash": freeze_hash,
    }


def validate_temporal_disjointness(
    windows: Mapping[str, Mapping[str, Any]],
    *,
    frozen_at_ms: int,
) -> bool:
    """Verify all certification evidence windows are valid, disjoint, and post-freeze."""

    freeze = int(frozen_at_ms)
    ordered_names = ("validation", "oos", "forward", "placebo")
    normalized: list[tuple[str, int, int]] = []
    for name in ordered_names:
        window = windows.get(name)
        if not isinstance(window, Mapping):
            raise ValueError(f"missing temporal window: {name}")
        try:
            start_ms = int(window["start_ms"])
            end_ms = int(window["end_ms"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"invalid temporal window: {name}") from exc
        if start_ms >= end_ms:
            raise ValueError(f"invalid temporal window: {name}")
        if start_ms <= freeze:
            raise ValueError(f"{name} evidence must be strictly post-freeze")
        normalized.append((name, start_ms, end_ms))

    for previous, current in zip(normalized, normalized[1:]):
        if current[1] < previous[2]:
            raise ValueError(f"temporal overlap: {previous[0]}->{current[0]}")
    return True


def validate_certification_entry(candidate: Mapping[str, Any]) -> bool:
    """Allow certification namespace entry only for complete, safe evidence."""

    status = candidate.get("certification_status")
    if status != "CERTIFICATION_READY":
        raise ValueError(f"certification status is not eligible: {status!r}")
    if not _is_sha256(candidate.get("freeze_hash")):
        raise ValueError("certification requires a full freeze_hash")
    if candidate.get("post_freeze_oos_consumed") is not True:
        raise ValueError("certification requires consumed post-freeze OOS")
    if candidate.get("paper_read_only") is not True:
        raise ValueError("certification requires paper_read_only=True")
    if candidate.get("real_execution") is not False:
        raise ValueError("certification requires real_execution=False")
    windows = candidate.get("temporal_windows")
    if not isinstance(windows, Mapping):
        raise ValueError("certification requires temporal_windows")
    try:
        frozen_at_ms = int(candidate["frozen_at_ms"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("certification requires a valid frozen_at_ms") from exc
    if frozen_at_ms <= 0:
        raise ValueError("certification requires a positive frozen_at_ms")
    validate_temporal_disjointness(windows, frozen_at_ms=frozen_at_ms)
    for field in (
        "costs_complete",
        "liquidability_complete",
        "provenance_complete",
        "positions_flat",
        "economic_reconciliation_ok",
        "validation_without_recalibration",
        "temporal_disjointness_ok",
        "forward_post_freeze_complete",
        "placebo_complete",
    ):
        if candidate.get(field) is not True:
            raise ValueError(f"certification requires {field}=True")
    return True


__all__ = [
    "SCHEMA_VERSION",
    "build_freeze_manifest",
    "consume_post_freeze_once",
    "validate_certification_entry",
    "validate_temporal_disjointness",
    "verify_freeze_manifest",
]
