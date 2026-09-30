"""Partial fill model for local replay."""

from __future__ import annotations


def estimate_partial_fill_ratio(*, requested_notional_usdt: float, available_depth_usdt: float) -> float:
    requested = max(float(requested_notional_usdt), 1e-9)
    return round(max(0.0, min(float(available_depth_usdt) / requested, 1.0)), 8)


__all__ = ["estimate_partial_fill_ratio"]
