"""Fail-closed safety controls for the paper-only Copy-Vault path.

The helpers in this module are pure decision receipts.  They do not access a
venue, read credentials, start a subprocess, or change runtime state.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence


_SECRET_NAME_RE = re.compile(
    r"(?:private[_ -]?key|mnemonic|seed(?: phrase)?|api[_ -]?key|secret|signature|bearer)\b",
    re.IGNORECASE,
)


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def circuit_breaker_rearm_receipt(
    *,
    proof_valid: bool,
    cooldown_elapsed: bool,
    health_fresh: bool,
    operator_acknowledged: bool,
) -> dict[str, Any]:
    """Allow rearm only after every independent recovery proof is present."""

    valid = all((proof_valid, cooldown_elapsed, health_fresh, operator_acknowledged))
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "rearm_allowed": valid,
        "fail_closed": not valid,
    }


def risk_signal_conflict_receipt(*, risk_veto: bool, signal_positive: bool) -> dict[str, Any]:
    """A risk veto always wins over a positive signal."""

    allowed = bool(signal_positive) and not bool(risk_veto)
    return {
        "status": "PROVEN",
        "decision": "ALLOW" if allowed else "DENY",
        "risk_veto_wins": True,
        "fail_closed": not allowed,
    }


def finite_quota_receipt(*, quota: Any, maximum: Any) -> dict[str, Any]:
    """Reject NaN, infinities, negatives and quotas above the declared cap."""

    valid = _finite_number(quota) and _finite_number(maximum)
    if valid:
        valid = 0.0 <= float(quota) <= float(maximum)
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "quota": float(quota) if valid else None,
        "maximum": float(maximum) if _finite_number(maximum) else None,
        "fail_closed": not valid,
    }


def non_negative_stop_receipt(*, stop_tolerance: Any) -> dict[str, Any]:
    """A stop tolerance must be finite and never negative."""

    valid = _finite_number(stop_tolerance) and float(stop_tolerance) >= 0.0
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "stop_tolerance": float(stop_tolerance) if valid else None,
        "fail_closed": not valid,
    }


def enabled_module_budget_receipt(*, module_enabled: bool, budget: Any) -> dict[str, Any]:
    """A disabled module cannot receive an implicit/default budget."""

    valid = bool(module_enabled) and _finite_number(budget) and float(budget) >= 0.0
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "budget_granted": float(budget) if valid else None,
        "module_enabled": bool(module_enabled),
        "fail_closed": not valid,
    }


def hard_stop_consistency_receipt(*, cli_stop: Any, ui_stop: Any) -> dict[str, Any]:
    """CLI and UI must use one exact finite hard-stop value."""

    valid = _finite_number(cli_stop) and _finite_number(ui_stop)
    if valid:
        valid = float(cli_stop) == float(ui_stop) and float(cli_stop) >= 0.0
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "consistent": valid,
        "hard_stop": float(cli_stop) if valid else None,
        "fail_closed": not valid,
    }


def score_guard_receipt(
    *, score_before: Any, score_after: Any, guard_approved: bool
) -> dict[str, Any]:
    """A score mutation requires an explicit guard approval."""

    finite = _finite_number(score_before) and _finite_number(score_after)
    changed = finite and float(score_before) != float(score_after)
    valid = finite and (not changed or bool(guard_approved))
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "changed": changed,
        "guard_approved": bool(guard_approved),
        "fail_closed": not valid,
    }


def source_failure_fallback_receipt(
    *,
    source_ok: bool,
    fallback_requested: bool,
    explicit_conservative_fallback: bool,
    fail_closed: bool,
) -> dict[str, Any]:
    """A failed source may only use an explicit conservative fail-closed fallback."""

    valid = bool(source_ok) or (
        bool(fallback_requested)
        and bool(explicit_conservative_fallback)
        and bool(fail_closed)
    )
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "fallback_allowed": valid,
        "source_ok": bool(source_ok),
        "fail_closed": not valid or bool(fail_closed),
    }


def venue_filter_receipt(
    *, venue: Any, category: Any, allowed_venues: Sequence[str]
) -> dict[str, Any]:
    """Require a declared venue/category and an explicit venue allow-list hit."""

    normalized_venue = str(venue).strip().casefold()
    normalized_category = str(category).strip().casefold()
    allowed = {str(item).strip().casefold() for item in allowed_venues if str(item).strip()}
    valid = bool(normalized_venue) and bool(normalized_category) and normalized_venue in allowed
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "venue": normalized_venue or None,
        "category": normalized_category or None,
        "filter_applied": valid,
        "fail_closed": not valid,
    }


def error_report_redaction_receipt(
    *, error_message: Any, sensitive_values: Sequence[str] = ()
) -> dict[str, Any]:
    """Reject reports containing secret names or supplied secret values."""

    text = str(error_message)
    lowered = text.casefold()
    named_secret = bool(_SECRET_NAME_RE.search(text))
    leaked_value = any(str(value) and str(value).casefold() in lowered for value in sensitive_values)
    valid = not named_secret and not leaked_value
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "redacted": valid,
        "fail_closed": not valid,
    }


__all__ = [
    "circuit_breaker_rearm_receipt",
    "risk_signal_conflict_receipt",
    "finite_quota_receipt",
    "non_negative_stop_receipt",
    "enabled_module_budget_receipt",
    "hard_stop_consistency_receipt",
    "score_guard_receipt",
    "source_failure_fallback_receipt",
    "venue_filter_receipt",
    "error_report_redaction_receipt",
]
