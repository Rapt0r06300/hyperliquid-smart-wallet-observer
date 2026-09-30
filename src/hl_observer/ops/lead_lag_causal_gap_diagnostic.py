"""Operational/reporting facade for canonical Lead-Lag causal diagnostics v4.

The 8 bps threshold is diagnostic only. Every causal-book/gap verdict is owned
by ``hl_observer.backtesting.lead_lag_causal_diagnostics``; this module only
loads recorded data, adapts historical arguments and writes compact reports.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.lead_lag_causal_diagnostics import (
    DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    ECONOMIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)
from hl_observer.backtesting.lead_lag_queue_replay import detect_rolling_shocks
from hl_observer.backtesting.lead_lag_source_alignment import (
    load_aligned_binance_trade_tape,
    select_aligned_bbo_sources,
)
from hl_observer.datasets.source_discovery import (
    is_dataset_workspace,
    load_family_source_paths,
)
from hl_observer.simulation.lead_lag_l2_history import (
    load_market_microstructure_event_windows,
)

SCHEMA_VERSION = "hypersmart.lead_lag_causal_book_coverage.v4"
REPORT_FILENAME = "LEAD_LAG_CAUSAL_GAP_DIAGNOSTIC.json"
REPORT_MARKDOWN_FILENAME = "LEAD_LAG_CAUSAL_GAP_DIAGNOSTIC.md"


def _root_cause(payload: Mapping[str, Any]) -> str:
    counts = payload.get("classifications")
    if not isinstance(counts, Mapping):
        counts = {}
    total = int(payload.get("shock_count") or 0)
    executable = int(counts.get("EXECUTABLE_CAUSAL_BOOK", 0) or 0)
    gaps = int(counts.get("EXPLICIT_RECORDED_FEED_GAP", 0) or 0)
    quality = int(counts.get("BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY", 0) or 0)
    inconclusive = int(counts.get("INCONCLUSIVE_DIAGNOSTIC_SCAN", 0) or 0)
    unresolved = int(counts.get("CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF", 0) or 0) + int(
        counts.get("NO_LATER_BOOK_RECORDED_NO_GAP_PROOF", 0) or 0
    )
    if total <= 0:
        return "NO_DIAGNOSTIC_SHOCKS"
    if executable:
        return "EXECUTABLE_CAUSAL_BOOK_OBSERVED_FOR_AT_LEAST_ONE_EVENT"
    if gaps == total:
        return "COLLECTION_GAP_EXPLICITLY_PROVEN_FOR_ALL_EVENTS"
    if gaps:
        return "MIXED_COLLECTION_GAP_AND_OTHER_FAIL_CLOSED_EVIDENCE"
    if quality == total:
        return "BOOKS_TIMELY_BUT_QUALITY_GATE_REJECTED"
    if inconclusive:
        return "DIAGNOSTIC_SCAN_INCOMPLETE_FAIL_CLOSED"
    if unresolved:
        return "NO_EXECUTABLE_BOOK_OBSERVED_WITHOUT_COLLECTOR_GAP_PROOF"
    return "UNRESOLVED_FAIL_CLOSED"


def diagnose_causal_book_availability(
    event_ts_ms: Sequence[int],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    coin: str = "ETH",
    max_delay_ms: int = DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    microstructure_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapt timestamp-only callers to the canonical event classifier."""

    shocks = [
        {
            "trigger_ts_ms": int(value),
            "lead_shock_bps": None,
            "direction": None,
        }
        for value in sorted({int(value) for value in event_ts_ms if int(value) > 0})
    ]
    result = diagnose_causal_book_coverage(
        shocks,
        books_by_coin,
        dict(microstructure_meta or {}),
        coin=coin,
        max_book_delay_ms=max_delay_ms,
    )
    return {
        **result,
        "schema_version": SCHEMA_VERSION,
        "compatibility_api": "ops.lead_lag_causal_gap_diagnostic.v1->canonical.v4",
        "root_cause": _root_cause(result),
        "interpretation_guard": (
            "A missing explicit event-local collector gap never proves market absence; "
            "loader incompleteness remains a distinct fail-closed class."
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


def build_lead_lag_causal_gap_diagnostic(root: str | Path) -> dict[str, Any]:
    project_root = Path(root).resolve()
    candidates = (
        load_family_source_paths(project_root, "lead_lag")
        if is_dataset_workspace(project_root)
        else None
    )
    aligned_sources, alignment = select_aligned_bbo_sources(
        project_root,
        candidates=candidates,
    )
    tape, tape_meta = load_aligned_binance_trade_tape(project_root, aligned_sources)
    trades = (tape.get("ETH") or {}).get("TRADE") or ()
    diagnostic_shocks = detect_rolling_shocks(
        trades,
        threshold_bps=DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    )
    event_timestamps = [int(row["trigger_ts_ms"]) for row in diagnostic_shocks]
    books, public_trades, history_meta = load_market_microstructure_event_windows(
        project_root,
        event_timestamps,
    )
    availability = diagnose_causal_book_coverage(
        diagnostic_shocks,
        books,
        history_meta,
        max_book_delay_ms=DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    )
    availability = {
        **availability,
        "root_cause": _root_cause(availability),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "DATA_QUALITY_AND_CAUSAL_BOOK_AVAILABILITY_ONLY",
        "diagnostic_threshold_bps": DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
        "economic_threshold_bps": ECONOMIC_SHOCK_THRESHOLD_BPS,
        "threshold_separation_enforced": (
            DIAGNOSTIC_SHOCK_THRESHOLD_BPS < ECONOMIC_SHOCK_THRESHOLD_BPS
        ),
        "economic_parameters_modified": False,
        "diagnostic_shocks": diagnostic_shocks,
        "source_alignment": alignment,
        "aligned_lead_tape": tape_meta,
        "microstructure_history": history_meta,
        "public_trade_rows_loaded": sum(len(rows) for rows in public_trades.values()),
        "causal_book_availability": availability,
        "paper_read_only": True,
        "real_execution": False,
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    availability = payload.get("causal_book_availability")
    if not isinstance(availability, Mapping):
        availability = {}
    lines = [
        "# Lead-Lag causal gap diagnostic",
        "",
        "**DIAGNOSTIC ONLY — the economic threshold remains 20 bps.**",
        "",
        f"- canonical schema: `{SCHEMA_VERSION}`",
        f"- diagnostic shock threshold: `{payload.get('diagnostic_threshold_bps')} bps`",
        f"- economic shock threshold: `{payload.get('economic_threshold_bps')} bps`",
        f"- diagnostic events: `{availability.get('shock_count', 0)}`",
        f"- root cause: `{availability.get('root_cause', 'UNKNOWN')}`",
        "- paper/read-only: `true`",
        "",
        "Absolute cumulative gap/reconnect counters are never event-local proof. "
        "Incomplete loader scans are reported separately from recorded feed gaps.",
        "",
        "## Events",
        "",
    ]
    for row in availability.get("events", ()):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "- `{} ms` → `{}` | next delay=`{}` ms | gap_delta=`{}` | reconnect_delta=`{}`".format(
                row.get("trigger_ts_ms"),
                row.get("classification"),
                row.get("next_book_delay_ms"),
                row.get("gap_count_delta"),
                row.get("reconnect_count_delta"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_lead_lag_causal_gap_diagnostic(
    root: str | Path,
    *,
    output_dir: str | Path,
) -> tuple[Path, Path, dict[str, Any]]:
    payload = build_lead_lag_causal_gap_diagnostic(root)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / REPORT_FILENAME
    markdown_path = destination / REPORT_MARKDOWN_FILENAME
    temporary = json_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, json_path)
    markdown_path.write_text(_markdown(payload), encoding="utf-8", newline="\n")
    return json_path, markdown_path, payload


__all__ = [
    "DIAGNOSTIC_MAX_BOOK_DELAY_MS",
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "ECONOMIC_SHOCK_THRESHOLD_BPS",
    "SCHEMA_VERSION",
    "build_lead_lag_causal_gap_diagnostic",
    "diagnose_causal_book_availability",
    "write_lead_lag_causal_gap_diagnostic",
]
