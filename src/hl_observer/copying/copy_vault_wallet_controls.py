"""Fail-closed wallet-discovery controls for the Copy-Vault lane."""

from __future__ import annotations

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


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def first_decision_wallet_discovery_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require wallet discovery provenance before the first paper decision."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="wallet_discovery_state_missing")
    valid = bool(str(state.get("decision_id") or "").strip()) and bool(str(state.get("wallet_id") or "").strip()) and state.get("discovered_before_decision") is True and bool(str(state.get("source_manifest") or "").strip())
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="WALLET_DISCOVERED_BEFORE_DECISION" if valid else "WALLET_DISCOVERY_PROVENANCE_MISSING")


def vault_master_subaccount_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Distinguish vault, master and subaccount identities explicitly."""
    allowed = {"vault", "master", "subaccount"}
    if not rows:
        return _base("MORE_DATA", reason="empty_wallet_roles")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("address") or "").strip() or row.get("role") not in allowed or (row.get("role") == "subaccount" and not str(row.get("parent_address") or "").strip())
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="VAULT_MASTER_SUBACCOUNT_DISTINCT" if not invalid else "WALLET_ROLE_AMBIGUOUS", invalid_rows=invalid)


def shortlist_justification_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Make every selected wallet observable and justified."""
    if not rows:
        return _base("MORE_DATA", reason="empty_shortlist")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("wallet_id") or "").strip() or not isinstance(row.get("rank"), int) or row.get("rank") <= 0 or not str(row.get("justification_ref") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="SHORTLIST_OBSERVABLE_AND_JUSTIFIED" if not invalid else "SHORTLIST_JUSTIFICATION_MISSING", invalid_rows=invalid)


def top500_survivorship_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Reject a top-500 result that silently prefilters the universe."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="top500_state_missing")
    universe = state.get("universe_count")
    selected = state.get("selected_count")
    valid = _positive_int(universe) and universe >= 500 and isinstance(selected, int) and selected > 0 and selected <= 500 and state.get("full_universe_observed") is True and state.get("survivorship_filter_applied") is False
    return _base("PROVEN" if valid else "REJECTED", verdict="TOP500_SURVIVORSHIP_CONTROLLED" if valid else "TOP500_SURVIVORSHIP_RISK")


def realtime_accessible_selection_receipt(rows: Sequence[Mapping[str, Any]], *, max_age_ms: int = 90_000) -> dict[str, Any]:
    """Select only observations that are accessible in the live read-only lane."""
    if not rows:
        return _base("MORE_DATA", reason="empty_realtime_selection")
    invalid = []
    for index, row in enumerate(rows):
        age = row.get("age_ms") if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or row.get("real_time_access") is not True or not isinstance(age, int) or isinstance(age, bool) or age < 0 or age > max_age_ms or not str(row.get("source") or "").strip():
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="REALTIME_ACCESSIBLE_SELECTION" if not invalid else "REALTIME_ACCESSIBILITY_FAILED", invalid_rows=invalid, max_age_ms=max_age_ms)


def hyperliquid_budget_calibration_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calibrate discovery to observed request budget rather than an assumed quota."""
    if not rows:
        return _base("MORE_DATA", reason="empty_budget_calibration")
    invalid = []
    for index, row in enumerate(rows):
        requested = row.get("requests") if isinstance(row, Mapping) else None
        budget = row.get("budget") if isinstance(row, Mapping) else None
        remaining = row.get("remaining") if isinstance(row, Mapping) else None
        if not isinstance(requested, int) or not isinstance(budget, int) or not isinstance(remaining, int) or requested < 0 or budget <= 0 or remaining < 0 or requested > budget or remaining > budget:
            invalid.append(index)
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="DISCOVERY_BUDGET_CALIBRATED" if not invalid else "DISCOVERY_BUDGET_MISSING", invalid_rows=invalid)


def leader_style_change_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Detect a leader style change from explicit consecutive observations."""
    if len(rows) < 2:
        return _base("MORE_DATA", reason="need_consecutive_style_observations")
    invalid = [index for index, row in enumerate(rows) if not isinstance(row, Mapping) or not str(row.get("style") or "").strip() or not isinstance(row.get("observed_at_ms"), int)]
    if invalid:
        return _base("UNMEASURABLE", reason="leader_style_observation_invalid", invalid_rows=invalid)
    changed = any(rows[index]["style"] != rows[index - 1]["style"] for index in range(1, len(rows)))
    return _base("PROVEN", verdict="LEADER_STYLE_CHANGE_DETECTED" if changed else "LEADER_STYLE_STABLE", changed=changed, observations=len(rows))


def desync_quarantine_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Quarantine a leader after DESYNC until reconstruction is complete."""
    if not isinstance(state, Mapping) or not isinstance(state.get("desync"), bool):
        return _base("UNMEASURABLE", reason="desync_state_missing")
    valid = not state["desync"] or (state.get("quarantined") is True and state.get("reconstruction_ref") is not None)
    return _base("PROVEN" if valid else "REJECTED", verdict="DESYNC_QUARANTINED" if valid and state["desync"] else "DESYNC_NOT_PRESENT" if valid else "DESYNC_QUARANTINE_MISSING")


def mirror_canonical_path_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure Mirror uses the canonical Copy-Vault pipeline rather than a fork."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="mirror_path_state_missing")
    valid = bool(str(state.get("mirror_path") or "").strip()) and bool(str(state.get("canonical_path") or "").strip()) and state.get("mirror_path") == state.get("canonical_path") and state.get("paper_read_only") is True
    return _base("PROVEN" if valid else "REJECTED", verdict="MIRROR_USES_CANONICAL_PIPELINE" if valid else "MIRROR_PIPELINE_FORK")


def watchlist_consent_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require explicit consent for every watchlist wallet."""
    if not rows:
        return _base("MORE_DATA", reason="empty_watchlist")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("wallet_id") or "").strip() or row.get("consent") is not True or not str(row.get("consent_ref") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="WATCHLIST_CONSENT_EXPLICIT" if not invalid else "WATCHLIST_CONSENT_MISSING", invalid_rows=invalid)


__all__ = [
    "first_decision_wallet_discovery_receipt",
    "vault_master_subaccount_receipt",
    "shortlist_justification_receipt",
    "top500_survivorship_receipt",
    "realtime_accessible_selection_receipt",
    "hyperliquid_budget_calibration_receipt",
    "leader_style_change_receipt",
    "desync_quarantine_receipt",
    "mirror_canonical_path_receipt",
    "watchlist_consent_receipt",
]
