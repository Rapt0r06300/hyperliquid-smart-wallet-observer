"""Canonical identities for batched read-only market events.

Hyperliquid can deliver several fills or trades in one WebSocket frame.  The
transport sequence identifies the frame, not each item in that frame.  Keeping
the three concepts below separate prevents two opposite bugs:

* collapsing distinct items that share a timestamp/frame;
* reporting a false sequence regression for the second item in a frame.

This module is deliberately transport-only.  It contains no strategy or
execution logic.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


_VOLATILE_FIELDS = {
    "received_at_ms",
    "recv_ts_ms",
    "write_ts_ms",
    "frame_sequence",
    "event_index_in_frame",
}


def _canonical_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in payload.items()
        if str(key) not in _VOLATILE_FIELDS
    }


def stable_item_id(
    payload: Mapping[str, Any],
    *,
    source: str,
    channel: str,
) -> str:
    """Return a replay-stable identity for one market event.

    Venue identifiers are retained in the canonical payload when present.
    Reception/write clocks and transport frame coordinates are excluded so a
    reconnect replay resolves to the same identity.
    """

    document = {
        "source": str(source),
        "channel": str(channel),
        "payload": _canonical_payload(payload),
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalFrameEvent:
    source: str
    channel: str
    frame_sequence: int | None
    event_index_in_frame: int
    stable_event_id: str
    exchange_ts_ms: int | None
    received_at_ms: int
    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonicalize_frame(
    items: Iterable[Mapping[str, Any]],
    *,
    source: str,
    channel: str,
    received_at_ms: int,
    frame_sequence: int | None = None,
    exchange_ts_fields: tuple[str, ...] = ("time", "timestamp", "ts_ms"),
) -> list[CanonicalFrameEvent]:
    """Expand one frame into independently identifiable canonical events."""

    result: list[CanonicalFrameEvent] = []
    for index, raw in enumerate(items):
        payload = dict(raw)
        exchange_ts: int | None = None
        for field_name in exchange_ts_fields:
            candidate = payload.get(field_name)
            if candidate is None:
                continue
            try:
                exchange_ts = int(candidate)
            except (TypeError, ValueError):
                exchange_ts = None
            break
        result.append(
            CanonicalFrameEvent(
                source=str(source),
                channel=str(channel),
                frame_sequence=None if frame_sequence is None else int(frame_sequence),
                event_index_in_frame=index,
                stable_event_id=stable_item_id(
                    payload,
                    source=source,
                    channel=channel,
                ),
                exchange_ts_ms=exchange_ts,
                received_at_ms=int(received_at_ms),
                payload=payload,
            )
        )
    return result


__all__ = [
    "CanonicalFrameEvent",
    "canonicalize_frame",
    "stable_item_id",
]
