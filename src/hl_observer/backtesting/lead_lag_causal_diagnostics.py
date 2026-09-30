"""Fail-closed causal coverage diagnostics for Lead-Lag execution evidence."""
from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from typing import Any

DIAGNOSTIC_SHOCK_THRESHOLD_BPS = 8.0
ECONOMIC_SHOCK_THRESHOLD_BPS = 20.0
DIAGNOSTIC_MAX_BOOK_DELAY_MS = 750


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _window_for_timestamp(
    timestamp_ms: int,
    windows: Sequence[Mapping[str, Any]],
) -> tuple[int, Mapping[str, Any]] | None:
    for index, row in enumerate(windows):
        start_ms = _int(row.get("start_ms"), -1)
        end_ms = _int(row.get("end_ms"), -1)
        if start_ms <= timestamp_ms <= end_ms:
            return index, row
    return None


def _quality_gap_reasons(row: Mapping[str, Any] | None) -> list[str]:
    if row is None:
        return []
    reasons = row.get("quality_reasons")
    if not isinstance(reasons, Sequence) or isinstance(reasons, (str, bytes, bytearray)):
        return []
    evidence: list[str] = []
    for reason in reasons:
        text = str(reason).upper()
        if "GAP" in text or "RECONNECT" in text or "SEQUENCE" in text:
            evidence.append(f"BOOK_QUALITY_{text}")
    return evidence


def _explicit_gap_evidence(
    *,
    previous: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    window_meta: Mapping[str, Any] | None,
) -> tuple[list[str], dict[str, Any]]:
    """Return only event-local recorded feed/collector continuity evidence.

    ``gap_count`` and ``reconnect_count`` are cumulative counters in recorded
    books.  Their absolute value cannot prove that the gap happened around the
    current shock.  We therefore require a positive delta between the immediate
    book before the shock and the first book after it.  This prevents one old
    reconnect from contaminating every later diagnostic event.

    Window-level counters remain admissible only because they describe the
    independently loaded causal event window itself.  Loader timeout/line-budget
    evidence is intentionally handled elsewhere and is never promoted to a
    collector gap.
    """

    evidence: list[str] = []
    details: dict[str, Any] = {
        "gap_count_delta": None,
        "reconnect_count_delta": None,
        "connection_changed": False,
        "sequence_delta": None,
    }

    if window_meta is not None:
        for key in ("gap_count", "reconnect_count", "sequence_gaps", "dropped_rows"):
            value = _int(window_meta.get(key))
            if value > 0:
                evidence.append(f"WINDOW_{key.upper()}={value}")

    if previous is not None and candidate is not None:
        previous_gap = _int(previous.get("gap_count"))
        candidate_gap = _int(candidate.get("gap_count"))
        gap_delta = max(0, candidate_gap - previous_gap)
        details["gap_count_delta"] = gap_delta
        if gap_delta > 0:
            evidence.append(f"BOOK_GAP_COUNT_DELTA={gap_delta}")

        previous_reconnect = _int(previous.get("reconnect_count"))
        candidate_reconnect = _int(candidate.get("reconnect_count"))
        reconnect_delta = max(0, candidate_reconnect - previous_reconnect)
        details["reconnect_count_delta"] = reconnect_delta
        if reconnect_delta > 0:
            evidence.append(f"BOOK_RECONNECT_COUNT_DELTA={reconnect_delta}")

        previous_connection = str(previous.get("connection_id") or "")
        candidate_connection = str(candidate.get("connection_id") or "")
        connection_changed = bool(
            previous_connection
            and candidate_connection
            and previous_connection != candidate_connection
        )
        details["connection_changed"] = connection_changed
        if connection_changed:
            evidence.append("BOOK_CONNECTION_CHANGED")

        previous_sequence = _int(previous.get("sequence"), -1)
        candidate_sequence = _int(candidate.get("sequence"), -1)
        if previous_sequence >= 0 and candidate_sequence >= 0:
            sequence_delta = candidate_sequence - previous_sequence
            details["sequence_delta"] = sequence_delta
            if (
                not connection_changed
                and candidate_connection == previous_connection
                and sequence_delta > 1
            ):
                evidence.append(f"BOOK_SEQUENCE_JUMP={sequence_delta}")

    # Direct quality metadata can explicitly name a gap/reconnect around either
    # boundary book.  Unlike cumulative absolute counters, this is row-local.
    evidence.extend(_quality_gap_reasons(previous))
    evidence.extend(_quality_gap_reasons(candidate))
    return sorted(set(evidence)), details


def _loader_incomplete_evidence(window_meta: Mapping[str, Any] | None) -> list[str]:
    if window_meta is None:
        return []
    stopped = str(window_meta.get("stopped_reason") or "COMPLETED")
    return [] if stopped == "COMPLETED" else [f"WINDOW_SCAN_{stopped}"]


