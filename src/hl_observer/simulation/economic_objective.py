"""Strict, shared proof contract for per-family paper economic objectives.

The contract deliberately separates a displayed/modelled PnL from a PnL that
is eligible for an economic claim.  Missing costs, open positions, duplicate
identities, absent forward evidence, or a non-paper execution mode all fail
closed.  No function in this module creates a signal or a fill.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

TARGET_NET_USD = 4.0
STARTING_CAPITAL_USD = 1000.0
CANONICAL_FAMILIES = (
    "copy_vault",
    "lead_lag",
    "cross_venue_dislocation_v2",
)

_ALIASES = {
    "copy-vault": "copy_vault",
    "copy_vault": "copy_vault",
    "lead-lag": "lead_lag",
    "lead_lag": "lead_lag",
    "arbitrage": "cross_venue_dislocation_v2",
    "cross_venue_dislocation": "cross_venue_dislocation_v2",
    "cross_venue_dislocation_v2": "cross_venue_dislocation_v2",
}


def canonical_family(value: object) -> str:
    """Collapse aliases so the active arbitrage family can never be counted twice."""

    normalized = str(value or "").strip().lower().replace(" ", "_")
    return _ALIASES.get(normalized, normalized)


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def evaluate_objective(
    evidence: Mapping[str, Any],
    *,
    target_net_usd: float = TARGET_NET_USD,
) -> dict[str, Any]:
    """Evaluate one family against the strict realized-net proof contract."""

    issues: list[str] = []
    family = canonical_family(evidence.get("family"))
    if family not in CANONICAL_FAMILIES:
        issues.append("NON_CANONICAL_OR_INACTIVE_FAMILY")
    if evidence.get("paper_read_only") is not True or evidence.get("real_execution") is not False:
        issues.append("NOT_PAPER_READ_ONLY")
    capital = _number(evidence.get("starting_capital_usd"))
    if capital != STARTING_CAPITAL_USD:
        issues.append("INVALID_STARTING_CAPITAL")
    if evidence.get("parameters_frozen") is not True:
        issues.append("PARAMETERS_NOT_FROZEN_BEFORE_EVALUATION")

    opened = _number(evidence.get("opened_positions"))
    closed = _number(evidence.get("closed_positions"))
    if opened is None or closed is None or opened <= 0 or opened != closed:
        issues.append("POSITIONS_NOT_FULLY_OPENED_AND_CLOSED")
    if family == "cross_venue_dislocation_v2" and evidence.get("all_positions_two_leg_closed") is not True:
        issues.append("CROSS_VENUE_TWO_LEG_CLOSE_PROOF_MISSING")

    metric_keys = (
        "gross_pnl_usd",
        "fees_usd",
        "spread_cost_usd",
        "slippage_cost_usd",
        "latency_cost_usd",
        "net_pnl_usd",
    )
    metrics = {key: _number(evidence.get(key)) for key in metric_keys}
    missing = [key for key, value in metrics.items() if value is None]
    issues.extend(f"UNMEASURED:{key}" for key in missing)
    for key in ("fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd"):
        if metrics[key] is not None and metrics[key] < 0:
            issues.append(f"NEGATIVE_COST:{key}")
    if not missing:
        expected = metrics["gross_pnl_usd"] - sum(
            metrics[key]
            for key in ("fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd")
        )
        if not math.isclose(expected, metrics["net_pnl_usd"], abs_tol=1e-4):
            issues.append("ECONOMIC_RECONCILIATION_FAILED")

    liquidatable_net = evidence.get("liquidatable_net")
    if liquidatable_net is None:
        # Read legacy artifacts without emitting two case-only keys in new JSON.
        liquidatable_net = evidence.get("LIQUIDATABLE_NET")
    if liquidatable_net is not True:
        issues.append("NOT_LIQUIDATABLE_NET")
    duplicates = _number(evidence.get("duplicate_trade_ids"))
    trade_count = _number(evidence.get("trade_ids_count"))
    trade_hash = str(evidence.get("trade_ids_sha256") or "")
    if duplicates != 0:
        issues.append("DUPLICATE_TRADE_IDENTITIES")
    if closed is None or trade_count != closed or len(trade_hash) != 64:
        issues.append("TRADE_ID_PROOF_INCOMPLETE")

    oos = evidence.get("oos")
    forward = evidence.get("forward")
    placebos = evidence.get("placebos")
    oos_net = _number(oos.get("net_pnl_usd")) if isinstance(oos, Mapping) else None
    oos_count = _number(oos.get("sample_count")) if isinstance(oos, Mapping) else None
    forward_net = (
        _number(forward.get("net_pnl_usd")) if isinstance(forward, Mapping) else None
    )
    forward_count = (
        _number(forward.get("sample_count")) if isinstance(forward, Mapping) else None
    )
    if not isinstance(oos, Mapping) or oos_net is None:
        issues.append("OOS_PROOF_MISSING")
    elif oos_count is None or oos_count <= 0:
        issues.append("OOS_SAMPLE_MISSING")
    elif oos_net <= 0:
        issues.append("OOS_NET_NOT_POSITIVE")
    elif oos.get("no_lookahead") is not True:
        issues.append("OOS_NO_LOOKAHEAD_PROOF_MISSING")
    if not isinstance(forward, Mapping) or forward_net is None:
        issues.append("FORWARD_POST_FREEZE_PROOF_MISSING")
    elif forward_count is None or forward_count <= 0:
        issues.append("FORWARD_SAMPLE_MISSING")
    elif forward_net <= 0:
        issues.append("FORWARD_NET_NOT_POSITIVE")
    elif forward.get("post_freeze") is not True:
        issues.append("FORWARD_NOT_PROVEN_POST_FREEZE")
    if not isinstance(placebos, Mapping) or placebos.get("beaten") is not True:
        issues.append("PLACEBO_NOT_BEATEN")

    proof_net = (
        oos_net + forward_net
        if oos_net is not None
        and forward_net is not None
        and oos_count is not None
        and oos_count > 0
        and forward_count is not None
        and forward_count > 0
        else None
    )
    if proof_net is None or proof_net < float(target_net_usd):
        issues.append("TARGET_NET_USD_NOT_REACHED")
    unique_issues = list(dict.fromkeys(issues))
    return {
        "family": family,
        "target_net_usd": float(target_net_usd),
        "proof_net_pnl_usd": proof_net,
        "eligible_net_pnl_usd": proof_net if not unique_issues else None,
        "objective_status": "ATTEINT" if not unique_issues else "NON_ATTEINT",
        "objective_reasons": unique_issues,
    }


__all__ = [
    "CANONICAL_FAMILIES",
    "STARTING_CAPITAL_USD",
    "TARGET_NET_USD",
    "canonical_family",
    "evaluate_objective",
]
