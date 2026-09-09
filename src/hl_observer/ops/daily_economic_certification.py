"""Final fail-closed economic certification for the real +4 USD/day target.

The existing canonical certification still proves economic integrity, OOS,
post-freeze forward evidence, costs, provenance and cross-family identity.  This
module adds the missing time-normalized requirement: each family must also
produce at least +4.00 USD net per full observed forward day.
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
) -> dict[str, Any]:
    """Add the time-normalized forward requirement without weakening base proof."""

    result = dict(base_result)
    reasons = [str(value) for value in result.get("reasons", []) if str(value)]
    evidence = payload if isinstance(payload, Mapping) else {}
    forward = evidence.get("forward") if isinstance(evidence.get("forward"), Mapping) else {}
    seconds = _number(forward.get("observation_seconds"))
    net = _number(forward.get("net_pnl_usd"))

    rate: float | None = None
    if seconds is None:
        reasons.append("FORWARD_OBSERVATION_DURATION_MISSING")
    elif seconds <= 0.0:
        reasons.append("FORWARD_OBSERVATION_DURATION_INVALID")
    else:
        if seconds < float(min_forward_observation_seconds):
            reasons.append("FORWARD_DAILY_PROOF_WINDOW_TOO_SHORT")
        if net is not None:
            rate = float(net) / (float(seconds) / 86_400.0)
        if rate is None:
            reasons.append("FORWARD_DAILY_NET_UNMEASURED")
        elif rate < float(target_net_usd_per_day):
            reasons.append("TARGET_NET_USD_PER_DAY_NOT_REACHED")

    daily_target_reached = bool(
        seconds is not None
        and seconds >= float(min_forward_observation_seconds)
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
            "forward_observation_seconds": seconds,
            "forward_observation_days": (
                round(float(seconds) / 86_400.0, 8)
                if seconds is not None and seconds > 0.0
                else None
            ),
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
        "daily_rate_basis": "STRICT_POST_FREEZE_FORWARD_WALL_CLOCK",
        "families": rows,
    }


__all__ = [
    "MIN_FORWARD_OBSERVATION_SECONDS",
    "SCHEMA",
    "TARGET_NET_USD_PER_DAY",
    "apply_daily_gate",
    "certify_daily_campaign",
    "certify_daily_workspace",
]
