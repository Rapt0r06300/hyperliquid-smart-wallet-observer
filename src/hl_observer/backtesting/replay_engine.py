"""Replay engine that applies deterministic timestamp ordering and delay."""

from __future__ import annotations

from typing import Any, Iterable

from .execution_delay_model import apply_execution_delay


def replay_events_with_delay(events: Iterable[dict[str, object]], *, delay_seconds: float) -> tuple[dict[str, object], ...]:
    replayed = []
    seen_event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("replay events must be mappings")
        delayed = apply_execution_delay(
            event.get("event_id"),  # type: ignore[arg-type]
            event.get("ts_ms"),  # type: ignore[arg-type]
            delay_seconds=delay_seconds,
        )
        if delayed.event_id in seen_event_ids:
            raise ValueError("replay event_id must be unique")
        seen_event_ids.add(delayed.event_id)
        row = dict(event)
        row["effective_ts_ms"] = delayed.effective_ts_ms
        row["delay_ms"] = delayed.delay_ms
        replayed.append(row)
    # A stable sort alone would preserve whichever input order a platform or
    # upstream merge happened to provide for equal timestamps.  Native event
    # identity is the canonical tie-break, so the same SAFE tape yields the
    # same replay sequence regardless of input permutation.
    return tuple(sorted(
        replayed,
        key=lambda row: (int(row["effective_ts_ms"]), str(row["event_id"]).strip()),
    ))


def replay_determinism_receipt(
    events: Iterable[dict[str, object]], *, delay_seconds: float,
) -> dict[str, Any]:
    """Prove deterministic replay without claiming cross-platform execution.

    The contract compares the canonical replay of the supplied SAFE rows with
    the canonical replay of the same rows in reverse input order.  It never
    fills missing rows or turns an invalid tape into a passing result.
    """
    rows = [dict(row) for row in events]
    try:
        forward = replay_events_with_delay(rows, delay_seconds=delay_seconds)
        reversed_input = replay_events_with_delay(
            reversed(rows), delay_seconds=delay_seconds,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        return {
            "status": "UNMEASURABLE",
            "reason": f"REPLAY_INPUT_INVALID:{type(exc).__name__}",
            "compared": 0,
            "paper_read_only": True,
            "real_execution": False,
        }
    stable = forward == reversed_input
    return {
        "status": "PROVEN" if stable else "REJECTED",
        "reason": "CANONICAL_REPLAY_ORDER_STABLE" if stable else "REPLAY_ORDER_MISMATCH",
        "compared": len(forward),
        "event_ids": tuple(str(row["event_id"]) for row in forward),
        "delay_seconds": float(delay_seconds),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["replay_events_with_delay", "replay_determinism_receipt"]
