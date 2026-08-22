"""Fail-closed causal coverage diagnostics for Lead-Lag execution evidence.

This module does not select or tune an economic strategy. It only answers a
narrow provenance question for predeclared shock timestamps: was a causal
Hyperliquid top-of-book observable quickly enough, and if not, does recorded
evidence contain an explicit collector/feed gap signal?

The diagnostic threshold may be lower than the frozen economic trigger solely
to autopsy already-observed events. Its output is never eligible economic PnL.
"""
from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from typing import Any

DIAGNOSTIC_SHOCK_THRESHOLD_BPS = 8.0
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


def _explicit_gap_evidence(
    *,
    trigger_ms: int,
    max_delay_ms: int,
    candidate: Mapping[str, Any] | None,
    window_meta: Mapping[str, Any] | None,
    nearby_books: Sequence[Mapping[str, Any]],
) -> list[str]:
    evidence: list[str] = []
    if window_meta is not None:
        stopped = str(window_meta.get("stopped_reason") or "COMPLETED")
        if stopped != "COMPLETED":
            evidence.append(f"WINDOW_SCAN_{stopped}")
        for key in ("gap_count", "reconnect_count", "sequence_gaps", "dropped_rows"):
            value = _int(window_meta.get(key))
            if value > 0:
                evidence.append(f"WINDOW_{key.upper()}={value}")

    # Recorded book rows carry collector health directly. A non-zero gap/reconnect
    # on the first causal row, or on another row inside the diagnostic horizon,
    # is explicit evidence that collection continuity was impaired. We do not
    # infer a gap merely because the next valid book is late.
    relevant_rows: list[Mapping[str, Any]] = []
    horizon_end = trigger_ms + max(0, int(max_delay_ms))
    for row in nearby_books:
        ts_ms = _int(row.get("ts_ms"))
        if trigger_ms <= ts_ms <= horizon_end:
            relevant_rows.append(row)
    if candidate is not None and candidate not in relevant_rows:
        candidate_ts = _int(candidate.get("ts_ms"))
        if candidate_ts >= trigger_ms:
            relevant_rows.append(candidate)

    for row in relevant_rows:
        for key in ("gap_count", "reconnect_count"):
            value = _int(row.get(key))
            if value > 0:
                evidence.append(f"BOOK_{key.upper()}={value}")
        reasons = row.get("quality_reasons")
        if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes, bytearray)):
            for reason in reasons:
                text = str(reason).upper()
                if "GAP" in text or "RECONNECT" in text or "SEQUENCE" in text:
                    evidence.append(f"BOOK_QUALITY_{text}")
    return sorted(set(evidence))


def diagnose_causal_book_coverage(
    shocks: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    microstructure_meta: Mapping[str, Any],
    *,
    coin: str = "ETH",
    max_book_delay_ms: int = DIAGNOSTIC_MAX_BOOK_DELAY_MS,
) -> dict[str, Any]:
    """Classify causal-book availability without inventing missing evidence.

    Classifications are intentionally conservative:
    - ``EXECUTABLE_CAUSAL_BOOK``: a recorded quality-ready book is observable
      within the allowed delay;
    - ``BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY``: a timely book exists but its
      recorded data gate rejects it;
    - ``EXPLICIT_RECORDED_FEED_GAP``: no timely book and recorded metadata or
      causal book rows carry an explicit gap/reconnect/partial-scan signal;
    - ``NO_CAUSAL_BOOK_WITHOUT_PROVEN_GAP``: no timely book, but the available
      metadata cannot prove that collection failed. This must not be rewritten
      as a collector bug or as proof that the market had no book.
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
        row for row in microstructure_meta.get("per_window", ()) if isinstance(row, Mapping)
    ]

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    delays: list[int] = []
    max_delay = max(0, int(max_book_delay_ms))

    for shock in shocks:
        trigger_ms = _int(shock.get("trigger_ts_ms"))
        index = bisect.bisect_left(timestamps, trigger_ms)
        candidate = books[index] if index < len(books) else None
        delay_ms = None if candidate is None else _int(candidate.get("ts_ms")) - trigger_ms
        timely = candidate is not None and delay_ms is not None and 0 <= delay_ms <= max_delay

        matched_window = _window_for_timestamp(trigger_ms, windows)
        relevant_meta: Mapping[str, Any] | None = None
        if matched_window is not None:
            window_index, _ = matched_window
            if window_index < len(per_window):
                relevant_meta = per_window[window_index]

        evidence = _explicit_gap_evidence(
            trigger_ms=trigger_ms,
            max_delay_ms=max_delay,
            candidate=candidate,
            window_meta=relevant_meta,
            nearby_books=books[max(0, index - 1) : min(len(books), index + 8)],
        )

        if timely and candidate.get("data_gate_ready") is True:
            classification = "EXECUTABLE_CAUSAL_BOOK"
            delays.append(int(delay_ms))
        elif timely:
            classification = "BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY"
            reasons = candidate.get("quality_reasons", ())
            if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes, bytearray)):
                evidence.extend(str(value) for value in reasons if value)
            evidence = sorted(set(evidence))
        elif evidence:
            classification = "EXPLICIT_RECORDED_FEED_GAP"
        else:
            classification = "NO_CAUSAL_BOOK_WITHOUT_PROVEN_GAP"

        counts[classification] = counts.get(classification, 0) + 1
        rows.append(
            {
                "trigger_ts_ms": trigger_ms,
                "lead_shock_bps": shock.get("lead_shock_bps"),
                "direction": shock.get("direction"),
                "classification": classification,
                "next_book_ts_ms": None if candidate is None else _int(candidate.get("ts_ms")),
                "next_book_delay_ms": delay_ms,
                "book_quality_ready": None if candidate is None else candidate.get("data_gate_ready") is True,
                "explicit_gap_evidence": evidence,
            }
        )

    ordered_delays = sorted(delays)
    return {
        "schema_version": "hypersmart.lead_lag_causal_book_coverage.v2",
        "coin": selected_coin,
        "max_book_delay_ms": max_delay,
        "shock_count": len(rows),
        "classifications": counts,
        "events": rows,
        "timely_quality_ready_count": counts.get("EXECUTABLE_CAUSAL_BOOK", 0),
        "median_timely_delay_ms": (
            ordered_delays[len(ordered_delays) // 2] if ordered_delays else None
        ),
        "interpretation": (
            "DIAGNOSTIC_ONLY_NOT_ECONOMIC_SELECTION; absence without explicit gap remains UNKNOWN_CAUSE"
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DIAGNOSTIC_MAX_BOOK_DELAY_MS",
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "diagnose_causal_book_coverage",
]
