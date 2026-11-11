"""Final fail-closed economic certification for the +5 USD/day research target.

The existing canonical certification proves economic integrity, OOS,
post-freeze forward evidence, costs, provenance and cross-family identity. This
module adds a time-normalized requirement bound to a verified forward wall
clock and collection-coverage receipt.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.ops.final_economic_certification import (
    CAMPAIGN_DIR,
    certify_campaign,
    certify_workspace,
)
from hl_observer.simulation.economic_objective import (
    CANONICAL_FAMILIES,
    TARGET_NET_USD_PER_DAY,
)

SCHEMA = "hypersmart.daily_economic_certification.v1"
MIN_FORWARD_OBSERVATION_SECONDS = 30 * 86_400.0
MIN_FORWARD_COVERAGE_RATIO = 0.99
MIN_FORWARD_TRADE_COUNT = 30


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _load_campaign(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def forward_coverage_gate(
    payload: Mapping[str, Any] | None,
    *,
    min_observation_seconds: float = MIN_FORWARD_OBSERVATION_SECONDS,
    min_coverage_ratio: float = MIN_FORWARD_COVERAGE_RATIO,
    min_trade_count: int = MIN_FORWARD_TRADE_COUNT,
) -> dict[str, Any]:
    """Validate temporal forward quality without looking at a PnL target."""
    forward = payload.get("forward") if isinstance(payload, Mapping) else None
    forward = forward if isinstance(forward, Mapping) else {}
    freeze = payload.get("parameter_freeze") if isinstance(payload, Mapping) else None
    freeze = freeze if isinstance(freeze, Mapping) else {}
    reasons: list[str] = []
    seconds = _number(forward.get("observation_seconds"))
    start_ms = _number(forward.get("observation_start_ms"))
    end_ms = _number(forward.get("observation_end_ms"))
    freeze_ms = _number(freeze.get("frozen_at_ms"))
    coverage_ratio = _number(forward.get("observation_coverage_ratio"))
    trade_count = _number(forward.get("sample_count"))
    if seconds is None or seconds <= 0:
        reasons.append("FORWARD_OBSERVATION_DURATION_INVALID")
    if start_ms is None or end_ms is None or end_ms <= start_ms:
        reasons.append("FORWARD_OBSERVATION_CLOCK_INVALID")
    if freeze_ms is None or start_ms is None or start_ms <= freeze_ms:
        reasons.append("FORWARD_OBSERVATION_NOT_STRICTLY_POST_FREEZE")
    if forward.get("post_freeze") is not True:
        reasons.append("FORWARD_DAILY_POST_FREEZE_FLAG_MISSING")
    if coverage_ratio is None or not 0.0 <= coverage_ratio <= 1.0:
        reasons.append("FORWARD_OBSERVATION_COVERAGE_INVALID")
    elif coverage_ratio < float(min_coverage_ratio):
        reasons.append("FORWARD_OBSERVATION_COVERAGE_TOO_LOW")
    if trade_count is None or trade_count < int(min_trade_count):
        reasons.append("FORWARD_TRADE_COUNT_TOO_SMALL")
    if not str(forward.get("observation_source") or "").strip():
        reasons.append("FORWARD_OBSERVATION_SOURCE_MISSING")
    if seconds is not None and start_ms is not None and end_ms is not None and end_ms > start_ms:
        clock_seconds = (end_ms - start_ms) / 1000.0
        if not math.isclose(seconds, clock_seconds, rel_tol=0.0, abs_tol=1e-3):
            reasons.append("FORWARD_OBSERVATION_DURATION_MISMATCH")
        elif clock_seconds < float(min_observation_seconds):
            reasons.append("FORWARD_DAILY_PROOF_WINDOW_TOO_SHORT")
    return {
        "status": "PROVEN" if not reasons else "UNMEASURABLE",
        "temporal_quality_proven": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "observation_seconds": seconds,
        "observation_start_ms": start_ms,
        "observation_end_ms": end_ms,
        "frozen_at_ms": freeze_ms,
        "coverage_ratio": coverage_ratio,
        "trade_count": int(trade_count) if trade_count is not None else None,
        "target_independent": True,
    }


def classify_daily_target_evidence(
    payload: Mapping[str, Any] | None,
    *,
    target_net_usd_per_day: float = TARGET_NET_USD_PER_DAY,
) -> dict[str, Any]:
    """Classify measured progress without weakening the certification gate."""
    target = _number(target_net_usd_per_day)
    gate = forward_coverage_gate(payload)
    forward = payload.get("forward") if isinstance(payload, Mapping) else None
    forward = forward if isinstance(forward, Mapping) else {}
    net = _number(forward.get("net_pnl_usd"))
    seconds = _number(gate.get("observation_seconds"))
    rate = None
    if gate["temporal_quality_proven"] and net is not None and seconds is not None and seconds > 0:
        rate = net / (seconds / 86_400.0)
    if target is None or target < 0:
        status, reason = "UNMEASURABLE", "TARGET_INVALID"
    elif not gate["temporal_quality_proven"] or rate is None:
        status, reason = "UNMEASURABLE", "FORWARD_NET_UNMEASURED"
    elif rate >= target:
        status, reason = "PROVEN", None
    elif rate > 0:
        status, reason = "PROMISING", "POSITIVE_BELOW_TARGET"
    else:
        status, reason = "REJECTED", "NON_POSITIVE_FORWARD_RATE"
    return {
        "status": status,
        "reason": reason,
        "forward_net_pnl_usd_per_day": round(rate, 8) if rate is not None else None,
        "target_net_usd_per_day": target,
        "target_gate_unchanged": True,
        "temporal_quality": gate,
        "paper_read_only": True,
        "real_execution": False,
    }


def apply_daily_gate(
    base_result: Mapping[str, Any],
    payload: Mapping[str, Any] | None,
    *,
    target_net_usd_per_day: float = TARGET_NET_USD_PER_DAY,
    min_forward_observation_seconds: float = MIN_FORWARD_OBSERVATION_SECONDS,
    min_forward_coverage_ratio: float = MIN_FORWARD_COVERAGE_RATIO,
) -> dict[str, Any]:
    """Add the verified +5 USD/day requirement without weakening base proof."""

    result = dict(base_result)
    reasons = [str(value) for value in result.get("reasons", []) if str(value)]
    evidence = payload if isinstance(payload, Mapping) else {}
    temporal_gate = forward_coverage_gate(evidence)
    reasons.extend(temporal_gate["reasons"])
    forward = evidence.get("forward") if isinstance(evidence.get("forward"), Mapping) else {}
    freeze = (
        evidence.get("parameter_freeze")
        if isinstance(evidence.get("parameter_freeze"), Mapping)
        else {}
    )

    seconds = _number(forward.get("observation_seconds"))
    start_ms = _number(forward.get("observation_start_ms"))
    end_ms = _number(forward.get("observation_end_ms"))
    freeze_ms = _number(freeze.get("frozen_at_ms"))
    coverage_ratio = _number(forward.get("observation_coverage_ratio"))
    coverage_verified = forward.get("observation_coverage_verified") is True
    observation_source = str(forward.get("observation_source") or "").strip()
    net = _number(forward.get("net_pnl_usd"))
    trade_count = _number(forward.get("sample_count"))

    if trade_count is None:
        reasons.append("FORWARD_TRADE_COUNT_MISSING")
    elif trade_count < MIN_FORWARD_TRADE_COUNT:
        reasons.append("FORWARD_TRADE_COUNT_TOO_SMALL")

    clock_seconds: float | None = None
    clock_consistent = False
    if seconds is None:
        reasons.append("FORWARD_OBSERVATION_DURATION_MISSING")
    elif seconds <= 0.0:
        reasons.append("FORWARD_OBSERVATION_DURATION_INVALID")

    if start_ms is None or end_ms is None:
        reasons.append("FORWARD_OBSERVATION_CLOCK_MISSING")
    elif end_ms <= start_ms:
        reasons.append("FORWARD_OBSERVATION_CLOCK_INVALID")
    else:
        clock_seconds = (float(end_ms) - float(start_ms)) / 1000.0
        if seconds is not None and seconds > 0.0:
            clock_consistent = math.isclose(
                float(seconds), clock_seconds, rel_tol=0.0, abs_tol=1e-3
            )
            if not clock_consistent:
                reasons.append("FORWARD_OBSERVATION_DURATION_MISMATCH")

    if freeze_ms is None:
        reasons.append("FORWARD_FREEZE_CLOCK_MISSING")
    elif start_ms is None or start_ms <= freeze_ms:
        reasons.append("FORWARD_OBSERVATION_NOT_STRICTLY_POST_FREEZE")
    if forward.get("post_freeze") is not True:
        reasons.append("FORWARD_DAILY_POST_FREEZE_FLAG_MISSING")

    if not coverage_verified:
        reasons.append("FORWARD_OBSERVATION_COVERAGE_UNVERIFIED")
    if coverage_ratio is None:
        reasons.append("FORWARD_OBSERVATION_COVERAGE_MISSING")
    elif not 0.0 <= coverage_ratio <= 1.0:
        reasons.append("FORWARD_OBSERVATION_COVERAGE_INVALID")
    elif coverage_ratio < float(min_forward_coverage_ratio):
        reasons.append("FORWARD_OBSERVATION_COVERAGE_TOO_LOW")
    if not observation_source:
        reasons.append("FORWARD_OBSERVATION_SOURCE_MISSING")

    verified_seconds = (
        clock_seconds
        if seconds is not None
        and seconds > 0.0
        and clock_seconds is not None
        and clock_consistent
        else None
    )
    rate: float | None = None
    if verified_seconds is not None:
        if verified_seconds < float(min_forward_observation_seconds):
            reasons.append("FORWARD_DAILY_PROOF_WINDOW_TOO_SHORT")
        if net is not None:
            rate = float(net) / (verified_seconds / 86_400.0)
    # Politique canonique : le repère journalier est une mesure rapportée, jamais une porte.
    # Seuls bloquent : un net forward non mesuré ou non strictement positif, et toute raison
    # structurelle (fenêtre, couverture, horloge, nombre de trades, post-gel).
    reference_reasons: list[str] = []
    if rate is None:
        reasons.append("FORWARD_DAILY_NET_UNMEASURED")
    elif rate <= 0.0:
        reasons.append("FORWARD_DAILY_NET_NOT_POSITIVE")
    elif rate < float(target_net_usd_per_day):
        reference_reasons.append("TARGET_NET_USD_PER_DAY_NOT_REACHED")

    daily_target_reached = bool(
        verified_seconds is not None
        and verified_seconds >= float(min_forward_observation_seconds)
        and freeze_ms is not None
        and start_ms is not None
        and start_ms > freeze_ms
        and forward.get("post_freeze") is True
        and coverage_verified
        and coverage_ratio is not None
        and coverage_ratio >= float(min_forward_coverage_ratio)
        and observation_source
        and trade_count is not None
        and trade_count >= MIN_FORWARD_TRADE_COUNT
        and rate is not None
        and rate >= float(target_net_usd_per_day)
    )
    structural_daily_gate_reached = bool(
        temporal_gate["temporal_quality_proven"] and rate is not None
    )
    positive_forward_net = bool(rate is not None and rate > 0.0)
    quality_certified = bool(
        result.get("certified") is True
        and structural_daily_gate_reached
        and positive_forward_net
    )
    blocking_reasons = list(dict.fromkeys(reasons))
    certified = bool(quality_certified and not blocking_reasons)
    if not certified:
        # A positive pooled OOS+forward total is diagnostic only when the
        # independent forward quality gate has not passed.
        result["eligible_net_pnl_usd"] = None
    result.update(
        {
            "status": "CERTIFIED" if certified else "NO_GO",
            "certified": certified,
            "target_net_usd_per_day": float(target_net_usd_per_day),
            "minimum_forward_observation_seconds": float(min_forward_observation_seconds),
            "minimum_forward_coverage_ratio": float(min_forward_coverage_ratio),
            "minimum_forward_trade_count": MIN_FORWARD_TRADE_COUNT,
            "forward_trade_count": int(trade_count) if trade_count is not None else None,
            "forward_observation_start_ms": start_ms,
            "forward_observation_end_ms": end_ms,
            "forward_observation_seconds": verified_seconds,
            "forward_observation_days": (
                round(verified_seconds / 86_400.0, 8)
                if verified_seconds is not None
                else None
            ),
            "forward_observation_coverage_ratio": coverage_ratio,
            "forward_observation_coverage_verified": coverage_verified,
            "forward_observation_source": observation_source or None,
            "forward_net_pnl_usd_per_day": round(rate, 8) if rate is not None else None,
            "quality_certified": quality_certified,
            "positive_forward_net": positive_forward_net,
            "historical_target_reached": daily_target_reached,
            "structural_daily_gate_reached": structural_daily_gate_reached,
            "temporal_quality_gate": temporal_gate,
            "daily_target_reached": daily_target_reached,
            "reference_target_is_gate": False,
            "reference_reasons": reference_reasons,
            "reasons": blocking_reasons,
        }
    )
    return result


def certify_daily_campaign(
    expected_family: str,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Run the existing strict certification, then the +5 USD/day gate."""

    return apply_daily_gate(certify_campaign(expected_family, payload), payload)