def _percentile(values: Sequence[int], fraction: float) -> float | None:
    ordered = sorted(int(value) for value in values if int(value) >= 0)
    if not ordered:
        return None
    if len(ordered) == 1:
        return float(ordered[0])
    position = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def diagnose_causal_book_coverage(
    shocks: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    microstructure_meta: Mapping[str, Any],
    *,
    coin: str = "ETH",
    max_book_delay_ms: int = DIAGNOSTIC_MAX_BOOK_DELAY_MS,
) -> dict[str, Any]:
    """Classify causal-book availability without inventing missing evidence.

    Loader incompleteness is distinct from a recorded feed gap. A clean later
    book is also distinct from having no later book at all. None of these
    diagnostic classes can select or promote an economic strategy.
    """
    selected_coin = str(coin).upper()
    books = sorted(
        [dict(row) for row in books_by_coin.get(selected_coin, ())],
        key=lambda row: _int(row.get("ts_ms")),
    )
    timestamps = [_int(row.get("ts_ms")) for row in books]
    windows = [
        row for row in microstructure_meta.get("windows", ()) if isinstance(row, Mapping)
    ]
    per_window = [
        row
        for row in microstructure_meta.get("per_window", ())
        if isinstance(row, Mapping)
    ]
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    timely_delays: list[int] = []
    first_book_delays: list[int] = []
    max_delay = max(0, int(max_book_delay_ms))

    for shock in shocks:
        trigger_ms = _int(shock.get("trigger_ts_ms"))
        index = bisect.bisect_left(timestamps, trigger_ms)
        previous = books[index - 1] if index > 0 else None
        candidate = books[index] if index < len(books) else None
        delay_ms = None if candidate is None else _int(candidate.get("ts_ms")) - trigger_ms
        timely = (
            candidate is not None
            and delay_ms is not None
            and 0 <= delay_ms <= max_delay
        )
        if delay_ms is not None and delay_ms >= 0:
            first_book_delays.append(int(delay_ms))

        matched_window = _window_for_timestamp(trigger_ms, windows)
        relevant_meta = None
        if matched_window is not None:
            window_index, _ = matched_window
            if window_index < len(per_window):
                relevant_meta = per_window[window_index]

        gap_evidence, gap_details = _explicit_gap_evidence(
            previous=previous,
            candidate=candidate,
            window_meta=relevant_meta,
        )
        loader_evidence = _loader_incomplete_evidence(relevant_meta)

        if timely and candidate.get("data_gate_ready") is True:
            classification = "EXECUTABLE_CAUSAL_BOOK"
            timely_delays.append(int(delay_ms))
        elif timely:
            classification = "BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY"
        elif gap_evidence:
            classification = "EXPLICIT_RECORDED_FEED_GAP"
        elif loader_evidence:
            classification = "INCONCLUSIVE_DIAGNOSTIC_SCAN"
        elif candidate is not None:
            classification = "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
        else:
            classification = "NO_LATER_BOOK_RECORDED_NO_GAP_PROOF"

        counts[classification] = counts.get(classification, 0) + 1
        rows.append(
            {
                "trigger_ts_ms": trigger_ms,
                "lead_shock_bps": shock.get("lead_shock_bps"),
                "direction": shock.get("direction"),
                "classification": classification,
                "previous_book_ts_ms": (
                    None if previous is None else _int(previous.get("ts_ms"))
                ),
                "next_book_ts_ms": (
                    None if candidate is None else _int(candidate.get("ts_ms"))
                ),
                "next_book_delay_ms": delay_ms,
                "book_quality_ready": (
                    None if candidate is None else candidate.get("data_gate_ready") is True
                ),
                "explicit_gap_evidence": gap_evidence,
                "loader_incomplete_evidence": loader_evidence,
                **gap_details,
            }
        )

    return {
        "schema_version": "hypersmart.lead_lag_causal_book_coverage.v4",
        "coin": selected_coin,
        "diagnostic_only": True,
        "diagnostic_shock_threshold_bps": DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
        "economic_shock_threshold_bps_unchanged": ECONOMIC_SHOCK_THRESHOLD_BPS,
        "max_book_delay_ms": max_delay,
        "shock_count": len(rows),
        "classifications": counts,
        "events": rows,
        "timely_quality_ready_count": counts.get("EXECUTABLE_CAUSAL_BOOK", 0),
        "median_timely_delay_ms": (
            sorted(timely_delays)[len(timely_delays) // 2] if timely_delays else None
        ),
        "first_book_delay_p50_ms": _percentile(first_book_delays, 0.50),
        "first_book_delay_p95_ms": _percentile(first_book_delays, 0.95),
        "gap_evidence_rule": (
            "EVENT_LOCAL_DELTAS_OR_ROW_LOCAL_QUALITY_OR_EVENT_WINDOW_COUNTERS; "
            "ABSOLUTE_CUMULATIVE_BOOK_COUNTERS_ARE_NOT_SUFFICIENT"
        ),
        "interpretation": (
            "DIAGNOSTIC_ONLY_NOT_ECONOMIC_SELECTION; loader incompleteness is not "
            "collector-gap evidence; absence without explicit recorded gap remains fail-closed"
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DIAGNOSTIC_MAX_BOOK_DELAY_MS",
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "ECONOMIC_SHOCK_THRESHOLD_BPS",
    "diagnose_causal_book_coverage",
]
