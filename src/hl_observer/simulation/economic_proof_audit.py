"""Line-level economic proof audit for the three active paper families.

The campaign builders validate their public summaries.  This module goes one
level deeper: it recomputes the ledger from raw closed trades, checks temporal
segments and parameter freezes, and reconciles the result with the published
campaign.  It never creates a signal, changes parameters, or executes an
order.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hl_observer.economics.assumptions import ZeroCostReason
from hl_observer.economics.hardcode_scanner import (
    PROPOSAL_DISPOSITION,
    scan_economic_paths,
)
from hl_observer.economics.hardcode_scanner import (
    SCHEMA_VERSION as HARDCODE_SCAN_SCHEMA,
)
from hl_observer.economics.proof_binding import audit_economic_contract_receipt

from .economic_campaigns import REPORT_DIR
from .economic_objective import (
    CANONICAL_FAMILIES,
    TARGET_NET_USD,
    canonical_family,
    evaluate_objective,
)

SCHEMA_VERSION = "hypersmart.economic_proof_audit.v1"
INDEPENDENT_AUDIT_SCHEMA = "hypersmart.independent_economic_audit.v1"
AUDIT_JSON = "HYPERSMART_ECONOMIC_PROOF_AUDIT.json"
AUDIT_MARKDOWN = "HYPERSMART_ECONOMIC_PROOF_AUDIT.md"
_SEGMENTS = ("train", "validation", "oos", "forward")
_COST_KEYS = (
    "fees_usd",
    "spread_cost_usd",
    "slippage_cost_usd",
    "latency_cost_usd",
)
_ECONOMIC_KEYS = ("gross_pnl_usd", *_COST_KEYS, "net_pnl_usd")
_CONTROL_NAMES = (
    "reconciliation_identities",
    "missing_costs",
    "stale_assumptions",
    "duplicate_charging",
    "hidden_hardcodes",
    "unsupported_zeros",
    "dependency_mismatch",
    "source_freshness",
)
_COMPONENT_TO_COST_KEY = {
    "fees": "fees_usd",
    "spread": "spread_cost_usd",
    "slippage": "slippage_cost_usd",
    "latency": "latency_cost_usd",
}
_ALLOWED_ZERO_REASONS = {reason.value for reason in ZeroCostReason}
_MAX_CONTROL_ISSUES = 32


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _rounded(value: float) -> float:
    return round(float(value), 8)


def _hash_ids(values: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(values))).encode("utf-8")).hexdigest()


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return _rounded(ordered[index])


def _distribution(values: Iterable[object]) -> dict[str, Any]:
    numbers = [number for value in values if (number := _number(value)) is not None]
    return {
        "count": len(numbers),
        "min": _rounded(min(numbers)) if numbers else None,
        "p50": _rounded(statistics.median(numbers)) if numbers else None,
        "p95": _percentile(numbers, 0.95),
        "max": _rounded(max(numbers)) if numbers else None,
    }


def _raw_trades(family: str, raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if family == "lead_lag":
        executable = raw.get("executable_campaign")
        rows = executable.get("trades") if isinstance(executable, Mapping) else None
    else:
        rows = raw.get("trades")
    return [row for row in rows or [] if isinstance(row, Mapping)]


def _is_liquidatable(row: Mapping[str, Any]) -> bool:
    value = row.get("liquidatable_net")
    if value is None:
        value = row.get("LIQUIDATABLE_NET")
    return value is True


def _timestamp_ms(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(row.get(key))
        if value is None:
            continue
        return value / 1_000_000.0 if key.endswith("_ns") else value
    return None


def _trade_economics(family: str, row: Mapping[str, Any]) -> dict[str, float | None]:
    if family != "cross_venue_dislocation_v2":
        return {key: _number(row.get(key)) for key in _ECONOMIC_KEYS}
    notional = _number(row.get("notional_usd"))
    if notional is None or notional <= 0:
        return {key: None for key in _ECONOMIC_KEYS}

    def usd_from_bps(key: str) -> float | None:
        value = _number(row.get(key))
        return None if value is None else value * notional / 10_000.0

    return {
        "gross_pnl_usd": usd_from_bps("gross_reconciled_bps"),
        "fees_usd": usd_from_bps("fees_bps"),
        "spread_cost_usd": usd_from_bps("spread_cost_bps"),
        "slippage_cost_usd": usd_from_bps("slippage_bps"),
        "latency_cost_usd": usd_from_bps("latency_cost_bps"),
        "net_pnl_usd": _number(row.get("net_usd")),
    }


def _trade_times(family: str, row: Mapping[str, Any]) -> tuple[float | None, float | None, float | None]:
    if family == "copy_vault":
        return (
            _timestamp_ms(row, "signal_ts_ms"),
            _timestamp_ms(row, "entry_ts_ms"),
            _timestamp_ms(row, "exit_ts_ms"),
        )
    if family == "lead_lag":
        return (
            _timestamp_ms(row, "signal_ts_ns"),
            _timestamp_ms(row, "entry_ts_ns"),
            _timestamp_ms(row, "exit_ts_ns"),
        )
    return (
        _timestamp_ms(row, "ts_detect"),
        _timestamp_ms(row, "ts_in"),
        _timestamp_ms(row, "ts_out"),
    )


def _freshness(family: str, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    if family == "copy_vault":
        fields = ("reference_lag_ms", "entry_target_lag_ms", "exit_target_lag_ms", "observed_latency_ms")
    elif family == "lead_lag":
        fields = ("reference_age_ms", "entry_latency_ms", "exit_observation_lag_ms")
    else:
        fields = ("age_s", "depth_freshness_ms")
    return {field: _distribution(row.get(field) for row in rows) for field in fields}


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(row["trade_id"]) for row in rows]
    economics = {
        key: _rounded(sum(float(row[key]) for row in rows)) for key in _ECONOMIC_KEYS
    }
    wins = [float(row["net_pnl_usd"]) for row in rows if float(row["net_pnl_usd"]) > 0]
    losses = [-float(row["net_pnl_usd"]) for row in rows if float(row["net_pnl_usd"]) < 0]
    return {
        **economics,
        "sample_count": len(rows),
        "trade_ids_count": len(set(ids)),
        "duplicate_trade_ids": len(ids) - len(set(ids)),
        "trade_ids_sha256": _hash_ids(ids),
        "hit_rate": _rounded(len(wins) / len(rows)) if rows else None,
        "profit_factor": _rounded(sum(wins) / sum(losses)) if losses else None,
        "liquidatable_net": bool(rows),
    }


def _concentration(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = str(row.get(key) or "UNKNOWN")
        groups[value].append(row)
    ranked = sorted(
        (
            {
                "value": value,
                "trade_count": len(group),
                "share": _rounded(len(group) / len(rows)) if rows else 0.0,
                "net_pnl_usd": _rounded(sum(float(item["net_pnl_usd"]) for item in group)),
            }
            for value, group in groups.items()
        ),
        key=lambda item: (-int(item["trade_count"]), str(item["value"])),
    )
    return {"unique": len(ranked), "top": ranked[:10]}


def _compare_metric(
    issues: list[str],
    *,
    label: str,
    expected: object,
    actual: object,
    tolerance: float = 1e-4,
) -> None:
    expected_number = _number(expected)
    actual_number = _number(actual)
    if expected_number is None or actual_number is None:
        issues.append(f"{label}_UNMEASURED")
    elif not math.isclose(expected_number, actual_number, abs_tol=tolerance):
        issues.append(
            f"{label}_MISMATCH:published={expected_number:.8f};raw={actual_number:.8f}"
        )


def _parse_instant(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _control_receipt(issues: Iterable[str], evidence: Mapping[str, Any]) -> dict[str, Any]:
    unique = list(dict.fromkeys(str(issue) for issue in issues if str(issue)))
    return {
        "ready": not unique,
        "issue_count": len(unique),
        "issues": unique[:_MAX_CONTROL_ISSUES],
        "issues_truncated": len(unique) > _MAX_CONTROL_ISSUES,
        "evidence": dict(evidence),
    }


def _assumption_control_inputs(
    contract: object,
    binding: Mapping[str, Any],
    *,
    audit_at: datetime,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    issues = {
        "stale_assumptions": [],
        "dependency_mismatch": [],
        "source_freshness": [],
    }
    evidence: dict[str, Any] = {
        "audit_at": audit_at.isoformat().replace("+00:00", "Z"),
        "required_count": 0,
        "assumption_count": 0,
        "external_source_count": 0,
        "internal_source_count": 0,
        "configured_source_count": 0,
        "formula_count": 0,
    }
    if not isinstance(contract, Mapping):
        issues["dependency_mismatch"].append("ECONOMIC_CONTRACT_MISSING")
        issues["source_freshness"].append("ASSUMPTION_SNAPSHOT_MISSING")
        return issues, evidence

    for reason in binding.get("issues") or []:
        issues["dependency_mismatch"].append(f"ECONOMIC_BINDING:{reason}")

    snapshot = contract.get("assumption_snapshot")
    assumptions = snapshot.get("assumptions") if isinstance(snapshot, Mapping) else None
    formulas = contract.get("formula_manifest")
    required_raw = contract.get("required_assumption_ids")
    required = (
        [str(item) for item in required_raw]
        if isinstance(required_raw, list) and all(isinstance(item, str) for item in required_raw)
        else []
    )
    evidence["required_count"] = len(required)
    if not isinstance(assumptions, list):
        issues["dependency_mismatch"].append("ASSUMPTION_SNAPSHOT_INVALID")
        issues["source_freshness"].append("ASSUMPTION_SNAPSHOT_INVALID")
        assumptions = []
    if not isinstance(formulas, list):
        issues["dependency_mismatch"].append("FORMULA_MANIFEST_INVALID")
        formulas = []
    evidence["assumption_count"] = len(assumptions)
    evidence["formula_count"] = len(formulas)

    by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_ids: list[str] = []
    for raw_assumption in assumptions:
        if not isinstance(raw_assumption, Mapping):
            issues["dependency_mismatch"].append("ASSUMPTION_ENTRY_INVALID")
            continue
        assumption_id = str(raw_assumption.get("assumption_id") or "").strip()
        if not assumption_id:
            issues["dependency_mismatch"].append("ASSUMPTION_ID_MISSING")
            continue
        if assumption_id in by_id:
            duplicate_ids.append(assumption_id)
        by_id[assumption_id] = raw_assumption
    if duplicate_ids:
        issues["dependency_mismatch"].append(
            f"DUPLICATE_ASSUMPTION_IDS:{','.join(sorted(set(duplicate_ids)))}"
        )
    missing_required = sorted(set(required) - set(by_id))
    if missing_required:
        issues["dependency_mismatch"].append(
            f"REQUIRED_ASSUMPTIONS_MISSING:{','.join(missing_required)}"
        )

    hexadecimal = set("0123456789abcdef")
    for assumption_id in required:
        assumption = by_id.get(assumption_id)
        if assumption is None:
            continue
        source_ref = str(assumption.get("source_ref") or "").strip()
        source_hash = str(assumption.get("source_hash") or "").strip().lower()
        if not source_ref:
            issues["source_freshness"].append(f"SOURCE_REF_MISSING:{assumption_id}")
        if len(source_hash) != 64 or any(char not in hexadecimal for char in source_hash):
            issues["source_freshness"].append(f"SOURCE_HASH_INVALID:{assumption_id}")

        observed_at = _parse_instant(assumption.get("observed_at"))
        valid_until = _parse_instant(assumption.get("valid_until"))
        revalidate_after = _parse_instant(assumption.get("revalidate_after"))
        raw_temporal = {
            "observed_at": assumption.get("observed_at"),
            "valid_until": assumption.get("valid_until"),
            "revalidate_after": assumption.get("revalidate_after"),
        }
        for field, parsed in (
            ("observed_at", observed_at),
            ("valid_until", valid_until),
            ("revalidate_after", revalidate_after),
        ):
            if raw_temporal[field] not in (None, "") and parsed is None:
                issues["source_freshness"].append(
                    f"SOURCE_TIMESTAMP_INVALID:{assumption_id}:{field}"
                )

        if source_ref.startswith(("https://", "http://")):
            evidence["external_source_count"] += 1
            if observed_at is None:
                issues["source_freshness"].append(
                    f"EXTERNAL_SOURCE_OBSERVED_AT_MISSING:{assumption_id}"
                )
            elif observed_at > audit_at:
                issues["source_freshness"].append(
                    f"EXTERNAL_SOURCE_OBSERVED_IN_FUTURE:{assumption_id}"
                )
            if valid_until is None and revalidate_after is None:
                issues["source_freshness"].append(
                    f"EXTERNAL_SOURCE_REVALIDATION_MISSING:{assumption_id}"
                )
        elif source_ref.startswith("env:"):
            evidence["configured_source_count"] += 1
            if not str(assumption.get("effective_from") or "").strip():
                issues["source_freshness"].append(
                    f"CONFIGURED_SOURCE_EFFECTIVE_FROM_MISSING:{assumption_id}"
                )
        elif source_ref.startswith(("project:", "formula:")):
            evidence["internal_source_count"] += 1
        elif source_ref:
            issues["source_freshness"].append(
                f"SOURCE_KIND_UNCLASSIFIED:{assumption_id}"
            )

        for field, deadline in (
            ("valid_until", valid_until),
            ("revalidate_after", revalidate_after),
        ):
            if deadline is not None and audit_at > deadline:
                reason = f"ASSUMPTION_STALE:{assumption_id}:{field}"
                issues["stale_assumptions"].append(reason)
                issues["source_freshness"].append(reason)

    assumption_ids = set(by_id)
    formula_outputs: set[str] = set()
    for raw_formula in formulas:
        if not isinstance(raw_formula, Mapping):
            issues["dependency_mismatch"].append("FORMULA_ENTRY_INVALID")
            continue
        formula_id = str(raw_formula.get("formula_id") or "").strip()
        output = str(raw_formula.get("output_assumption_id") or "").strip()
        parents_raw = raw_formula.get("parent_ids")
        parents = (
            [str(item) for item in parents_raw]
            if isinstance(parents_raw, list) and all(isinstance(item, str) for item in parents_raw)
            else []
        )
        if not formula_id or not output or not parents:
            issues["dependency_mismatch"].append(
                f"FORMULA_DEPENDENCY_INVALID:{formula_id or 'UNKNOWN'}"
            )
            continue
        if output in formula_outputs:
            issues["dependency_mismatch"].append(f"FORMULA_OUTPUT_DUPLICATE:{output}")
        formula_outputs.add(output)
        missing_nodes = sorted(({output, *parents}) - assumption_ids)
        if missing_nodes:
            issues["dependency_mismatch"].append(
                f"FORMULA_NODES_MISSING:{formula_id}:{','.join(missing_nodes)}"
            )
    return issues, evidence


def _hardcode_control(scan: object) -> dict[str, Any]:
    issues: list[str] = []
    evidence: dict[str, Any] = {
        "proposal_count": None,
        "parse_error_count": None,
        "files_scanned": None,
        "receipt_sha256": None,
        "by_category": {},
    }
    if not isinstance(scan, Mapping):
        return _control_receipt(["HARDCODE_SCAN_MISSING"], evidence)
    summary = scan.get("summary")
    if scan.get("schema_version") != HARDCODE_SCAN_SCHEMA:
        issues.append("HARDCODE_SCAN_SCHEMA_INVALID")
    if scan.get("disposition") != PROPOSAL_DISPOSITION or scan.get("auto_rewrite") is not False:
        issues.append("HARDCODE_SCAN_DISPOSITION_INVALID")
    if not isinstance(summary, Mapping):
        issues.append("HARDCODE_SCAN_SUMMARY_INVALID")
        summary = {}
    parse_error_count = _number(summary.get("parse_error_count"))
    if parse_error_count is None or parse_error_count != 0:
        issues.append("HARDCODE_SCAN_PARSE_ERRORS")
    findings = scan.get("findings")
    if not isinstance(findings, list):
        issues.append("HARDCODE_SCAN_FINDINGS_INVALID")
        findings = []
    elif any(
        not isinstance(row, Mapping) or row.get("disposition") != PROPOSAL_DISPOSITION
        for row in findings
    ):
        issues.append("HARDCODE_FINDING_UNCLASSIFIED")
    file_hashes = scan.get("file_hashes")
    if not isinstance(file_hashes, Mapping) or any(value is None for value in file_hashes.values()):
        issues.append("HARDCODE_SCAN_FILE_HASH_MISSING")
    receipt_hash = str(scan.get("receipt_sha256") or "")
    body = {key: value for key, value in scan.items() if key != "receipt_sha256"}
    expected_hash = hashlib.sha256(repr(body).encode()).hexdigest()
    if receipt_hash != expected_hash:
        issues.append("HARDCODE_SCAN_RECEIPT_HASH_MISMATCH")
    evidence.update(
        {
            "proposal_count": summary.get("proposal_count"),
            "parse_error_count": summary.get("parse_error_count"),
            "files_scanned": summary.get("files_scanned"),
            "receipt_sha256": receipt_hash or None,
            "by_category": dict(summary.get("by_category") or {}),
        }
    )
    return _control_receipt(issues, evidence)


def _trade_cost_controls(
    family: str,
    rows: list[Mapping[str, Any]],
    *,
    reality_model_version: str,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    issues = {
        "reconciliation_identities": [],
        "missing_costs": [],
        "duplicate_charging": [],
        "unsupported_zeros": [],
        "dependency_mismatch": [],
    }
    evidence = {
        "liquidatable_rows_checked": 0,
        "cost_receipts_checked": 0,
        "expected_components": list(_COMPONENT_TO_COST_KEY),
    }
    for index, row in enumerate(rows):
        if not _is_liquidatable(row):
            continue
        trade_id = str(row.get("trade_id") or row.get("episode_id") or index)
        evidence["liquidatable_rows_checked"] += 1
        economics = _trade_economics(family, row)
        if any(value is None for value in economics.values()):
            issues["missing_costs"].append(f"TRADE_ECONOMICS_UNMEASURED:{trade_id}")
            continue
        gross = float(economics["gross_pnl_usd"])
        net = float(economics["net_pnl_usd"])
        direct_costs = sum(float(economics[key]) for key in _COST_KEYS)
        if not math.isclose(gross - direct_costs, net, abs_tol=1e-4):
            issues["reconciliation_identities"].append(
                f"TRADE_RECONCILIATION_FAILED:{trade_id}"
            )

        receipts = row.get("cost_component_receipts")
        if not isinstance(receipts, Mapping):
            issues["missing_costs"].append(f"COST_RECEIPTS_MISSING:{trade_id}")
            continue
        missing = sorted(set(_COMPONENT_TO_COST_KEY) - set(receipts))
        extras = sorted(set(receipts) - set(_COMPONENT_TO_COST_KEY))
        if missing:
            issues["missing_costs"].append(
                f"COST_COMPONENTS_MISSING:{trade_id}:{','.join(missing)}"
            )
        if extras:
            issues["duplicate_charging"].append(
                f"UNEXPECTED_COST_COMPONENTS:{trade_id}:{','.join(extras)}"
            )

        receipt_amounts: list[float] = []
        receipt_components: list[str] = []
        for component, cost_key in _COMPONENT_TO_COST_KEY.items():
            receipt = receipts.get(component)
            if not isinstance(receipt, Mapping):
                continue
            evidence["cost_receipts_checked"] += 1
            declared_component = str(receipt.get("component") or "")
            receipt_components.append(declared_component)
            if declared_component != component:
                issues["duplicate_charging"].append(
                    f"COST_COMPONENT_IDENTITY_MISMATCH:{trade_id}:{component}"
                )
            amount = _number(receipt.get("amount_usd"))
            expected_amount = float(economics[cost_key])
            if amount is None:
                issues["missing_costs"].append(
                    f"COST_RECEIPT_AMOUNT_UNMEASURED:{trade_id}:{component}"
                )
                continue
            receipt_amounts.append(amount)
            if not math.isclose(amount, expected_amount, abs_tol=1e-7):
                issues["duplicate_charging"].append(
                    f"COST_RECEIPT_AMOUNT_MISMATCH:{trade_id}:{component}"
                )
            zero_reason = receipt.get("zero_reason")
            if amount == 0.0:
                if zero_reason not in _ALLOWED_ZERO_REASONS:
                    issues["unsupported_zeros"].append(
                        f"ZERO_REASON_MISSING_OR_INVALID:{trade_id}:{component}"
                    )
                elif zero_reason == ZeroCostReason.MISSING_UNMEASURABLE.value:
                    issues["unsupported_zeros"].append(
                        f"ZERO_COST_UNMEASURABLE:{trade_id}:{component}"
                    )
            elif zero_reason is not None:
                issues["unsupported_zeros"].append(
                    f"ZERO_REASON_ON_NONZERO_COST:{trade_id}:{component}"
                )
            if receipt.get("certification_eligible") is not True:
                issues["unsupported_zeros"].append(
                    f"COST_RECEIPT_NOT_CERTIFIABLE:{trade_id}:{component}"
                )
            if (
                not str(receipt.get("formula_id") or "").strip()
                or receipt.get("reality_model_version") != reality_model_version
                or not isinstance(receipt.get("provenance_ids"), list)
                or not receipt.get("provenance_ids")
            ):
                issues["dependency_mismatch"].append(
                    f"COST_RECEIPT_BINDING_INVALID:{trade_id}:{component}"
                )
        if len(receipt_components) != len(set(receipt_components)):
            issues["duplicate_charging"].append(
                f"DUPLICATE_COST_COMPONENT_ID:{trade_id}"
            )
        if len(receipt_amounts) == len(_COMPONENT_TO_COST_KEY) and not math.isclose(
            gross - sum(receipt_amounts), net, abs_tol=1e-4
        ):
            issues["duplicate_charging"].append(
                f"COST_RECEIPT_DEDUCTION_COUNT_INVALID:{trade_id}"
            )
        if row.get("economic_reconciled") is False:
            issues["reconciliation_identities"].append(
                f"PRODUCER_RECONCILIATION_FALSE:{trade_id}"
            )
    return issues, evidence


def _independent_economic_audit(
    family: str,
    campaign: Mapping[str, Any],
    raw_rows: list[Mapping[str, Any]],
    economic_binding: Mapping[str, Any],
    *,
    hardcode_scan: object,
    audit_at: datetime,
) -> dict[str, Any]:
    controls: dict[str, dict[str, Any]] = {}
    contract = campaign.get("economic_contract")
    reality_model_version = (
        str(contract.get("reality_model_version") or "")
        if isinstance(contract, Mapping)
        else ""
    )
    cost_issues, cost_evidence = _trade_cost_controls(
        family,
        raw_rows,
        reality_model_version=reality_model_version,
    )
    assumption_issues, assumption_evidence = _assumption_control_inputs(
        contract,
        economic_binding,
        audit_at=audit_at,
    )
    for name in ("reconciliation_identities", "missing_costs", "duplicate_charging", "unsupported_zeros"):
        controls[name] = _control_receipt(cost_issues[name], cost_evidence)
    controls["stale_assumptions"] = _control_receipt(
        assumption_issues["stale_assumptions"], assumption_evidence
    )
    controls["dependency_mismatch"] = _control_receipt(
        [
            *assumption_issues["dependency_mismatch"],
            *cost_issues["dependency_mismatch"],
        ],
        {**assumption_evidence, **cost_evidence},
    )
    controls["source_freshness"] = _control_receipt(
        assumption_issues["source_freshness"], assumption_evidence
    )
    controls["hidden_hardcodes"] = _hardcode_control(hardcode_scan)
    ordered = {name: controls[name] for name in _CONTROL_NAMES}
    return {
        "schema_version": INDEPENDENT_AUDIT_SCHEMA,
        "family": family,
        "ready": all(control["ready"] for control in ordered.values()),
        "controls": ordered,
    }


def audit_family(
    campaign: Mapping[str, Any],
    raw: Mapping[str, Any],
    *,
    target_net_usd: float = TARGET_NET_USD,
    hardcode_scan: Mapping[str, Any] | None = None,
    audit_as_of_ms: int | None = None,
) -> dict[str, Any]:
    """Recompute and classify one family without changing its strategy."""

    audit_ms = int(audit_as_of_ms if audit_as_of_ms is not None else time.time() * 1000)
    audit_at = datetime.fromtimestamp(audit_ms / 1000.0, tz=UTC)
    family = canonical_family(campaign.get("family"))
    issues: list[str] = []
    warnings: list[str] = []
    if family not in CANONICAL_FAMILIES:
        issues.append("UNKNOWN_OR_INACTIVE_FAMILY")
    if campaign.get("paper_read_only") is not True or campaign.get("real_execution") is not False:
        issues.append("PAPER_READ_ONLY_GUARD_FAILED")
    if raw.get("paper_read_only") is False or raw.get("real_execution") is True:
        issues.append("RAW_REAL_EXECUTION_GUARD_FAILED")

    economic_binding = audit_economic_contract_receipt(
        campaign.get("economic_contract"),
        expected_family=family,
        require_certifiable_mode=True,
    )
    issues.extend(
        f"ECONOMIC_BINDING_INVALID:{reason}"
        for reason in economic_binding.get("issues") or []
    )
    bound_snapshot_hash = economic_binding.get("assumption_snapshot_hash")
    if campaign.get("assumption_snapshot_hash") != bound_snapshot_hash:
        issues.append("CAMPAIGN_ASSUMPTION_SNAPSHOT_MISMATCH")

    raw_rows = _raw_trades(family, raw)
    liquidatable_rows = [row for row in raw_rows if _is_liquidatable(row)]
    if not raw_rows:
        issues.append("RAW_TRADES_MISSING")
    if not liquidatable_rows:
        issues.append("LIQUIDATABLE_TRADES_MISSING")

    audited_rows: list[dict[str, Any]] = []
    all_ids: list[str] = []
    for index, row in enumerate(liquidatable_rows):
        trade_id = str(row.get("trade_id") or row.get("episode_id") or "").strip()
        if not trade_id:
            issues.append(f"TRADE_ID_MISSING:{index}")
            continue
        all_ids.append(trade_id)
        if row.get("assumption_snapshot_hash") != bound_snapshot_hash:
            issues.append(f"TRADE_ASSUMPTION_SNAPSHOT_MISMATCH:{trade_id}")
        economics = _trade_economics(family, row)
        if any(value is None for value in economics.values()):
            issues.append(f"TRADE_ECONOMICS_UNMEASURED:{trade_id}")
            continue
        if any(float(economics[key]) < 0 for key in _COST_KEYS):
            issues.append(f"TRADE_NEGATIVE_COST:{trade_id}")
        reconciled = math.isclose(
            float(economics["gross_pnl_usd"])
            - sum(float(economics[key]) for key in _COST_KEYS),
            float(economics["net_pnl_usd"]),
            abs_tol=1e-4,
        )
        if not reconciled:
            issues.append(f"TRADE_ECONOMIC_RECONCILIATION_FAILED:{trade_id}")
        signal_ms, entry_ms, exit_ms = _trade_times(family, row)
        if entry_ms is None or exit_ms is None or entry_ms > exit_ms:
            issues.append(f"TRADE_LIFECYCLE_INVALID:{trade_id}")
        if family == "lead_lag" and (row.get("opened") is not True or row.get("closed") is not True):
            issues.append(f"TRADE_NOT_OPENED_AND_CLOSED:{trade_id}")
        if family == "cross_venue_dislocation_v2" and row.get("two_leg") is not True:
            issues.append(f"CROSS_TRADE_TWO_LEG_PROOF_MISSING:{trade_id}")
        segment = str(row.get("walk_forward_segment") or "unknown").lower()
        if segment not in _SEGMENTS:
            issues.append(f"TRADE_SEGMENT_MISSING:{trade_id}")
        audited_rows.append(
            {
                **row,
                "trade_id": trade_id,
                "walk_forward_segment": segment,
                "signal_ts_ms": signal_ms,
                "entry_ts_ms_audit": entry_ms,
                "exit_ts_ms_audit": exit_ms,
                **{key: float(value) for key, value in economics.items()},
            }
        )

    duplicates = [trade_id for trade_id, count in Counter(all_ids).items() if count > 1]
    if duplicates:
        issues.append(f"DUPLICATE_RAW_TRADE_IDS:{','.join(sorted(duplicates))}")

    aggregate = _aggregate(audited_rows) if audited_rows else None
    if aggregate is not None:
        for key in _ECONOMIC_KEYS:
            _compare_metric(
                issues,
                label=f"CAMPAIGN_{key.upper()}",
                expected=campaign.get(key),
                actual=aggregate.get(key),
            )
        _compare_metric(
            issues,
            label="CAMPAIGN_CLOSED_POSITIONS",
            expected=campaign.get("closed_positions"),
            actual=aggregate.get("sample_count"),
            tolerance=0.0,
        )
        if str(campaign.get("trade_ids_sha256") or "") != aggregate["trade_ids_sha256"]:
            issues.append("CAMPAIGN_TRADE_HASH_MISMATCH")

    segment_rows = {
        name: [row for row in audited_rows if row["walk_forward_segment"] == name]
        for name in _SEGMENTS
    }
    segment_audits = {
        name: (_aggregate(rows) if rows else None) for name, rows in segment_rows.items()
    }
    segment_id_sets = {
        name: {row["trade_id"] for row in rows} for name, rows in segment_rows.items()
    }
    for left_index, left in enumerate(_SEGMENTS):
        for right in _SEGMENTS[left_index + 1 :]:
            overlap = segment_id_sets[left] & segment_id_sets[right]
            if overlap:
                issues.append(f"SEGMENT_TRADE_ID_OVERLAP:{left}:{right}")

    freeze = campaign.get("parameter_freeze")
    freeze_ms = _number(freeze.get("frozen_at_ms")) if isinstance(freeze, Mapping) else None
    forward_rows = segment_rows["forward"]
    if forward_rows and freeze_ms is None:
        issues.append("FORWARD_WITHOUT_PHYSICAL_FREEZE")
    for row in forward_rows:
        signal_ms = _number(row.get("signal_ts_ms"))
        if freeze_ms is None or signal_ms is None or signal_ms <= freeze_ms:
            issues.append(f"FORWARD_NOT_POST_FREEZE:{row['trade_id']}")

    for name in ("oos", "forward"):
        published = campaign.get(name)
        audited = segment_audits[name]
        published_count = (
            _number(published.get("sample_count")) if isinstance(published, Mapping) else None
        )
        if audited is None:
            if published_count not in (None, 0.0):
                issues.append(f"{name.upper()}_RAW_SEGMENT_MISSING")
            continue
        if not isinstance(published, Mapping):
            issues.append(f"{name.upper()}_PUBLISHED_SEGMENT_MISSING")
            continue
        for key in _ECONOMIC_KEYS:
            _compare_metric(
                issues,
                label=f"{name.upper()}_{key.upper()}",
                expected=published.get(key),
                actual=audited.get(key),
            )
        if name == "oos" and published.get("no_lookahead") is not True:
            issues.append("OOS_NO_LOOKAHEAD_PROOF_MISSING")
        if name == "forward" and published.get("post_freeze") is not True:
            issues.append("FORWARD_POST_FREEZE_FLAG_MISSING")

    recomputed_objective = evaluate_objective(campaign, target_net_usd=target_net_usd)
    if recomputed_objective["objective_status"] != campaign.get("objective_status"):
        issues.append("OBJECTIVE_STATUS_NOT_REPRODUCIBLE")
    if recomputed_objective["proof_net_pnl_usd"] != campaign.get("proof_net_pnl_usd"):
        issues.append("OBJECTIVE_PROOF_NET_NOT_REPRODUCIBLE")

    independent_audit = _independent_economic_audit(
        family,
        campaign,
        raw_rows,
        economic_binding,
        hardcode_scan=hardcode_scan,
        audit_at=audit_at,
    )
    for control_name, control in independent_audit["controls"].items():
        if control["ready"]:
            continue
        issues.extend(
            f"INDEPENDENT_{control_name.upper()}:{reason}"
            for reason in control["issues"]
        )

    forward_count = len(forward_rows)
    oos_count = len(segment_rows["oos"])
    if forward_count == 0:
        warnings.append("FORWARD_POST_FREEZE_SAMPLE_MISSING")
    if oos_count == 0:
        warnings.append("OOS_SAMPLE_MISSING")
    objective_status = str(recomputed_objective["objective_status"])
    if issues:
        classification = "INVALID"
    elif forward_count == 0 or oos_count == 0:
        classification = "INCOMPLETE"
    elif objective_status == "ATTEINT":
        classification = "VALID_POSITIVE"
    else:
        proof_net = _number(recomputed_objective.get("proof_net_pnl_usd"))
        classification = "VALID_NEGATIVE" if proof_net is not None and proof_net < 0 else "VALID_NON_TARGET"

    gross = float(aggregate["gross_pnl_usd"]) if aggregate else 0.0
    total_costs = (
        sum(float(aggregate[key]) for key in _COST_KEYS) if aggregate else 0.0
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "family": family,
        "classification": classification,
        "ledger_valid": not issues,
        "objective_status": objective_status,
        "target_net_usd": float(target_net_usd),
        "proof_net_pnl_usd": recomputed_objective.get("proof_net_pnl_usd"),
        "diagnostic_net_pnl_usd": aggregate.get("net_pnl_usd") if aggregate else None,
        "raw_trade_count": len(raw_rows),
        "liquidatable_trade_count": len(liquidatable_rows),
        "excluded_non_liquidatable_count": len(raw_rows) - len(liquidatable_rows),
        "aggregate_recomputed": aggregate,
        "segments_recomputed": segment_audits,
        "freeze_id": freeze.get("campaign_id") if isinstance(freeze, Mapping) else None,
        "freeze_at_ms": freeze_ms,
        "issues": list(dict.fromkeys(issues)),
        "warnings": list(dict.fromkeys(warnings)),
        "objective_reasons": recomputed_objective.get("objective_reasons"),
        "economic_binding": economic_binding,
        "independent_economic_audit": independent_audit,
        "economics": {
            "total_costs_usd": _rounded(total_costs),
            "cost_to_abs_gross_ratio": (
                _rounded(total_costs / abs(gross)) if abs(gross) > 1e-12 else None
            ),
        },
        "concentration": {
            "coin": _concentration(audited_rows, "coin"),
            "leader_or_vault": _concentration(audited_rows, "vault"),
        },
        "freshness": _freshness(family, raw_rows),
    }


def _global_independent_audit(
    families: list[Mapping[str, Any]],
    missing_families: list[str],
) -> dict[str, Any]:
    controls: dict[str, dict[str, Any]] = {}
    for name in _CONTROL_NAMES:
        family_controls: dict[str, Any] = {}
        issues: list[str] = []
        for family_row in families:
            family = str(family_row.get("family") or "UNKNOWN")
            independent = family_row.get("independent_economic_audit")
            control = (
                independent.get("controls", {}).get(name)
                if isinstance(independent, Mapping)
                else None
            )
            if not isinstance(control, Mapping):
                issues.append(f"{family}:CONTROL_MISSING")
                continue
            family_controls[family] = {
                "ready": control.get("ready") is True,
                "issues": list(control.get("issues") or []),
                "evidence": dict(control.get("evidence") or {}),
            }
            issues.extend(f"{family}:{reason}" for reason in control.get("issues") or [])
        if missing_families:
            issues.append(f"MISSING_FAMILIES:{','.join(sorted(missing_families))}")
        controls[name] = _control_receipt(
            issues,
            {
                "families": family_controls,
                "missing_families": sorted(missing_families),
            },
        )
    return {
        "schema_version": INDEPENDENT_AUDIT_SCHEMA,
        "ready": all(control["ready"] for control in controls.values()),
        "controls": controls,
    }


def audit_reports(
    root: str | Path,
    *,
    hardcode_scan: Mapping[str, Any] | None = None,
    audit_as_of_ms: int | None = None,
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    report_dir = project_root / REPORT_DIR
    generated_at_ms = int(
        audit_as_of_ms if audit_as_of_ms is not None else time.time() * 1000
    )
    hardcode_receipt = (
        dict(hardcode_scan)
        if isinstance(hardcode_scan, Mapping)
        else scan_economic_paths(project_root)
    )
    families: list[dict[str, Any]] = []
    missing: list[str] = []
    for family in CANONICAL_FAMILIES:
        campaign_path = report_dir / f"{family}.json"
        raw_path = report_dir / "raw" / f"{family}.json"
        if not campaign_path.is_file() or not raw_path.is_file():
            missing.append(family)
            continue
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        families.append(
            audit_family(
                campaign,
                raw,
                hardcode_scan=hardcode_receipt,
                audit_as_of_ms=generated_at_ms,
            )
        )
    independent_audit = _global_independent_audit(families, missing)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": generated_at_ms,
        "paper_read_only": True,
        "real_execution": False,
        "target_net_usd_per_family": TARGET_NET_USD,
        "families": families,
        "missing_families": missing,
        "all_ledgers_valid": (
            not missing
            and independent_audit["ready"]
            and all(row["ledger_valid"] for row in families)
        ),
        "all_objectives_met": (
            not missing
            and len(families) == len(CANONICAL_FAMILIES)
            and all(row["objective_status"] == "ATTEINT" for row in families)
        ),
        "pnl_aggregation_across_families_allowed": False,
        "independent_economic_audit": independent_audit,
        "economic_hardcode_scan": hardcode_receipt,
    }


def render_markdown(audit: Mapping[str, Any]) -> str:
    lines = [
        "# Audit de preuve economique HyperSmart",
        "",
        "Chaque famille est auditee separement. Aucun PnL inter-famille n'est additionne.",
        "Lecture seule et paper local; aucune execution reelle.",
        "",
    ]
    for row in audit.get("families") or []:
        aggregate = row.get("aggregate_recomputed") or {}
        costs = row.get("economics") or {}
        independent = row.get("independent_economic_audit") or {}
        controls = independent.get("controls") or {}
        lines.extend(
            [
                f"## {row.get('family')} - {row.get('classification')}",
                "",
                f"- Objectif +4 USD: **{row.get('objective_status')}**",
                f"- PnL net diagnostic recalcule: {row.get('diagnostic_net_pnl_usd')}",
                f"- PnL net de preuve OOS + forward: {row.get('proof_net_pnl_usd')}",
                f"- Trades bruts/liquidatables/exclus: {row.get('raw_trade_count')} / {row.get('liquidatable_trade_count')} / {row.get('excluded_non_liquidatable_count')}",
                f"- Brut/couts/net: {aggregate.get('gross_pnl_usd')} / {costs.get('total_costs_usd')} / {aggregate.get('net_pnl_usd')}",
                f"- Ratio couts / |brut|: {costs.get('cost_to_abs_gross_ratio')}",
                f"- Ledger valide: {row.get('ledger_valid')}",
                f"- Audit economique independant: {independent.get('ready')}",
                f"- Freeze: {row.get('freeze_id')}",
                f"- Problemes: {', '.join(row.get('issues') or []) or 'aucun'}",
                f"- Avertissements: {', '.join(row.get('warnings') or []) or 'aucun'}",
                f"- Raisons objectif: {', '.join(row.get('objective_reasons') or []) or 'aucune'}",
                "",
            ]
        )
        for control_name in _CONTROL_NAMES:
            control = controls.get(control_name) or {}
            lines.append(
                f"  - {control_name}: {control.get('ready')}"
                f" ({', '.join(control.get('issues') or []) or 'aucun probleme'})"
            )
        lines.append("")
    global_independent = audit.get("independent_economic_audit") or {}
    lines.extend(
        [
            "## Verdict global",
            "",
            f"- Ledgers tous valides: {audit.get('all_ledgers_valid')}",
            f"- Audit economique independant global: {global_independent.get('ready')}",
            f"- Trois objectifs atteints separement: {audit.get('all_objectives_met')}",
            "- Agregation des PnL entre familles: interdite",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_audit(root: str | Path, audit: Mapping[str, Any]) -> tuple[Path, Path]:
    project_root = Path(root).resolve()
    output_dir = project_root / REPORT_DIR
    json_path = output_dir / AUDIT_JSON
    markdown_path = output_dir / AUDIT_MARKDOWN
    _atomic_write(json_path, json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _atomic_write(markdown_path, render_markdown(audit))
    return json_path, markdown_path


__all__ = [
    "AUDIT_JSON",
    "AUDIT_MARKDOWN",
    "INDEPENDENT_AUDIT_SCHEMA",
    "SCHEMA_VERSION",
    "audit_family",
    "audit_reports",
    "render_markdown",
    "write_audit",
]
