"""Causal collection-vs-market diagnostics for Lead-Lag evidence.

This module does not select or tune an economic strategy. It only explains why
an already observed lead shock has (or has not) a recorded Hyperliquid book
within the predeclared execution-delay ceiling. The diagnostic threshold is
therefore deliberately separate from the immutable economic threshold used by
the Lead-Lag replay.

Only recorded PAPER/READ-ONLY evidence is consumed. Absence of a book is never
silently labelled as a market fact: without explicit collector-gap evidence the
verdict remains inconclusive.
"""
from __future__ import annotations

import bisect
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

DIAGNOSTIC_SHOCK_THRESHOLD_BPS = 8.0
ECONOMIC_SHOCK_THRESHOLD_BPS = 20.0
DEFAULT_MAX_BOOK_DELAY_MS = 750
_GAP_TOKENS = ("GAP", "RECONNECT", "SEQUENCE", "STALE", "DISCONTINU")


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _quality_reasons(row: Mapping[str, Any] | None) -> list[str]:
    if row is None:
        return []
    raw = row.get("quality_reasons")
    if isinstance(raw, str):
        return [item for item in raw.split("|") if item]
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return [str(item) for item in raw if str(item)]
    return []


def _explicit_gap_evidence(row: Mapping[str, Any] | None) -> list[str]:
    if row is None:
        return []
    evidence: list[str] = []
    gap_count = _positive_int(row.get("gap_count"))
    reconnect_count = _positive_int(row.get("reconnect_count"))
    if gap_count is not None:
        evidence.append(f"gap_count={gap_count}")
    if reconnect_count is not None:
        evidence.append(f"reconnect_count={reconnect_count}")
    for reason in _quality_reasons(row):
        upper = reason.upper()
        if any(token in upper for token in _GAP_TOKENS):
            evidence.append(f"quality_reason={reason}")
    return evidence


def _window_meta_for_timestamp(
    microstructure_meta: Mapping[str, Any], timestamp_ms: int
) -> Mapping[str, Any] | None:
    per_window = microstructure_meta.get("per_window")
    if not isinstance(per_window, Sequence) or isinstance(per_window, (str, bytes, bytearray)):
        return None
    for raw in per_window:
        if not isinstance(raw, Mapping):
            continue
        start_ms = _positive_int(raw.get("requested_start_ms"))
        end_ms = _positive_int(raw.get("requested_end_ms"))
        if start_ms is None or end_ms is None:
            continue
        if start_ms <= timestamp_ms <= end_ms:
            return raw
    return None


