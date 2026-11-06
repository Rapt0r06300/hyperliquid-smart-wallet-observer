"""Fail-closed risk and paper-order controls for Copy-Vault."""

from __future__ import annotations

import math
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


def authoritative_risk_engine_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require one named risk engine authority for each paper decision."""
    if not isinstance(state, Mapping) or not str(state.get("risk_engine_id") or "").strip() or not isinstance(state.get("authoritative"), bool):
        return _base("UNMEASURABLE", reason="risk_engine_identity_missing")
    valid = state["authoritative"] is True and state.get("engine_count") == 1 and state.get("paper_read_only") is True
    return _base("PROVEN" if valid else "REJECTED", verdict="ONE_AUTHORITATIVE_RISK_ENGINE" if valid else "MULTIPLE_OR_NONAUTHORITATIVE_RISK_ENGINES")


def veto_order_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require all safety vetoes to precede a PAPER order decision."""
    if not rows:
        return _base("MORE_DATA", reason="empty_veto_order")
    invalid = []
    for index, row in enumerate(rows):
        veto_order = row.get("veto_order") if isinstance(row, Mapping) else None
        paper_order = row.get("paper_order_order") if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not isinstance(veto_order, int) or not isinstance(paper_order, int) or veto_order >= paper_order or row.get("real_execution") is not False:
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="SAFETY_VETO_PRECEDES_PAPER_ORDER" if not invalid else "SAFETY_VETO_ORDER_INVALID", invalid_rows=invalid)


def leverage_cost_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Expose leverage cost on the canonical 350 USD paper capital."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="leverage_state_missing")
    capital = _number(state.get("capital_usd"))
    leverage = _number(state.get("leverage"))
    cost = _number(state.get("leverage_cost_usd"))
    valid = capital == 350 and leverage is not None and leverage >= 1 and cost is not None and cost >= 0
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="LEVERAGE_COST_ON_CANONICAL_350_USD" if valid else "LEVERAGE_COST_INCOMPLETE", capital_usd=capital, leverage=leverage, leverage_cost_usd=cost)


def vault_concentration_receipt(rows: Sequence[Mapping[str, Any]], *, max_fraction: Any = 0.25) -> dict[str, Any]:
    """Prevent concentration across multiple vaults using explicit allocations."""
    cap = _number(max_fraction)
    if cap is None or cap <= 0 or cap > 1:
        return _base("UNMEASURABLE", reason="invalid_vault_concentration_cap")
    if not rows:
        return _base("MORE_DATA", reason="empty_vault_allocations")
    invalid = []
    for index, row in enumerate(rows):
        fraction = _number(row.get("fraction")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not str(row.get("vault_id") or "").strip() or fraction is None or fraction < 0 or fraction > cap:
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="VAULT_CONCENTRATION_WITHIN_CAP" if not invalid else "VAULT_CONCENTRATION_OVER_CAP", invalid_rows=invalid)


def stream_outage_position_priority_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Prioritize position safety over new entry decisions after a stream outage."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="stream_outage_state_missing")
    valid = state.get("stream_healthy") is False and state.get("position_management_priority") is True and state.get("new_entries_allowed") is False
    return _base("PROVEN" if valid else "REJECTED", verdict="OUTAGE_POSITION_MANAGEMENT_PRIORITY" if valid else "OUTAGE_ENTRY_PATH_PRESENT")


def paper_kill_switch_source_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Distinguish a paper kill switch from stopping a source collector."""
    if not isinstance(state, Mapping) or not isinstance(state.get("paper_kill_switch"), bool) or not isinstance(state.get("sources_stopped"), bool):
        return _base("UNMEASURABLE", reason="kill_switch_source_state_missing")
    valid = state.get("kill_switch_reason") is not None and state.get("source_stop_reason") is not None
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="PAPER_KILL_SWITCH_SEPARATE_FROM_SOURCE_STOP" if valid else "KILL_SWITCH_SOURCE_CAUSE_MISSING")


def drawdown_threshold_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require observed equity and an explicit drawdown threshold crossing."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="drawdown_state_missing")
    drawdown = _number(state.get("drawdown_fraction"))
    threshold = _number(state.get("threshold_fraction"))
    valid = drawdown is not None and threshold is not None and 0 <= drawdown <= 1 and 0 < threshold <= 1 and isinstance(state.get("threshold_crossed"), bool) and state["threshold_crossed"] == (drawdown >= threshold)
    return _base("PROVEN" if valid else "REJECTED", verdict="DRAWDOWN_THRESHOLD_EXPLICIT" if valid else "DRAWDOWN_THRESHOLD_MISMATCH", drawdown_fraction=drawdown, threshold_fraction=threshold)


def env_limits_monotonic_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Reject environment overrides that lower canonical safety limits."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="environment_limits_missing")
    canonical = _number(state.get("canonical_limit"))
    effective = _number(state.get("effective_limit"))
    valid = canonical is not None and effective is not None and effective >= canonical and state.get("env_override_attempted") is False
    return _base("PROVEN" if valid else "REJECTED", verdict="SAFETY_LIMITS_MONOTONIC" if valid else "SAFETY_LIMIT_LOWERED_BY_ENV", canonical_limit=canonical, effective_limit=effective)


def reduce_only_invariant_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require every paper pipeline action to preserve reduce-only state."""
    if not rows:
        return _base("MORE_DATA", reason="empty_pipeline_actions")
    invalid = [index for index, row in enumerate(rows) if not isinstance(row, Mapping) or not str(row.get("pipeline") or "").strip() or row.get("reduce_only") is not True or row.get("real_execution") is not False]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="REDUCE_ONLY_INVARIANT_PRESERVED" if not invalid else "REDUCE_ONLY_INVARIANT_BROKEN", invalid_rows=invalid)


def independent_security_veto_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Record a security veto independently from an AI score."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="security_veto_state_missing")
    valid = state.get("security_veto") is True and state.get("ai_score") is not None and state.get("decision") == "NO_TRADE" and state.get("real_execution") is False
    return _base("PROVEN" if valid else "REJECTED", verdict="SECURITY_VETO_INDEPENDENT_OF_AI_SCORE" if valid else "SECURITY_VETO_NOT_INDEPENDENT")


__all__ = [
    "authoritative_risk_engine_receipt",
    "veto_order_receipt",
    "leverage_cost_receipt",
    "vault_concentration_receipt",
    "stream_outage_position_priority_receipt",
    "paper_kill_switch_source_receipt",
    "drawdown_threshold_receipt",
    "env_limits_monotonic_receipt",
    "reduce_only_invariant_receipt",
    "independent_security_veto_receipt",
]
