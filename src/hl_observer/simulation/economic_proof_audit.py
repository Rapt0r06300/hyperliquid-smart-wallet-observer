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
from pathlib import Path
from typing import Any

from .economic_campaigns import REPORT_DIR
from .economic_objective import (
    CANONICAL_FAMILIES,
    TARGET_NET_USD,
    canonical_family,
    evaluate_objective,
)

SCHEMA_VERSION = "hypersmart.economic_proof_audit.v1"
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


def audit_family(
    campaign: Mapping[str, Any],
    raw: Mapping[str, Any],
    *,
    target_net_usd: float = TARGET_NET_USD,
) -> dict[str, Any]:
    """Recompute and classify one family without changing its strategy."""

    family = canonical_family(campaign.get("family"))
    issues: list[str] = []
    warnings: list[str] = []
    if family not in CANONICAL_FAMILIES:
        issues.append("UNKNOWN_OR_INACTIVE_FAMILY")
    if campaign.get("paper_read_only") is not True or campaign.get("real_execution") is not False:
        issues.append("PAPER_READ_ONLY_GUARD_FAILED")
    if raw.get("paper_read_only") is False or raw.get("real_execution") is True:
        issues.append("RAW_REAL_EXECUTION_GUARD_FAILED")

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


def audit_reports(root: str | Path) -> dict[str, Any]:
    project_root = Path(root).resolve()
    report_dir = project_root / REPORT_DIR
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
        families.append(audit_family(campaign, raw))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": int(time.time() * 1000),
        "paper_read_only": True,
        "real_execution": False,
        "target_net_usd_per_family": TARGET_NET_USD,
        "families": families,
        "missing_families": missing,
        "all_ledgers_valid": not missing and all(row["ledger_valid"] for row in families),
        "all_objectives_met": (
            not missing
            and len(families) == len(CANONICAL_FAMILIES)
            and all(row["objective_status"] == "ATTEINT" for row in families)
        ),
        "pnl_aggregation_across_families_allowed": False,
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
                f"- Freeze: {row.get('freeze_id')}",
                f"- Problemes: {', '.join(row.get('issues') or []) or 'aucun'}",
                f"- Avertissements: {', '.join(row.get('warnings') or []) or 'aucun'}",
                f"- Raisons objectif: {', '.join(row.get('objective_reasons') or []) or 'aucune'}",
                "",
            ]
        )
    lines.extend(
        [
            "## Verdict global",
            "",
            f"- Ledgers tous valides: {audit.get('all_ledgers_valid')}",
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
    "SCHEMA_VERSION",
    "audit_family",
    "audit_reports",
    "render_markdown",
    "write_audit",
]
