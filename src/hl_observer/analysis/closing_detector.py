from __future__ import annotations

from pydantic import BaseModel

from hl_observer.analysis.closing_classifier import ClosingType, classify_closing


class ClosingEvent(BaseModel):
    wallet_address: str
    coin: str
    action: str
    closing_type: ClosingType
    detected_at_ms: int | None = None
    confidence_score: float = 0.0


def detect_closings_from_deltas(deltas: list[object]) -> list[ClosingEvent]:
    events: list[ClosingEvent] = []
    for delta in deltas:
        action = str(getattr(delta, "action", "") or "").upper()
        if action not in {"REDUCE", "CLOSE", "FLIP"}:
            continue
        raw = getattr(delta, "raw_json", None) or getattr(delta, "raw", {}) or {}
        closed_pnl = raw.get("closedPnl") if isinstance(raw, dict) else None
        try:
            closed_pnl_float = float(closed_pnl) if closed_pnl is not None else None
        except (TypeError, ValueError):
            closed_pnl_float = None
        events.append(
            ClosingEvent(
                wallet_address=str(getattr(delta, "wallet_address", getattr(delta, "wallet", ""))),
                coin=str(getattr(delta, "coin", "UNKNOWN")).upper(),
                action=action,
                closing_type=classify_closing(action=action, closed_pnl=closed_pnl_float),
                detected_at_ms=getattr(delta, "detected_at_ms", None) or getattr(delta, "exchange_ts", None),
                confidence_score=float(getattr(delta, "confidence_score", 0.0) or 0.0),
            )
        )
    return events
