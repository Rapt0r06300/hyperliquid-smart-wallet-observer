"""Normalize exchange fee configs into bps."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExchangeFee:
    source: str
    maker_bps: float
    taker_bps: float


def normalize_fee_bps(source: str, *, maker: float, taker: float, input_unit: str = "fraction") -> ExchangeFee:
    if input_unit == "fraction":
        maker_bps = float(maker) * 10_000.0
        taker_bps = float(taker) * 10_000.0
    elif input_unit == "percent":
        maker_bps = float(maker) * 100.0
        taker_bps = float(taker) * 100.0
    else:
        maker_bps = float(maker)
        taker_bps = float(taker)
    return ExchangeFee(str(source), round(maker_bps, 8), round(taker_bps, 8))


__all__ = ["ExchangeFee", "normalize_fee_bps"]
