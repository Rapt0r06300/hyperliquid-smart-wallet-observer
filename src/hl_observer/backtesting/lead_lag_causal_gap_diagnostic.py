"""Causal diagnosis for missing Lead-Lag execution books.

This module answers a deliberately narrower question than the strategy replay:
when a recorded Binance shock has no Hyperliquid book within the executable
latency bound, do the surrounding recorded books show an explicit collector
break (gap/reconnect), or a contiguous capture whose book cadence was simply
slower than the bound?

The diagnostic never changes strategy parameters, never promotes a trade, and
never turns missing data into a zero.  It is PAPER/READ-ONLY evidence only.
"""
from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_causal_gap_diagnostic.v1"
DIAGNOSTIC_SHOCK_THRESHOLD_BPS = 8.0
EXECUTABLE_BOOK_LIMIT_MS = 750


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _same_contiguous_connection(
    previous: Mapping[str, Any] | None,
    following: Mapping[str, Any] | None,
) -> bool:
    if previous is None or following is None:
        return False
    previous_connection = str(previous.get("connection_id") or "")
    following_connection = str(following.get("connection_id") or "")
    if not previous_connection or previous_connection != following_connection:
        return False
    if _integer(previous.get("gap_count")) != _integer(following.get("gap_count")):
        return False
    if _integer(previous.get("reconnect_count")) != _integer(following.get("reconnect_count")):
        return False
    previous_sequence = _integer(previous.get("sequence"), -1)
    following_sequence = _integer(following.get("sequence"), -1)
    return (
        previous_sequence >= 0
        and following_sequence >= 0
        and following_sequence == previous_sequence + 1
    )


def diagnose_causal_book_availability(
    shocks: Sequence[Mapping[str, Any]],
    books: Sequence[Mapping[str, Any]],
    *,
    max_book_delay_ms: int = EXECUTABLE_BOOK_LIMIT_MS,
) -> dict[str, Any]:
    """Classify book availability around shocks without changing economics.

    ``CONTIGUOUS_CAPTURE_NO_BOOK_WITHIN_LIMIT`` means the surrounding valid
    books are consecutive on the same recorded connection with unchanged gap
    and reconnect counters.  That is evidence against an explicit collector
    loss, but it is *not* proof that the market itself had no intermediate
    update; the result therefore stays diagnostic and fail-closed.
    """

    clean_books = sorted(
        [dict(row) for row in books if _integer(row.get("ts_ms")) > 0],
        key=lambda row: _integer(row.get("ts_ms")),
    )
    timestamps = [_integer(row.get("ts_ms")) for row in clean_books]
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    limit = max(0, int(max_book_delay_ms))

    for shock in shocks:
        trigger_ms = _integer(shock.get("trigger_ts_ms"))
        if trigger_ms <= 0:
            continue
        insertion = bisect.bisect_left(timestamps, trigger_ms)
        previous = clean_books[insertion - 1] if insertion > 0 else None
        following = clean_books[insertion] if insertion < len(clean_books) else None
        following_delay = (
            _integer(following.get("ts_ms")) - trigger_ms if following is not None else None
        )
        timely = following_delay is not None and 0 <= following_delay <= limit
        quality_ready = bool(following is not None and following.get("data_gate_ready") is True)
        explicit_gap = bool(
            following is not None
            and (
                _integer(following.get("gap_count")) > _integer((previous or {}).get("gap_count"))
                or _integer(following.get("reconnect_count"))
                > _integer((previous or {}).get("reconnect_count"))
                or (
                    previous is not None
                    and str(previous.get("connection_id") or "")
                    and str(following.get("connection_id") or "")
                    and str(previous.get("connection_id")) != str(following.get("connection_id"))
                )
            )
        )
        contiguous = _same_contiguous_connection(previous, following)

        if timely and quality_ready:
            classification = "EXECUTABLE_BOOK_WITHIN_LIMIT"
        elif timely:
            classification = "BOOK_WITHIN_LIMIT_QUALITY_REJECTED"
        elif explicit_gap:
            classification = "COLLECTOR_GAP_EVIDENCE"
        elif contiguous:
            classification = "CONTIGUOUS_CAPTURE_NO_BOOK_WITHIN_LIMIT"
        elif following is None:
            classification = "NO_FOLLOWING_BOOK_RECORDED"
        else:
            classification = "NO_BOOK_WITHIN_LIMIT_UNRESOLVED"

        counts[classification] = counts.get(classification, 0) + 1
        rows.append(
            {
                "trigger_ts_ms": trigger_ms,
                "lead_shock_bps": shock.get("lead_shock_bps"),
                "direction": shock.get("direction"),
                "classification": classification,
                "max_book_delay_ms": limit,
                "following_book_delay_ms": following_delay,
                "timely_book": timely,
                "following_book_quality_ready": quality_ready,
                "explicit_collector_gap_evidence": explicit_gap,
                "contiguous_capture_evidence": contiguous,
                "previous_book_ts_ms": (
                    _integer(previous.get("ts_ms")) if previous is not None else None
                ),
                "following_book_ts_ms": (
                    _integer(following.get("ts_ms")) if following is not None else None
                ),
                "previous_connection_id": (
                    previous.get("connection_id") if previous is not None else None
                ),
                "following_connection_id": (
                    following.get("connection_id") if following is not None else None
                ),
                "previous_sequence": (
                    previous.get("sequence") if previous is not None else None
                ),
                "following_sequence": (
                    following.get("sequence") if following is not None else None
                ),
                "paper_read_only": True,
                "real_execution": False,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "DIAGNOSE_COLLECTOR_GAP_VS_RECORDED_BOOK_CADENCE",
        "diagnostic_only": True,
        "strategy_parameters_changed": False,
        "diagnostic_shock_threshold_bps": DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
        "economic_shock_threshold_unchanged": True,
        "max_book_delay_ms": limit,
        "shock_count": len(rows),
        "classification_counts": counts,
        "events": rows,
        "interpretation_guard": (
            "CONTIGUOUS_CAPTURE_NO_BOOK_WITHIN_LIMIT is evidence against an explicit "
            "collector break, not proof that no market update existed."
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "EXECUTABLE_BOOK_LIMIT_MS",
    "SCHEMA_VERSION",
    "diagnose_causal_book_availability",
]