def diagnose_causal_book_availability(
    shocks: Sequence[Mapping[str, Any]],
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    microstructure_meta: Mapping[str, Any],
    *,
    coin: str = "ETH",
    max_book_delay_ms: int = DEFAULT_MAX_BOOK_DELAY_MS,
    diagnostic_threshold_bps: float = DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
) -> dict[str, Any]:
    """Classify book availability without inventing a cause for missing data."""

    selected_coin = str(coin).strip().upper()
    ceiling_ms = max(0, int(max_book_delay_ms))
    books = sorted(
        [dict(row) for row in l2_history.get(selected_coin, ()) if isinstance(row, Mapping)],
        key=lambda row: int(row.get("ts_ms") or 0),
    )
    timestamps = [int(row.get("ts_ms") or 0) for row in books]
    rows: list[dict[str, Any]] = []

    for raw_shock in shocks:
        trigger_ms = _positive_int(raw_shock.get("trigger_ts_ms"))
        if trigger_ms is None:
            continue
        index = bisect.bisect_left(timestamps, trigger_ms)
        previous = books[index - 1] if index > 0 else None
        following = books[index] if index < len(books) else None
        window_meta = _window_meta_for_timestamp(microstructure_meta, trigger_ms)
        window_stop = (
            str(window_meta.get("stopped_reason") or "UNKNOWN")
            if isinstance(window_meta, Mapping)
            else "NO_WINDOW_METADATA"
        )
        sources_read = (
            int(window_meta.get("sources_read") or 0)
            if isinstance(window_meta, Mapping)
            else 0
        )
        scan_complete = window_stop == "COMPLETED"
        gap_evidence = [
            *_explicit_gap_evidence(previous),
            *_explicit_gap_evidence(following),
        ]
        if sources_read <= 0:
            gap_evidence.append("no_recorded_source_overlaps_window")

        following_ts = _positive_int(following.get("ts_ms")) if following else None
        delay_ms = following_ts - trigger_ms if following_ts is not None else None
        quality_ready = following.get("data_gate_ready") is True if following else False

        if not scan_complete:
            classification = "SCAN_INCOMPLETE"
        elif sources_read <= 0:
            classification = "NO_RECORDED_SOURCE_FOR_WINDOW"
        elif following is None:
            classification = (
                "NO_BOOK_AFTER_SHOCK_WITH_GAP_EVIDENCE"
                if gap_evidence
                else "NO_BOOK_AFTER_SHOCK_NO_GAP_EVIDENCE"
            )
        elif delay_ms is not None and delay_ms <= ceiling_ms and quality_ready:
            classification = "EXECUTABLE_BOOK_WITHIN_DELAY"
        elif delay_ms is not None and delay_ms <= ceiling_ms:
            classification = "BOOK_WITHIN_DELAY_REJECTED_QUALITY"
        else:
            classification = (
                "RECORDED_BOOK_TOO_LATE_WITH_GAP_EVIDENCE"
                if gap_evidence
                else "RECORDED_BOOK_TOO_LATE_NO_GAP_EVIDENCE"
            )

        rows.append(
            {
                "trigger_ts_ms": trigger_ms,
                "lead_shock_bps": float(raw_shock.get("lead_shock_bps") or 0.0),
                "direction": int(raw_shock.get("direction") or 0),
                "classification": classification,
                "first_book_ts_ms": following_ts,
                "first_book_delay_ms": delay_ms,
                "max_book_delay_ms": ceiling_ms,
                "first_book_data_gate_ready": quality_ready,
                "first_book_quality_reasons": _quality_reasons(following),
                "previous_book_ts_ms": (
                    _positive_int(previous.get("ts_ms")) if previous else None
                ),
                "window_scan_complete": scan_complete,
                "window_stopped_reason": window_stop,
                "window_sources_read": sources_read,
                "explicit_collector_gap_evidence": sorted(set(gap_evidence)),
                "collector_gap_evidence_present": bool(gap_evidence),
            }
        )

    counts = Counter(row["classification"] for row in rows)
    blocked = [row for row in rows if row["classification"] != "EXECUTABLE_BOOK_WITHIN_DELAY"]
    if any(row["classification"] == "SCAN_INCOMPLETE" for row in rows):
        conclusion = "INCONCLUSIVE_SCAN_LIMIT"
    elif any(row["classification"] == "NO_RECORDED_SOURCE_FOR_WINDOW" for row in rows):
        conclusion = "COLLECTOR_COVERAGE_GAP_CONFIRMED"
    elif blocked and all(row["collector_gap_evidence_present"] for row in blocked):
        conclusion = "EXPLICIT_COLLECTOR_GAP_EVIDENCE_PRESENT"
    elif blocked:
        conclusion = "INSUFFICIENT_EVIDENCE_TO_DISTINGUISH_MARKET_FROM_COLLECTION"
    else:
        conclusion = "CAUSAL_BOOK_COVERAGE_OK"

    executable = counts.get("EXECUTABLE_BOOK_WITHIN_DELAY", 0)
    delays = [
        int(row["first_book_delay_ms"])
        for row in rows
        if row.get("first_book_delay_ms") is not None
    ]
    return {
        "schema_version": "hypersmart.lead_lag_collection_diagnostic.v1",
        "coin": selected_coin,
        "diagnostic_only": True,
        "diagnostic_shock_threshold_bps": float(diagnostic_threshold_bps),
        "economic_shock_threshold_bps_unchanged": ECONOMIC_SHOCK_THRESHOLD_BPS,
        "max_book_delay_ms": ceiling_ms,
        "shock_count": len(rows),
        "executable_book_count": executable,
        "classification_counts": dict(sorted(counts.items())),
        "first_book_delay_min_ms": min(delays) if delays else None,
        "first_book_delay_max_ms": max(delays) if delays else None,
        "conclusion": conclusion,
        "events": rows,
        "interpretation_rule": (
            "NEVER_LABEL_MARKET_ABSENCE_WITHOUT_EXPLICIT_EVIDENCE; "
            "MISSING_OR_LATE_BOOK_WITHOUT_GAP_EVIDENCE_REMAINS_INCONCLUSIVE"
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DEFAULT_MAX_BOOK_DELAY_MS",
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "ECONOMIC_SHOCK_THRESHOLD_BPS",
    "diagnose_causal_book_availability",
]
