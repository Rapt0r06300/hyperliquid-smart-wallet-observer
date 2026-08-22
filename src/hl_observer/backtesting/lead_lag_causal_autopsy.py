"""Causal data-quality autopsy for Lead-Lag shock execution evidence.

This module is diagnostic only: it never changes the economic Lead-Lag trigger.
It classifies whether a predeclared diagnostic shock has executable Hyperliquid
book evidence, rejected-quality evidence, an explicit collector gap, or merely
no recorded book within the requested causal delay.  PAPER/READ-ONLY only.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_causal_autopsy.v1"
DIAGNOSTIC_THRESHOLD_BPS = 8.0
DIAGNOSTIC_WINDOW_MS = 1_000
DIAGNOSTIC_COOLDOWN_MS = 5_000
MAX_EXECUTABLE_DELAY_MS = 750


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _detect_shocks(
    trades: Sequence[Sequence[float]],
    *,
    threshold_bps: float,
    window_ms: int,
    cooldown_ms: int,
) -> list[dict[str, Any]]:
    clean: list[tuple[int, float]] = []
    for row in trades:
        if len(row) < 2:
            continue
        timestamp_ns = _number(row[0])
        price = _number(row[1])
        if timestamp_ns is None or price is None or timestamp_ns <= 0 or price <= 0:
            continue
        clean.append((int(timestamp_ns), float(price)))
    clean.sort()
    window_ns = max(1, int(window_ms)) * 1_000_000
    left = 0
    last_trigger_ms = -10**18
    shocks: list[dict[str, Any]] = []
    for index, (timestamp_ns, price) in enumerate(clean):
        while left < index and timestamp_ns - clean[left][0] > window_ns:
            left += 1
        if left >= index:
            continue
        base_ts_ns, base_price = clean[left]
        shock_bps = (price - base_price) / base_price * 10_000.0
        trigger_ms = timestamp_ns // 1_000_000
        if abs(shock_bps) < float(threshold_bps):
            continue
        if trigger_ms - last_trigger_ms < max(0, int(cooldown_ms)):
            continue
        shocks.append(
            {
                "trigger_ts_ms": int(trigger_ms),
                "window_start_ts_ms": int(base_ts_ns // 1_000_000),
                "lead_shock_bps": float(shock_bps),
                "direction": 1 if shock_bps > 0 else -1,
            }
        )
        last_trigger_ms = trigger_ms
    return shocks


def _explicit_gap_near(
    books: Sequence[Mapping[str, Any]],
    *,
    trigger_ms: int,
    max_delay_ms: int,
) -> bool:
    start = int(trigger_ms) - max(1, int(max_delay_ms))
    end = int(trigger_ms) + max(1, int(max_delay_ms))
    for row in books:
        ts_ms = int(row.get("ts_ms") or 0)
        if ts_ms < start:
            continue
        if ts_ms > end:
            break
        if int(row.get("gap_count") or 0) > 0 or int(row.get("reconnect_count") or 0) > 0:
            return True
        reasons = row.get("quality_reasons")
        if isinstance(reasons, str):
            text = reasons.upper()
        elif isinstance(reasons, Sequence):
            text = "|".join(str(item) for item in reasons).upper()
        else:
            text = ""
        if "GAP" in text or "RECONNECT" in text or "DISCONNECT" in text:
            return True
    return False


def diagnose_causal_book_coverage(
    tape: Mapping[str, Mapping[str, list]],
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    coin: str = "ETH",
    threshold_bps: float = DIAGNOSTIC_THRESHOLD_BPS,
    window_ms: int = DIAGNOSTIC_WINDOW_MS,
    cooldown_ms: int = DIAGNOSTIC_COOLDOWN_MS,
    max_delay_ms: int = MAX_EXECUTABLE_DELAY_MS,
) -> dict[str, Any]:
    """Classify causal book availability around diagnostic shocks.

    ``threshold_bps`` is intentionally diagnostic and must not be reused as the
    economic strategy threshold.  Missing book evidence is never labelled a
    collector gap unless recorded gap/reconnect evidence exists nearby.
    """

    selected_coin = str(coin).upper()
    trades = list((tape.get(selected_coin) or {}).get("TRADE") or [])
    shocks = _detect_shocks(
        trades,
        threshold_bps=threshold_bps,
        window_ms=window_ms,
        cooldown_ms=cooldown_ms,
    )
    books = sorted(
        [dict(row) for row in l2_history.get(selected_coin, ())],
        key=lambda row: int(row.get("ts_ms") or 0),
    )
    timestamps = [int(row.get("ts_ms") or 0) for row in books]
    events: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for shock in shocks:
        trigger_ms = int(shock["trigger_ts_ms"])
        index = bisect.bisect_left(timestamps, trigger_ms)
        next_book = books[index] if index < len(books) else None
        delay_ms = None if next_book is None else int(next_book.get("ts_ms") or 0) - trigger_ms
        explicit_gap = _explicit_gap_near(
            books,
            trigger_ms=trigger_ms,
            max_delay_ms=max_delay_ms,
        )
        if next_book is not None and delay_ms is not None and 0 <= delay_ms <= int(max_delay_ms):
            if next_book.get("data_gate_ready") is True:
                classification = "EXECUTABLE_BOOK_WITHIN_LIMIT"
            else:
                classification = "BOOK_WITHIN_LIMIT_REJECTED_BY_DATA_GATE"
        elif explicit_gap:
            classification = "EXPLICIT_COLLECTOR_GAP_NEAR_SHOCK"
        else:
            classification = "NO_RECORDED_BOOK_WITHIN_LIMIT_NO_PROVEN_GAP"
        counts[classification] = counts.get(classification, 0) + 1
        events.append(
            {
                **shock,
                "next_book_ts_ms": (
                    int(next_book.get("ts_ms") or 0) if next_book is not None else None
                ),
                "next_book_delay_ms": delay_ms,
                "next_book_data_gate_ready": (
                    next_book.get("data_gate_ready") is True if next_book is not None else None
                ),
                "next_book_gap_count": (
                    int(next_book.get("gap_count") or 0) if next_book is not None else None
                ),
                "next_book_reconnect_count": (
                    int(next_book.get("reconnect_count") or 0) if next_book is not None else None
                ),
                "explicit_gap_evidence": explicit_gap,
                "classification": classification,
            }
        )

    delays = [
        int(row["next_book_delay_ms"])
        for row in events
        if row.get("next_book_delay_ms") is not None and int(row["next_book_delay_ms"]) >= 0
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "coin": selected_coin,
        "diagnostic_only": True,
        "economic_threshold_changed": False,
        "diagnostic_threshold_bps": float(threshold_bps),
        "diagnostic_window_ms": int(window_ms),
        "diagnostic_cooldown_ms": int(cooldown_ms),
        "max_executable_delay_ms": int(max_delay_ms),
        "shock_count": len(shocks),
        "classification_counts": counts,
        "events": events,
        "min_next_book_delay_ms": min(delays) if delays else None,
        "max_next_book_delay_ms": max(delays) if delays else None,
        "conclusion": (
            "EXECUTABLE_CAUSAL_BOOK_EXISTS"
            if counts.get("EXECUTABLE_BOOK_WITHIN_LIMIT", 0) > 0
            else (
                "COLLECTOR_GAP_PROVEN_FOR_AT_LEAST_ONE_SHOCK"
                if counts.get("EXPLICIT_COLLECTOR_GAP_NEAR_SHOCK", 0) > 0
                else "NO_EXECUTABLE_BOOK_AND_NO_COLLECTOR_GAP_PROVEN"
            )
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DIAGNOSTIC_THRESHOLD_BPS",
    "MAX_EXECUTABLE_DELAY_MS",
    "diagnose_causal_book_coverage",
]
