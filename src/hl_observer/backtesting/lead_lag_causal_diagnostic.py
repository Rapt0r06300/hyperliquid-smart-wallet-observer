"""Fail-closed causal availability diagnostic for Lead-Lag execution evidence.

This module answers one narrow research question without changing the economic
strategy: when a recorded lead shock occurs, was an executable Hyperliquid book
observable within the predeclared 750 ms budget, merely late, rejected by data
quality, or absent with explicit collection-gap evidence?

The diagnostic threshold may be lower than the frozen economic trigger because
it is used only to inspect source coverage. Its output MUST NOT create trades,
change economic parameters, or certify PnL.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_causal_availability.v1"
DIAGNOSTIC_SHOCK_THRESHOLD_BPS = 8.0
DEFAULT_MAX_BOOK_DELAY_MS = 750
DEFAULT_LOOKAHEAD_MS = 15_000


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _nonnegative_int(value: object) -> int:
    parsed = _finite(value)
    return max(0, int(parsed)) if parsed is not None else 0


def _book_rows(
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    coin: str,
) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in l2_history.get(str(coin).upper(), ())
        if _nonnegative_int(row.get("ts_ms")) > 0
    ]
    rows.sort(key=lambda row: int(row["ts_ms"]))
    return rows


def _explicit_gap_evidence(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> dict[str, Any]:
    rows = [row for row in (before, after) if isinstance(row, Mapping)]
    gap_count = max((_nonnegative_int(row.get("gap_count")) for row in rows), default=0)
    reconnect_count = max(
        (_nonnegative_int(row.get("reconnect_count")) for row in rows), default=0
    )
    reasons = sorted(
        {
            str(reason)
            for row in rows
            for reason in (
                row.get("quality_reasons")
                if isinstance(row.get("quality_reasons"), Sequence)
                and not isinstance(row.get("quality_reasons"), (str, bytes, bytearray))
                else ()
            )
            if str(reason)
        }
    )
    explicit = bool(gap_count > 0 or reconnect_count > 0 or any("GAP" in reason.upper() for reason in reasons))
    return {
        "explicit_gap_evidence": explicit,
        "nearby_gap_count": gap_count,
        "nearby_reconnect_count": reconnect_count,
        "nearby_quality_reasons": reasons[:20],
    }


def diagnose_causal_book_availability(
    shocks: Sequence[Mapping[str, Any]],
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    coin: str = "ETH",
    max_book_delay_ms: int = DEFAULT_MAX_BOOK_DELAY_MS,
    lookahead_ms: int = DEFAULT_LOOKAHEAD_MS,
    diagnostic_threshold_bps: float = DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
) -> dict[str, Any]:
    """Classify causal book availability for each already-recorded diagnostic shock.

    This function never searches for a profitable threshold. The caller supplies
    shocks independently; ``diagnostic_threshold_bps`` is provenance only. The
    economic replay remains responsible for its own frozen 20 bps trigger.
    """

    selected_coin = str(coin).upper()
    books = _book_rows(l2_history, coin=selected_coin)
    timestamps = [int(row["ts_ms"]) for row in books]
    max_delay = max(0, int(max_book_delay_ms))
    lookahead = max(max_delay, int(lookahead_ms))

    events: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for raw in sorted(shocks, key=lambda row: int(row.get("trigger_ts_ms") or 0)):
        trigger = _nonnegative_int(raw.get("trigger_ts_ms"))
        if trigger <= 0:
            continue
        index = bisect.bisect_left(timestamps, trigger)
        before = books[index - 1] if index > 0 else None
        after = books[index] if index < len(books) else None
        delay_ms = None if after is None else int(after["ts_ms"]) - trigger
        within_lookahead = delay_ms is not None and 0 <= delay_ms <= lookahead
        quality_ready = bool(after is not None and after.get("data_gate_ready") is True)
        gap = _explicit_gap_evidence(before, after)

        if delay_ms is not None and 0 <= delay_ms <= max_delay and quality_ready:
            classification = "EXECUTABLE_CAUSAL_BOOK"
        elif delay_ms is not None and 0 <= delay_ms <= max_delay:
            classification = "BOOK_WITHIN_BUDGET_QUALITY_REJECTED"
        elif within_lookahead:
            classification = "LATE_CAUSAL_BOOK"
        elif gap["explicit_gap_evidence"]:
            classification = "NO_BOOK_WITH_EXPLICIT_COLLECTION_GAP_EVIDENCE"
        else:
            classification = "NO_RECORDED_CAUSAL_BOOK_GAP_UNPROVEN"

        counts[classification] = counts.get(classification, 0) + 1
        events.append(
            {
                "trigger_ts_ms": trigger,
                "lead_shock_bps": _finite(raw.get("lead_shock_bps")),
                "direction": int(_finite(raw.get("direction")) or 0),
                "classification": classification,
                "first_causal_book_ts_ms": int(after["ts_ms"]) if after is not None else None,
                "first_causal_book_delay_ms": delay_ms,
                "first_causal_book_quality_ready": quality_ready if after is not None else None,
                "first_causal_book_connection_id": after.get("connection_id") if after is not None else None,
                "previous_book_ts_ms": int(before["ts_ms"]) if before is not None else None,
                **gap,
            }
        )

    delays = [
        int(event["first_causal_book_delay_ms"])
        for event in events
        if event.get("first_causal_book_delay_ms") is not None
        and int(event["first_causal_book_delay_ms"]) >= 0
    ]
    delays.sort()
    executable = counts.get("EXECUTABLE_CAUSAL_BOOK", 0)
    explicit_gap_events = counts.get("NO_BOOK_WITH_EXPLICIT_COLLECTION_GAP_EVIDENCE", 0)
    late = counts.get("LATE_CAUSAL_BOOK", 0)
    unproven = counts.get("NO_RECORDED_CAUSAL_BOOK_GAP_UNPROVEN", 0)
    quality_rejected = counts.get("BOOK_WITHIN_BUDGET_QUALITY_REJECTED", 0)

    if executable:
        conclusion = "EXECUTABLE_BOOKS_EXIST_IN_DIAGNOSTIC_SAMPLE"
    elif explicit_gap_events:
        conclusion = "COLLECTION_GAPS_EXPLAIN_AT_LEAST_PART_OF_MISSING_EXECUTION_EVIDENCE"
    elif quality_rejected:
        conclusion = "BOOKS_EXIST_BUT_DATA_QUALITY_GATE_BLOCKS_EXECUTION"
    elif late:
        conclusion = "RECORDED_BOOKS_ARE_CAUSAL_BUT_TOO_LATE_FOR_750MS_BUDGET"
    elif unproven:
        conclusion = "NO_EXECUTABLE_BOOK_AND_NO_EXPLICIT_GAP_PROOF"
    else:
        conclusion = "NO_DIAGNOSTIC_SHOCKS"

    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "SOURCE_COVERAGE_DIAGNOSTIC_ONLY_NOT_ECONOMIC_TUNING",
        "coin": selected_coin,
        "diagnostic_shock_threshold_bps": float(diagnostic_threshold_bps),
        "economic_threshold_unchanged": True,
        "max_executable_book_delay_ms": max_delay,
        "diagnostic_lookahead_ms": lookahead,
        "shock_count": len(events),
        "book_count": len(books),
        "classifications": dict(sorted(counts.items())),
        "executable_book_events": executable,
        "explicit_collection_gap_events": explicit_gap_events,
        "quality_rejected_events": quality_rejected,
        "late_book_events": late,
        "gap_unproven_events": unproven,
        "min_first_book_delay_ms": min(delays) if delays else None,
        "max_first_book_delay_ms": max(delays) if delays else None,
        "events": events,
        "conclusion": conclusion,
        "paper_read_only": True,
        "real_execution": False,
        "creates_trades": False,
        "changes_strategy_parameters": False,
    }


__all__ = [
    "DEFAULT_LOOKAHEAD_MS",
    "DEFAULT_MAX_BOOK_DELAY_MS",
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "SCHEMA_VERSION",
    "diagnose_causal_book_availability",
]
