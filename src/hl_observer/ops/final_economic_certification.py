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
from hl_observer.simulation.economic_proof_identity import (
    audit_family_event_sets,
    proof_events,
)

SCHEMA = "hypersmart.final_economic_certification.v2"
CAMPAIGN_DIR = Path("runtime") / "reports" / "economic_campaigns"
RAW_DIR = CAMPAIGN_DIR / "raw"


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


def _sample_count(segment: object) -> int:
    if not isinstance(segment, Mapping):
        return 0
    value = _number(segment.get("sample_count"))
    return max(0, int(value or 0))


def _raw_trade_rows(family: str, raw: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """Return the raw rows underlying the OOS/forward campaign proof.

    The three families intentionally keep their native ledgers.  We only
    normalise them at the final gate, after each family has already produced
    its own immutable evidence.
    """

    if not isinstance(raw, Mapping):
        return []
    normalized = canonical_family(family)
    source: object
    if normalized == "lead_lag":
        executable = raw.get("executable_campaign")
        source = executable.get("trades") if isinstance(executable, Mapping) else None
    else:
        source = raw.get("trades")
    if not isinstance(source, list):
        return []
    return [row for row in source if isinstance(row, Mapping)]


def _append_reason(row: dict[str, Any], reason: str) -> None:
    reasons = [str(value) for value in row.get("reasons", []) if str(value)]
    if reason not in reasons:
        reasons.append(reason)
    row["reasons"] = reasons
    row["certified"] = False
    row["status"] = "NO_GO"


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
    campaigns: dict[str, dict[str, Any] | None] = {}
    identity_audits: dict[str, dict[str, Any]] = {}

    for family in CANONICAL_FAMILIES:
        campaign = _load_object(root / CAMPAIGN_DIR / f"{family}.json")
        campaigns[family] = campaign
        rows[family] = certify_campaign(family, campaign)

        raw = _load_object(root / RAW_DIR / f"{family}.json")
        audit = proof_events(_raw_trade_rows(family, raw))
        expected_proof_rows = (
            _sample_count(campaign.get("oos")) + _sample_count(campaign.get("forward"))
            if isinstance(campaign, Mapping)
            else 0
        )
        audit["expected_proof_rows"] = expected_proof_rows
        audit["count_matches_campaign"] = audit.get("proof_rows") == expected_proof_rows
        audit["complete"] = bool(
            audit.get("complete") is True
            and expected_proof_rows > 0
            and audit["count_matches_campaign"] is True
        )
        identity_audits[family] = audit
        if rows[family].get("certified") is True and audit["complete"] is not True:
            _append_reason(rows[family], "GLOBAL_TRADE_IDENTITY_PROOF_INCOMPLETE")

    global_audit = audit_family_event_sets(identity_audits)

    # A duplicate canonical event inside one family is forbidden even when the
    # native IDs differ or when the same episode was moved OOS -> forward.
    intra = global_audit.get("intra_family_duplicate_global_events")
    if isinstance(intra, Mapping):
        for family, count in intra.items():
            if int(count or 0) > 0 and family in rows:
                _append_reason(rows[family], "GLOBAL_TRADE_IDENTITY_DUPLICATE")

    # Cross-family overlap invalidates both owners of the reused event.  This
    # is independent from PnL and therefore cannot be compensated by a third
    # profitable family.
    pairwise = global_audit.get("pairwise")
    if isinstance(pairwise, Mapping):
        for pair, detail in pairwise.items():
            if not isinstance(detail, Mapping) or int(detail.get("collision_count") or 0) <= 0:
                continue
            left, separator, right = str(pair).partition("__")
            if not separator:
                continue
            for family in (left, right):
                if family in rows:
                    _append_reason(rows[family], "CROSS_FAMILY_TRADE_REUSE")

    all_certified = bool(
        global_audit.get("no_reuse") is True
        and all(row.get("certified") is True for row in rows.values())
    )
    public_identity_audits = {
        family: {
            "proof_rows": audit.get("proof_rows"),
            "expected_proof_rows": audit.get("expected_proof_rows"),
            "canonical_events": audit.get("canonical_events"),
            "missing_identity_rows": audit.get("missing_identity_rows"),
            "duplicate_global_events": audit.get("duplicate_global_events"),
            "count_matches_campaign": audit.get("count_matches_campaign"),
            "complete": audit.get("complete"),
        }
        for family, audit in identity_audits.items()
    }
    return {
        "schema": SCHEMA,
        "status": "ALL_FAMILIES_CERTIFIED" if all_certified else "NO_GO",
        "all_families_certified": all_certified,
        "target_net_usd_per_family": TARGET_NET_USD,
        "cross_family_pnl_compensation_allowed": False,
        "cross_family_trade_reuse_allowed": False,
        "global_trade_identity_audits": public_identity_audits,
        "cross_family_trade_reuse_audit": global_audit,
        "families": rows,
        "paper_only": True,
        "real_execution": False,
    }


__all__ = [
    "CAMPAIGN_DIR",
    "RAW_DIR",
    "SCHEMA",
    "certify_campaign",
    "certify_workspace",
]
