from __future__ import annotations

from pydantic import BaseModel

from hl_observer.analysis.opening_classifier import OpeningType, classify_opening


class OpeningEvent(BaseModel):
    wallet_address: str
    coin: str
    action: str
    side: str | None = None
    opening_type: OpeningType
    detected_at_ms: int | None = None
    confidence_score: float = 0.0


def detect_openings_from_deltas(deltas: list[object]) -> list[OpeningEvent]:
    events: list[OpeningEvent] = []
    for delta in deltas:
        action = str(getattr(delta, "action", "") or "").upper()
        if action not in {"OPEN", "ADD", "FLIP"}:
            continue
        side = getattr(delta, "new_side", None) or getattr(delta, "side", None)
        side_text = str(side) if side is not None else None
        events.append(
            OpeningEvent(
                wallet_address=str(getattr(delta, "wallet_address", getattr(delta, "wallet", ""))),
                coin=str(getattr(delta, "coin", "UNKNOWN")).upper(),
                action=action,
                side=side_text,
                opening_type=classify_opening(action=action, side=side_text),
                detected_at_ms=getattr(delta, "detected_at_ms", None) or getattr(delta, "exchange_ts", None),
                confidence_score=float(getattr(delta, "confidence_score", 0.0) or 0.0),
            )
        )
    return events