def certify_daily_workspace(workspace: str | Path) -> dict[str, Any]:
    """Require all canonical families to pass both base and daily certification."""

    root = Path(workspace).resolve()
    base = certify_workspace(root)
    base_rows = base.get("families") if isinstance(base.get("families"), Mapping) else {}
    rows: dict[str, dict[str, Any]] = {}
    for family in CANONICAL_FAMILIES:
        payload = _load_campaign(root / CAMPAIGN_DIR / f"{family}.json")
        base_row = base_rows.get(family) if isinstance(base_rows.get(family), Mapping) else {
            "family": family,
            "status": "NO_GO",
            "certified": False,
            "reasons": ["BASE_CERTIFICATION_RESULT_MISSING"],
        }
        rows[family] = apply_daily_gate(base_row, payload)

    no_reuse = bool(
        isinstance(base.get("cross_family_trade_reuse_audit"), Mapping)
        and base["cross_family_trade_reuse_audit"].get("no_reuse") is True
    )
    all_certified = bool(no_reuse and all(row.get("certified") is True for row in rows.values()))
    return {
        **base,
        "schema": SCHEMA,
        "status": "ALL_FAMILIES_CERTIFIED_DAILY" if all_certified else "NO_GO",
        "all_families_certified": all_certified,
        "target_net_usd_per_day_per_family": TARGET_NET_USD_PER_DAY,
        "minimum_forward_observation_seconds_per_family": MIN_FORWARD_OBSERVATION_SECONDS,
        "minimum_forward_coverage_ratio_per_family": MIN_FORWARD_COVERAGE_RATIO,
        "minimum_forward_trade_count_per_family": MIN_FORWARD_TRADE_COUNT,
        "daily_rate_basis": "VERIFIED_STRICT_POST_FREEZE_FORWARD_WALL_CLOCK",
        "families": rows,
    }


