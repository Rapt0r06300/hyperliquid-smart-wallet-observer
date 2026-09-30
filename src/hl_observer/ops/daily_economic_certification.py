"""Final fail-closed economic certification for the real +4 USD/day target.

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
from hl_observer.simulation.economic_objective import CANONICAL_FAMILIES

SCHEMA = "hypersmart.daily_economic_certification.v1"
TARGET_NET_USD_PER_DAY = 4.0
MIN_FORWARD_OBSERVATION_SECONDS = 86_400.0
MIN_FORWARD_COVERAGE_RATIO = 0.99


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


def apply_daily_gate(
    base_result: Mapping[str, Any],
    payload: Mapping[str, Any] | None,
    *,
    target_net_usd_per_day: float = TARGET_NET_USD_PER_DAY,
    min_forward_observation_seconds: float = MIN_FORWARD_OBSERVATION_SECONDS,
    min_forward_coverage_ratio: float = MIN_FORWARD_COVERAGE_RATIO,
) -> dict[str, Any]:
    """Add the verified +4 USD/day requirement without weakening base proof."""

    result = dict(base_result)
    reasons = [str(value) for value in result.get("reasons", []) if str(value)]
    evidence = payload if isinstance(payload, Mapping) else {}
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
    if rate is None:
        reasons.append("FORWARD_DAILY_NET_UNMEASURED")
    elif rate < float(target_net_usd_per_day):
        reasons.append("TARGET_NET_USD_PER_DAY_NOT_REACHED")

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
        and rate is not None
        and rate >= float(target_net_usd_per_day)
    )
    certified = bool(result.get("certified") is True and daily_target_reached)
    result.update(
        {
            "status": "CERTIFIED" if certified else "NO_GO",
            "certified": certified,
            "target_net_usd_per_day": float(target_net_usd_per_day),
            "minimum_forward_observation_seconds": float(min_forward_observation_seconds),
            "minimum_forward_coverage_ratio": float(min_forward_coverage_ratio),
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
            "daily_target_reached": daily_target_reached,
            "reasons": list(dict.fromkeys(reasons)),
        }
    )
    return result


def certify_daily_campaign(
    expected_family: str,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Run the existing strict certification, then the +4 USD/day gate."""

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
        "daily_rate_basis": "VERIFIED_STRICT_POST_FREEZE_FORWARD_WALL_CLOCK",
        "families": rows,
    }


__all__ = [
    "MIN_FORWARD_COVERAGE_RATIO",
    "MIN_FORWARD_OBSERVATION_SECONDS",
    "SCHEMA",
    "TARGET_NET_USD_PER_DAY",
    "apply_daily_gate",
    "certify_daily_campaign",
    "certify_daily_workspace",
]
