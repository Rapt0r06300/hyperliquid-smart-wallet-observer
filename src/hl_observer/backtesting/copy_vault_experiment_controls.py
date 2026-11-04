"""Fail-closed experiment controls for Copy-Vault launcher decisions."""

from __future__ import annotations

import math
import re
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


def net_improvement_freeze_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Freeze only a measured net improvement with explicit baseline identity."""
    if not rows:
        return _base("MORE_DATA", reason="empty_improvement_freeze")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("freeze_id") or "").strip()
        or not str(row.get("baseline_sha256") or "").strip()
        or not str(row.get("challenger_sha256") or "").strip()
        or row.get("frozen") is not True
        or _number(row.get("net_improvement_bps")) is None
        or _number(row.get("net_improvement_bps")) <= 0
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="NET_IMPROVEMENT_FROZEN_WITH_BASELINE", invalid_rows=invalid)


def target_not_terminal_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep the daily target as a goal, never as a terminal success condition."""
    if not rows:
        return _base("MORE_DATA", reason="empty_target_policy")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("target_usd") != 5.0
        or row.get("target_is_terminal") is not False
        or row.get("continuation_policy") != "CONTINUE_RESEARCH"
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="TARGET_NOT_TERMINAL", invalid_rows=invalid)


def hotpath_untouched_experiment_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require experiments to leave the live decision hot path unchanged."""
    if not rows:
        return _base("MORE_DATA", reason="empty_hotpath_isolation")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("hot_path_mutated") is not False
        or row.get("lane") != "RESEARCH_ONLY"
        or not str(row.get("live_hot_path_sha256") or "").strip()
        or not str(row.get("experiment_sha256") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="EXPERIMENT_HOTPATH_UNTOUCHED", invalid_rows=invalid)


def launcher_cost_ablation_link_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require every launcher suggestion to cite a cost ablation."""
    if not rows:
        return _base("MORE_DATA", reason="empty_launcher_suggestion_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("suggestion_id") or "").strip()
        or not str(row.get("cost_ablation_ref") or "").strip()
        or row.get("costs_included") is not True
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="LAUNCHER_SUGGESTION_COST_ABLATED", invalid_rows=invalid)


def selective_vs_all_copy_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare selective and all-copy variants on a shared, identified sample."""
    if not rows:
        return _base("MORE_DATA", reason="empty_copy_variant_comparison")
    variants = {row.get("variant") for row in rows if isinstance(row, Mapping)}
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("variant") not in {"SELECTIVE", "ALL"}
        or not str(row.get("corpus_manifest_sha256") or "").strip()
        or row.get("costs_included") is not True
        or _number(row.get("net_result")) is None
    ]
    if variants != {"SELECTIVE", "ALL"}:
        invalid.append("variant_coverage")
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="SELECTIVE_VS_ALL_COPY_COMPARED", invalid_rows=invalid)


def disjoint_oos_after_tuning_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require OOS to start after tuning and cite a separate manifest."""
    if not rows:
        return _base("MORE_DATA", reason="empty_oos_split_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or _number(row.get("tuning_end_ms")) is None
        or _number(row.get("oos_start_ms")) is None
        or _number(row.get("oos_start_ms")) <= _number(row.get("tuning_end_ms"))
        or row.get("overlap") is not False
        or not str(row.get("oos_manifest_sha256") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="TUNING_OOS_DISJOINT", invalid_rows=invalid)


def launcher_version_freeze_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Bind launcher version, code, config and freeze identity."""
    if not rows:
        return _base("MORE_DATA", reason="empty_launcher_freeze_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("launcher_version") or "").strip()
        or not str(row.get("code_sha256") or "").strip()
        or not str(row.get("config_sha256") or "").strip()
        or not str(row.get("freeze_id") or "").strip()
        or row.get("frozen") is not True
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="LAUNCHER_VERSION_FREEZE_BOUND", invalid_rows=invalid)


def delayed_data_falsification_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Falsify an apparent advantage when source delay exceeds the admissible bound."""
    if not rows:
        return _base("MORE_DATA", reason="empty_delay_falsification")
    invalid: list[int] = []
    falsified = 0
    for index, row in enumerate(rows):
        delay = _number(row.get("delay_ms")) if isinstance(row, Mapping) else None
        bound = _number(row.get("max_delay_ms")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or delay is None or bound is None or delay < 0 or bound <= 0:
            invalid.append(index)
        elif delay > bound and row.get("advantage_valid") is not False:
            invalid.append(index)
        elif delay > bound:
            falsified += 1
    return _base("PROVEN" if falsified and not invalid else "REJECTED", verdict="DELAYED_DATA_ADVANTAGE_FALSIFIED", falsified_count=falsified, invalid_rows=invalid)


def neutral_benchmark_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a net strategy result to beat a matched neutral benchmark."""
    if not rows:
        return _base("MORE_DATA", reason="empty_neutral_benchmark")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        strategy = _number(row.get("strategy_net")) if isinstance(row, Mapping) else None
        neutral = _number(row.get("neutral_net")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or strategy is None or neutral is None or row.get("same_corpus") is not True or row.get("same_costs") is not True or strategy <= neutral:
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="STRATEGY_BEATS_MATCHED_NEUTRAL", invalid_rows=invalid)


def no_revenue_promise_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Prevent UI or launcher copy from promising income or guaranteed returns."""
    if not rows:
        return _base("MORE_DATA", reason="empty_revenue_copy_inventory")
    forbidden = re.compile(r"(?:guarantee|guaranteed|profit|income|revenue|risk[- ]?free|certain)", re.I)
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("claim_status") != "NO_PROMISE"
        or forbidden.search(str(row.get("text") or ""))
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="NO_REVENUE_PROMISE", invalid_rows=invalid)


__all__ = [
    "net_improvement_freeze_receipt",
    "target_not_terminal_receipt",
    "hotpath_untouched_experiment_receipt",
    "launcher_cost_ablation_link_receipt",
    "selective_vs_all_copy_receipt",
    "disjoint_oos_after_tuning_receipt",
    "launcher_version_freeze_receipt",
    "delayed_data_falsification_receipt",
    "neutral_benchmark_receipt",
    "no_revenue_promise_receipt",
]
