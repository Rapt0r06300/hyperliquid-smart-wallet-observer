"""Read-only UI and launcher observability contracts for Copy-Vault."""

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


def economic_writer_uniqueness_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require exactly one active economic writer and no duplicate writer ids."""
    if not rows:
        return _base("MORE_DATA", reason="empty_economic_writer_inventory")
    ids = [str(row.get("writer_id") or "").strip() if isinstance(row, Mapping) else "" for row in rows]
    active = [row for row in rows if isinstance(row, Mapping) and row.get("active") is True]
    valid = all(ids) and len(ids) == len(set(ids)) and len(active) == 1
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="SINGLE_ECONOMIC_WRITER" if valid else "DUPLICATE_OR_MISSING_ECONOMIC_WRITER",
        writer_count=len(ids),
        active_count=len(active),
    )


def launcher_vs_strategy_state_receipt(launcher: Mapping[str, Any], strategy: Mapping[str, Any]) -> dict[str, Any]:
    """Keep launcher process state distinct from strategy state."""
    if not isinstance(launcher, Mapping) or not isinstance(strategy, Mapping):
        return _base("UNMEASURABLE", reason="invalid_launcher_strategy_state")
    valid = bool(str(launcher.get("state") or "").strip()) and bool(str(strategy.get("state") or "").strip())
    return _base(
        "PROVEN" if valid else "UNMEASURABLE",
        verdict="LAUNCHER_AND_STRATEGY_STATE_DISTINCT" if valid else "LAUNCHER_OR_STRATEGY_STATE_MISSING",
        launcher_state=launcher.get("state"),
        strategy_state=strategy.get("state"),
    )


def final_cmd_powershell_override_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require CMD and PowerShell inputs to agree before showing an effective value."""
    if not rows:
        return _base("MORE_DATA", reason="empty_launcher_override_inventory")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if (
            not isinstance(row, Mapping)
            or "cmd_value" not in row
            or "powershell_value" not in row
            or row.get("cmd_value") != row.get("powershell_value")
            or row.get("effective_source") not in {"CMD", "POWERSHELL"}
            or row.get("conflict") is True
        ):
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="CMD_POWERSHELL_OVERRIDE_RECONCILED", invalid_rows=invalid)


def refusal_module_link_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require each refusal to name its actual module and stable refusal code."""
    if not rows:
        return _base("MORE_DATA", reason="empty_refusal_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("refusal_code") or "").strip()
        or not str(row.get("module") or "").strip()
        or not str(row.get("reason") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="REFUSAL_LINKED_TO_MODULE", invalid_rows=invalid)


def wallet_stream_delay_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Expose per-wallet stream delay without hiding stale or missing observations."""
    if not rows:
        return _base("MORE_DATA", reason="empty_wallet_stream_delay")
    invalid: list[int] = []
    delays: list[float] = []
    for index, row in enumerate(rows):
        observed = _number(row.get("observed_ts_ms")) if isinstance(row, Mapping) else None
        source = _number(row.get("source_ts_ms")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not str(row.get("wallet") or "").strip() or observed is None or source is None or observed < source:
            invalid.append(index)
        else:
            delays.append(observed - source)
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="WALLET_STREAM_DELAY_EXPOSED", invalid_rows=invalid, max_delay_ms=max(delays) if delays else None)


def local_pnl_vs_certified_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Separate local paper PnL origin from any future certified evidence."""
    if not rows:
        return _base("MORE_DATA", reason="empty_pnl_origin_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("origin") not in {"LOCAL_PAPER", "CERTIFIED"}
        or not str(row.get("source_ref") or "").strip()
        or (row.get("origin") == "LOCAL_PAPER" and row.get("certified") is not False)
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="LOCAL_PNL_CERTIFICATION_SEPARATED", invalid_rows=invalid)


def ui_disabled_family_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Prevent UI surfaces from activating an economic family outside Copy-Vault."""
    if not rows:
        return _base("MORE_DATA", reason="empty_ui_family_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("family") != "Copy-Vault"
        or row.get("scope_state") != "ACTIVE"
        or row.get("execution_enabled") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="UI_SCOPE_EXCLUDES_DISABLED_FAMILIES", invalid_rows=invalid)


def safe_corpus_status_receipt(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Show SAFE coverage and gaps explicitly rather than presenting a false green."""
    if not isinstance(summary, Mapping):
        return _base("UNMEASURABLE", reason="invalid_safe_corpus_summary")
    safe_count = summary.get("safe_shards")
    gap_count = summary.get("gap_count")
    if not isinstance(safe_count, int) or safe_count < 0 or not isinstance(gap_count, int) or gap_count < 0:
        return _base("UNMEASURABLE", reason="safe_corpus_counts_missing")
    return _base(
        "PROVEN",
        verdict="SAFE_CORPUS_STATUS_WITH_EXPLICIT_GAPS",
        safe_shards=safe_count,
        gap_count=gap_count,
        coverage_state="COMPLETE" if gap_count == 0 else "GAPPED",
    )


def http_refresh_without_pnl_recompute_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require status refreshes to use cached PnL state instead of recalculating it."""
    if not rows:
        return _base("MORE_DATA", reason="empty_http_refresh_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("refresh_kind") != "HTTP_STATUS"
        or row.get("pnl_recomputed") is not False
        or not str(row.get("pnl_cache_hash") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="HTTP_REFRESH_REUSES_PNL_CACHE", invalid_rows=invalid)


def health_vs_profit_alert_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep infrastructure health alerts separate from economic profit alerts."""
    if not rows:
        return _base("MORE_DATA", reason="empty_alert_inventory")
    allowed = {"HEALTH", "PROFIT"}
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("alert_type") not in allowed
        or not str(row.get("code") or "").strip()
        or row.get("healthy") is None
        or (row.get("alert_type") == "HEALTH" and "profit" in str(row.get("code")).lower())
        or (row.get("alert_type") == "PROFIT" and "health" in str(row.get("code")).lower())
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="HEALTH_PROFIT_ALERTS_SEPARATED", invalid_rows=invalid)


__all__ = [
    "economic_writer_uniqueness_receipt",
    "launcher_vs_strategy_state_receipt",
    "final_cmd_powershell_override_receipt",
    "refusal_module_link_receipt",
    "wallet_stream_delay_receipt",
    "local_pnl_vs_certified_receipt",
    "ui_disabled_family_receipt",
    "safe_corpus_status_receipt",
    "http_refresh_without_pnl_recompute_receipt",
    "health_vs_profit_alert_receipt",
]
