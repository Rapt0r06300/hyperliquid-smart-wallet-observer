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


def _window_for_timestamp(timestamp_ms: int, windows: Sequence[Mapping[str, Any]]) -> tuple[int, Mapping[str, Any]] | None:
    for index, row in enumerate(windows):
        start_ms = _int(row.get("start_ms"), -1)
        end_ms = _int(row.get("end_ms"), -1)
        if start_ms <= timestamp_ms <= end_ms:
            return index, row
    return None


def _explicit_gap_evidence(*, candidate: Mapping[str, Any] | None, window_meta: Mapping[str, Any] | None, nearby_books: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return only recorded feed/collector continuity evidence.

    A diagnostic loader timeout or line-budget stop is not a market-data gap:
    it means the local autopsy was incomplete. Keeping those concepts separate
    prevents a bounded research scan from manufacturing a collector root cause.
    """
    evidence: list[str] = []
    if window_meta is not None:
        for key in ("gap_count", "reconnect_count", "sequence_gaps", "dropped_rows"):
            value = _int(window_meta.get(key))
            if value > 0:
                evidence.append(f"WINDOW_{key.upper()}={value}")
    relevant_rows = list(nearby_books)
    if candidate is not None and candidate not in relevant_rows:
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


def diagnose_causal_book_coverage(shocks: Sequence[Mapping[str, Any]], books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]], microstructure_meta: Mapping[str, Any], *, coin: str = "ETH", max_book_delay_ms: int = DIAGNOSTIC_MAX_BOOK_DELAY_MS) -> dict[str, Any]:
    """Classify causal-book availability without inventing missing evidence.

    Loader incompleteness is distinct from a recorded feed gap. A clean later
    book is also distinct from having no later book at all. None of these
    diagnostic classes can select or promote an economic strategy.
    """
    selected_coin = str(coin).upper()
    books = sorted([dict(row) for row in books_by_coin.get(selected_coin, ())], key=lambda row: _int(row.get("ts_ms")))
    timestamps = [_int(row.get("ts_ms")) for row in books]
    windows = [row for row in microstructure_meta.get("windows", ()) if isinstance(row, Mapping)]
    per_window = [row for row in microstructure_meta.get("per_window", ()) if isinstance(row, Mapping)]
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    timely_delays: list[int] = []
    first_book_delays: list[int] = []
    max_delay = max(0, int(max_book_delay_ms))
    for shock in shocks:
        trigger_ms = _int(shock.get("trigger_ts_ms"))
        index = bisect.bisect_left(timestamps, trigger_ms)
        candidate = books[index] if index < len(books) else None
        delay_ms = None if candidate is None else _int(candidate.get("ts_ms")) - trigger_ms
        timely = candidate is not None and delay_ms is not None and 0 <= delay_ms <= max_delay
        if delay_ms is not None and delay_ms >= 0:
            first_book_delays.append(int(delay_ms))
        matched_window = _window_for_timestamp(trigger_ms, windows)
        relevant_meta = None
        if matched_window is not None:
            window_index, _ = matched_window
            if window_index < len(per_window):
                relevant_meta = per_window[window_index]
        nearby_books = books[max(0, index - 1): min(len(books), index + 8)]
        gap_evidence = _explicit_gap_evidence(candidate=candidate, window_meta=relevant_meta, nearby_books=nearby_books)
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
        rows.append({"trigger_ts_ms": trigger_ms, "lead_shock_bps": shock.get("lead_shock_bps"), "direction": shock.get("direction"), "classification": classification, "next_book_ts_ms": None if candidate is None else _int(candidate.get("ts_ms")), "next_book_delay_ms": delay_ms, "book_quality_ready": None if candidate is None else candidate.get("data_gate_ready") is True, "explicit_gap_evidence": gap_evidence, "loader_incomplete_evidence": loader_evidence})
    return {"schema_version": "hypersmart.lead_lag_causal_book_coverage.v3", "coin": selected_coin, "diagnostic_only": True, "diagnostic_shock_threshold_bps": DIAGNOSTIC_SHOCK_THRESHOLD_BPS, "economic_shock_threshold_bps_unchanged": ECONOMIC_SHOCK_THRESHOLD_BPS, "max_book_delay_ms": max_delay, "shock_count": len(rows), "classifications": counts, "events": rows, "timely_quality_ready_count": counts.get("EXECUTABLE_CAUSAL_BOOK", 0), "median_timely_delay_ms": sorted(timely_delays)[len(timely_delays)//2] if timely_delays else None, "first_book_delay_p50_ms": _percentile(first_book_delays, 0.50), "first_book_delay_p95_ms": _percentile(first_book_delays, 0.95), "interpretation": "DIAGNOSTIC_ONLY_NOT_ECONOMIC_SELECTION; loader incompleteness is not collector-gap evidence; absence without explicit recorded gap remains fail-closed", "paper_read_only": True, "real_execution": False}


__all__ = ["DIAGNOSTIC_MAX_BOOK_DELAY_MS", "DIAGNOSTIC_SHOCK_THRESHOLD_BPS", "ECONOMIC_SHOCK_THRESHOLD_BPS", "diagnose_causal_book_coverage"]
