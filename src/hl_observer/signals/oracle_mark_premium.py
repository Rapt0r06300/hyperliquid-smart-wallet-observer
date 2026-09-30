"""V15 #196 — Oracle vs mark premium as a signal (Hyperliquid-native)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OracleMarkPremium:
    premium_bps: float
    signal: str            # MARK_RICH | MARK_CHEAP | NEUTRAL
    side_hint: str | None  # mean-reversion side hint


def oracle_mark_premium(
    *,
    oracle_px: float,
    mark_px: float,
    threshold_bps: float = 10.0,
) -> OracleMarkPremium:
    if oracle_px <= 0:
        return OracleMarkPremium(0.0, "NEUTRAL", None)
    prem = (float(mark_px) - float(oracle_px)) / float(oracle_px) * 10_000.0
    if prem >= threshold_bps:
        return OracleMarkPremium(round(prem, 4), "MARK_RICH", "SHORT")   # mark above oracle -> fade up
    if prem <= -threshold_bps:
        return OracleMarkPremium(round(prem, 4), "MARK_CHEAP", "LONG")
    return OracleMarkPremium(round(prem, 4), "NEUTRAL", None)


__all__ = ["OracleMarkPremium", "oracle_mark_premium"]