def daily_certification_safety_receipt(result: object) -> dict[str, object]:
    """Validate certification output without manufacturing a positive verdict."""
    families = result.get("families") if isinstance(result, Mapping) else None
    valid = (
        isinstance(result, Mapping)
        and result.get("status") in {"ALL_FAMILIES_CERTIFIED_DAILY", "NO_GO"}
        and isinstance(result.get("all_families_certified"), bool)
        and result.get("daily_rate_basis") == "VERIFIED_STRICT_POST_FREEZE_FORWARD_WALL_CLOCK"
        and isinstance(families, Mapping)
        and result.get("paper_read_only", True) is True
        and result.get("real_execution", False) is False
        and result.get("automatic_activation", False) is False
    )
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "verdict": "DAILY_CERTIFICATION_SAFE" if valid else "DAILY_CERTIFICATION_UNSAFE",
        "paper_read_only": True,
        "real_execution": False,
        "economic_verdict": "UNMEASURABLE" if not (isinstance(result, Mapping) and result.get("all_families_certified") is True) else "PROVEN_EXTERNAL_RESULT_REQUIRED",
        "automatic_activation": False,
        "fail_closed": not valid,
    }


__all__ = [
    "MIN_FORWARD_COVERAGE_RATIO",
    "MIN_FORWARD_OBSERVATION_SECONDS",
    "MIN_FORWARD_TRADE_COUNT",
    "forward_coverage_gate",
    "classify_daily_target_evidence",
    "SCHEMA",
    "TARGET_NET_USD_PER_DAY",
    "apply_daily_gate",
    "certify_daily_campaign",
    "certify_daily_workspace",
    "daily_certification_safety_receipt",
]
