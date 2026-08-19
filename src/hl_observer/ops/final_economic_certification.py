from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.simulation.economic_objective import (
    CANONICAL_FAMILIES,
    TARGET_NET_USD,
    canonical_family,
    evaluate_objective,
)

SCHEMA = "hypersmart.final_economic_certification.v1"
CAMPAIGN_DIR = Path("runtime") / "reports" / "economic_campaigns"


def _load_object(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def certify_campaign(expected_family: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    expected = canonical_family(expected_family)
    if payload is None:
        return {
            "family": expected,
            "status": "NO_GO",
            "certified": False,
            "eligible_net_pnl_usd": None,
            "proof_net_pnl_usd": None,
            "liquidatable_net": False,
            "oos_positive": False,
            "forward_positive": False,
            "forward_post_freeze": False,
            "placebo_beaten": False,
            "costs_complete": False,
            "reasons": ["CAMPAIGN_MISSING_OR_UNREADABLE"],
        }

    reasons: list[str] = []
    actual_family = canonical_family(payload.get("family"))
    if actual_family != expected:
        reasons.append(f"FAMILY_MISMATCH:{actual_family or 'MISSING'}")

    recomputed = evaluate_objective(payload)
    stored_status = str(payload.get("objective_status") or "")
    recomputed_status = str(recomputed.get("objective_status") or "")
    if stored_status != recomputed_status:
        reasons.append("OBJECTIVE_STATUS_DRIFT")

    stored_eligible = _number(payload.get("eligible_net_pnl_usd"))
    recomputed_eligible = _number(recomputed.get("eligible_net_pnl_usd"))
    if (stored_eligible is None) != (recomputed_eligible is None):
        reasons.append("ELIGIBLE_NET_DRIFT")
    elif (
        stored_eligible is not None
        and recomputed_eligible is not None
        and not math.isclose(stored_eligible, recomputed_eligible, abs_tol=1e-8)
    ):
        reasons.append("ELIGIBLE_NET_DRIFT")

    if recomputed_status != "ATTEINT":
        reasons.extend(
            str(reason)
            for reason in recomputed.get("objective_reasons", [])
            if str(reason).strip()
        )

    proof_net = _number(recomputed.get("proof_net_pnl_usd"))
    if recomputed_eligible is None or recomputed_eligible < TARGET_NET_USD:
        reasons.append("ELIGIBLE_TARGET_NOT_REACHED")
    if proof_net is None or proof_net < TARGET_NET_USD:
        reasons.append("PROOF_TARGET_NOT_REACHED")

    oos = payload.get("oos") if isinstance(payload.get("oos"), Mapping) else {}
    forward = payload.get("forward") if isinstance(payload.get("forward"), Mapping) else {}
    placebos = payload.get("placebos") if isinstance(payload.get("placebos"), Mapping) else {}
    cost_keys = ("fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd")
    costs_complete = all(
        _number(payload.get(key)) is not None and float(payload.get(key)) >= 0
        for key in cost_keys
    )
    if not costs_complete:
        reasons.append("COSTS_INCOMPLETE")

    oos_positive = (_number(oos.get("net_pnl_usd")) or 0.0) > 0.0
    forward_positive = (_number(forward.get("net_pnl_usd")) or 0.0) > 0.0
    forward_post_freeze = forward.get("post_freeze") is True
    placebo_beaten = placebos.get("beaten") is True
    liquidatable = payload.get("liquidatable_net") is True

    unique_reasons = list(dict.fromkeys(reasons))
    certified = (
        actual_family == expected
        and recomputed_status == "ATTEINT"
        and recomputed_eligible is not None
        and recomputed_eligible >= TARGET_NET_USD
        and proof_net is not None
        and proof_net >= TARGET_NET_USD
        and liquidatable
        and costs_complete
        and oos_positive
        and forward_positive
        and forward_post_freeze
        and placebo_beaten
        and not unique_reasons
    )
    return {
        "family": expected,
        "status": "CERTIFIED" if certified else "NO_GO",
        "certified": certified,
        "eligible_net_pnl_usd": recomputed_eligible,
        "proof_net_pnl_usd": proof_net,
        "liquidatable_net": liquidatable,
        "oos_positive": oos_positive,
        "forward_positive": forward_positive,
        "forward_post_freeze": forward_post_freeze,
        "placebo_beaten": placebo_beaten,
        "costs_complete": costs_complete,
        "reasons": unique_reasons,
    }


def certify_workspace(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace).resolve()
    rows: dict[str, dict[str, Any]] = {}
    for family in CANONICAL_FAMILIES:
        payload = _load_object(root / CAMPAIGN_DIR / f"{family}.json")
        rows[family] = certify_campaign(family, payload)

    all_certified = all(row.get("certified") is True for row in rows.values())
    return {
        "schema": SCHEMA,
        "status": "ALL_FAMILIES_CERTIFIED" if all_certified else "NO_GO",
        "all_families_certified": all_certified,
        "target_net_usd_per_family": TARGET_NET_USD,
        "cross_family_pnl_compensation_allowed": False,
        "families": rows,
        "paper_only": True,
        "real_execution": False,
    }


__all__ = [
    "CAMPAIGN_DIR",
    "SCHEMA",
    "certify_campaign",
    "certify_workspace",
]
