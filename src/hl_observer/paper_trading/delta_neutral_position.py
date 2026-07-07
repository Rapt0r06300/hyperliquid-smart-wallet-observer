"""Paper delta-neutral position math."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeltaNeutralPosition:
    coin: str
    long_notional_usdt: float
    short_notional_usdt: float
    net_exposure_usdt: float
    exposure_ratio: float
    balanced: bool


def build_delta_neutral_position(
    *,
    coin: str,
    long_notional_usdt: float,
    short_notional_usdt: float,
    max_exposure_ratio: float = 0.05,
) -> DeltaNeutralPosition:
    long_n = max(0.0, float(long_notional_usdt or 0.0))
    short_n = max(0.0, float(short_notional_usdt or 0.0))
    gross = max(1e-9, long_n + short_n)
    net = long_n - short_n
    ratio = abs(net) / gross
    return DeltaNeutralPosition(str(coin).upper(), round(long_n, 8), round(short_n, 8), round(net, 8), round(ratio, 8), ratio <= float(max_exposure_ratio))


__all__ = ["DeltaNeutralPosition", "build_delta_neutral_position"]
