from __future__ import annotations

from pydantic import BaseModel


class PositionDelta(BaseModel):
    wallet: str
    coin: str
    previous_size: float
    current_size: float

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
    )
