"""Fail-closed controls for non-authoritative Copy-Vault model shadow paths."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def v13_shadow_role_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Define V13 as an observable shadow, never an authoritative controller."""
    if not rows:
        return _base("MORE_DATA", reason="empty_v13_shadow_role")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("version") != "V13"
        or row.get("role") != "SHADOW"
        or row.get("authoritative") is not False
        or row.get("can_submit") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="V13_SHADOW_ROLE_EXPLICIT", invalid_rows=invalid)


def v14_signal_rater_non_authoritative_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep V14 signal rating informational and unable to override gates."""
    if not rows:
        return _base("MORE_DATA", reason="empty_v14_signal_rater")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("version") != "V14"
        or row.get("component") != "signal-rater"
        or row.get("authoritative") is not False
        or row.get("can_override") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="V14_SIGNAL_RATER_NON_AUTHORITATIVE", invalid_rows=invalid)


def ollama_outage_engine_continuity_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a model outage to preserve the paper engine without model authority."""
    if not rows:
        return _base("MORE_DATA", reason="empty_model_outage_sample")
    invalid: list[int] = []
    outage_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("engine_alive") is not True:
            invalid.append(index)
            continue
        if row.get("model_available") is False:
            outage_count += 1
            if row.get("engine_state") != "RUNNING" or row.get("paper_read_only") is not True:
                invalid.append(index)
    return _base(
        "PROVEN" if outage_count and not invalid else "REJECTED",
        verdict="OLLAMA_OUTAGE_ENGINE_CONTINUES" if outage_count and not invalid else "OLLAMA_OUTAGE_NOT_ISOLATED",
        outage_count=outage_count,
        invalid_rows=invalid,
    )


def model_noise_reduction_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require deterministic input identity and explicit bounded shadow noise."""
    if not rows:
        return _base("MORE_DATA", reason="empty_model_noise_sample")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        noise = _number(row.get("noise_score")) if isinstance(row, Mapping) else None
        if (
            not isinstance(row, Mapping)
            or not str(row.get("input_hash") or "").strip()
            or row.get("deterministic_features") is not True
            or row.get("noise_reduced") is not True
            or noise is None
            or noise < 0
            or noise > 1
        ):
            invalid.append(index)
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="MODEL_NOISE_BOUNDED", invalid_rows=invalid)


def model_age_provenance_receipt(rows: Sequence[Mapping[str, Any]], *, max_age_ms: int = 86_400_000) -> dict[str, Any]:
    """Require model identity, source and bounded load age."""
    if not rows or max_age_ms <= 0:
        return _base("MORE_DATA" if not rows else "UNMEASURABLE", reason="invalid_model_age_window")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        trained = _number(row.get("trained_at_ms")) if isinstance(row, Mapping) else None
        loaded = _number(row.get("loaded_at_ms")) if isinstance(row, Mapping) else None
        if (
            not isinstance(row, Mapping)
            or not str(row.get("model_id") or "").strip()
            or not str(row.get("model_sha256") or "").strip()
            or not str(row.get("provenance") or "").strip()
            or trained is None
            or loaded is None
            or loaded < trained
            or loaded - trained > max_age_ms
        ):
            invalid.append(index)
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="MODEL_AGE_AND_PROVENANCE_VERIFIED", invalid_rows=invalid)


def training_session_separation_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Prevent training metadata from silently becoming active-session state."""
    if not rows:
        return _base("MORE_DATA", reason="empty_training_session_separation")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("training_session_id") or "").strip()
        or not str(row.get("active_session_id") or "").strip()
        or row.get("training_session_id") == row.get("active_session_id")
        or not str(row.get("artifact_sha256") or "").strip()
        or row.get("active_session_mutated") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="TRAINING_ACTIVE_SESSION_SEPARATED", invalid_rows=invalid)


def sensitive_explanation_redaction_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject explanations that still expose common secret-bearing fields."""
    if not rows:
        return _base("MORE_DATA", reason="empty_explanation_redaction")
    forbidden = re.compile(r"(?:private[_ -]?key|mnemonic|seed|signature|api[_ -]?key|secret)", re.I)
    invalid: list[int] = []
    for index, row in enumerate(rows):
        text = str(row.get("explanation") or "") if isinstance(row, Mapping) else ""
        if not isinstance(row, Mapping) or row.get("redacted") is not True or forbidden.search(text):
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="SENSITIVE_EXPLANATION_REDACTED", invalid_rows=invalid)


def model_freeze_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a model freeze to bind code, config and evaluation manifest."""
    if not rows:
        return _base("MORE_DATA", reason="empty_model_freeze")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("frozen") is not True
        or not str(row.get("model_sha256") or "").strip()
        or not str(row.get("config_sha256") or "").strip()
        or not str(row.get("evaluation_manifest_sha256") or "").strip()
        or row.get("parameters_bound") is not True
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="MODEL_FREEZE_BOUND_TO_EVALUATION", invalid_rows=invalid)


def baseline_vs_llm_shadow_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare a deterministic baseline with LLM shadow output without delegation."""
    if not rows:
        return _base("MORE_DATA", reason="empty_baseline_shadow_comparison")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if (
            not isinstance(row, Mapping)
            or "baseline_decision" not in row
            or "shadow_decision" not in row
            or row.get("baseline_authoritative") is not True
            or row.get("shadow_authoritative") is not False
            or row.get("shadow_can_override") is not False
        ):
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="BASELINE_AUTHORITATIVE_LLM_SHADOW_ONLY", invalid_rows=invalid)


def portable_model_path_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject absolute PC-specific model paths from a portable session."""
    if not rows:
        return _base("MORE_DATA", reason="empty_model_path_sample")
    invalid: list[int] = []
    drive_path = re.compile(r"^[A-Za-z]:[\\/]")
    for index, row in enumerate(rows):
        path = str(row.get("model_path") or "") if isinstance(row, Mapping) else ""
        if not isinstance(row, Mapping) or not str(row.get("model_id") or "").strip() or not path or drive_path.match(path) or path.startswith(("/", "\\")):
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="MODEL_PATH_PORTABLE", invalid_rows=invalid)


__all__ = [
    "v13_shadow_role_receipt",
    "v14_signal_rater_non_authoritative_receipt",
    "ollama_outage_engine_continuity_receipt",
    "model_noise_reduction_receipt",
    "model_age_provenance_receipt",
    "training_session_separation_receipt",
    "sensitive_explanation_redaction_receipt",
    "model_freeze_receipt",
    "baseline_vs_llm_shadow_receipt",
    "portable_model_path_receipt",
]
