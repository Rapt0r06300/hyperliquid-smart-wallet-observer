from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _fill_time(fill: dict[str, Any]) -> int:
    return int(fill.get("time") or fill.get("timestamp") or 0)


def signed_fill_size(fill: dict[str, Any]) -> float | None:
    size = _safe_float(fill.get("sz") or fill.get("size"))
    if size is None:
        return None

    side = str(fill.get("side") or "").strip().lower()
    if side in {"b", "buy", "bid"}:
        return abs(size)
    if side in {"a", "s", "sell", "ask"}:
        return -abs(size)

    direction = str(fill.get("dir") or "").strip().lower()
    if "open long" in direction or "close short" in direction:
        return abs(size)
    if "open short" in direction or "close long" in direction:
        return -abs(size)
    return None


def classify_delta(previous_size: float, current_size: float) -> str:
    if previous_size == current_size:
        return "unchanged"
    if previous_size == 0 and current_size > 0:
        return "open_long"
    if previous_size == 0 and current_size < 0:
        return "open_short"
    if previous_size > 0 and current_size == 0:
        return "close_long"
    if previous_size < 0 and current_size == 0:
        return "close_short"
    if previous_size > 0 and current_size < 0:
        return "flip_long_to_short"
    if previous_size < 0 and current_size > 0:
        return "flip_short_to_long"
    if previous_size > 0 and current_size > previous_size:
        return "add_long"
    if previous_size > 0 and current_size < previous_size:
        return "reduce_long"
    if previous_size < 0 and current_size < previous_size:
        return "add_short"
    if previous_size < 0 and current_size > previous_size:
        return "reduce_short"
    return "unknown"


class PositionDelta(BaseModel):
    wallet: str
    coin: str
    previous_size: float
    current_size: float
    exchange_ts: int | None = None
    side: str | None = None
    price: float | None = None
    fill_size: float | None = None
    delta_type: str = "unknown"
    confidence: str = "medium"
    source: str = "fills"
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def delta_size(self) -> float:
        return self.current_size - self.previous_size


def detect_position_delta(wallet: str, coin: str, previous_size: float, current_size: float) -> PositionDelta | None:
    if previous_size == current_size:
        return None
    return PositionDelta(
        wallet=wallet,
        coin=coin,
        previous_size=previous_size,
        current_size=current_size,
        delta_type=classify_delta(previous_size, current_size),
        confidence="manual",
    )


def reconstruct_position_deltas_from_fills(
    wallet: str,
    fills: list[dict[str, Any]],
) -> list[PositionDelta]:
    deltas: list[PositionDelta] = []
    cumulative_by_coin: dict[str, float] = {}

    for fill in sorted(fills, key=_fill_time):
        coin = str(fill.get("coin") or fill.get("coinName") or "UNKNOWN").upper()
        signed_size = signed_fill_size(fill)
        if signed_size is None:
            continue

        start_position = _safe_float(_first_present(fill, "startPosition", "start_position"))
        if start_position is None:
            previous_size = cumulative_by_coin.get(coin, 0.0)
            confidence = "medium"
        else:
            previous_size = start_position
            confidence = "high"

        current_size = previous_size + signed_size
        cumulative_by_coin[coin] = current_size
        if previous_size == current_size:
            continue

        deltas.append(
            PositionDelta(
                wallet=wallet,
                coin=coin,
                previous_size=previous_size,
                current_size=current_size,
                exchange_ts=_fill_time(fill) or None,
                side=str(fill.get("side")) if fill.get("side") is not None else None,
                price=_safe_float(_first_present(fill, "px", "price")),
                fill_size=abs(signed_size),
                delta_type=classify_delta(previous_size, current_size),
                confidence=confidence,
                source="user_fills",
                raw=fill,
            )
        )
    return deltas
