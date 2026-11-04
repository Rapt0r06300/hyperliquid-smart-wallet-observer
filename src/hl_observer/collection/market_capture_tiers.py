"""Deterministic, causal capture tiers for bounded public market collection."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class CaptureTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"


@dataclass(frozen=True, slots=True)
class MarketCaptureEvidence:
    volume_percentile: float = 0.0
    trades_per_second: float = 0.0
    depth_usd_10bps: float = 0.0
    spread_bps: float = 0.0
    updates_per_second: float = 0.0
    volatility_bps: float = 0.0
    venue_count: int = 1
    strategy_priority: bool = False
    gap_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class CaptureProfile:
    tier: CaptureTier
    depth: int
    channels: tuple[str, ...]


def capture_score(e: MarketCaptureEvidence) -> int:
    """Score only already-observed evidence; no future data and no ML."""
    return sum((
        2 if e.volume_percentile >= 0.90 else 1 if e.volume_percentile >= 0.60 else 0,
        2 if e.trades_per_second >= 5 else 1 if e.trades_per_second >= 1 else 0,
        1 if e.depth_usd_10bps >= 100_000 else 0,
        1 if e.updates_per_second >= 5 else 0,
        1 if e.volatility_bps >= 20 else 0,
        2 if e.venue_count >= 3 else 1 if e.venue_count >= 2 else 0,
        2 if e.strategy_priority else 0,
        -2 if e.gap_rate >= 0.05 else 0,
    ))


def decide_capture_tier(
    evidence: MarketCaptureEvidence,
    *,
    previous: CaptureTier | None = None,
) -> CaptureTier:
    """One-step hysteresis prevents A/C flapping and abrupt bandwidth spikes."""
    score = capture_score(evidence)
    target = CaptureTier.A if score >= 7 else CaptureTier.B if score >= 3 else CaptureTier.C
    if previous == CaptureTier.A and target == CaptureTier.C:
        return CaptureTier.B
    if previous == CaptureTier.C and target == CaptureTier.A:
        return CaptureTier.B
    return target


_PROFILES: Mapping[str, Mapping[CaptureTier, CaptureProfile]] = {
    "binance": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 1000, ("depth", "bookTicker", "aggTrade", "markPrice", "forceOrder")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 100, ("depth", "bookTicker", "aggTrade", "markPrice")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 5, ("bookTicker", "aggTrade")),
    },
    "hyperliquid": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 20, ("l2Book", "bbo", "trades", "allMids", "activeAssetCtx")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 10, ("l2Book", "bbo", "trades", "activeAssetCtx")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 1, ("bbo", "trades", "allMids")),
    },
    "bybit": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 1000, ("orderbook", "bbo", "trades", "ticker", "liquidations")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 200, ("orderbook", "bbo", "trades", "ticker")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 1, ("bbo", "trades")),
    },
    "okx": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 400, ("books", "bbo-tbt", "trades", "tickers", "funding-rate", "open-interest", "mark-price", "index-tickers")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 400, ("books", "bbo-tbt", "trades", "tickers")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 1, ("bbo-tbt", "trades")),
    },
    "bitget": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 400, ("books", "books1", "ticker", "trade", "liquidation")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 15, ("books15", "books1", "ticker", "trade")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 1, ("books1", "trade")),
    },
    "gate": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 100, ("futures.order_book_update", "futures.book_ticker", "futures.trades", "futures.tickers")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 50, ("futures.order_book_update", "futures.book_ticker", "futures.trades")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 1, ("futures.book_ticker", "futures.trades")),
    },
    "deribit": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 1000, ("book", "trades", "ticker")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 100, ("book", "trades", "ticker")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 1, ("ticker", "trades")),
    },
    "kraken": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 1000, ("book", "trade", "ticker")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 100, ("book", "trade", "ticker")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 1, ("ticker", "trade")),
    },
    "coinbase": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 1000, ("level2", "market_trades", "heartbeats")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 100, ("level2", "market_trades", "heartbeats")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 1, ("ticker", "market_trades", "heartbeats")),
    },
    "htx": {
        CaptureTier.A: CaptureProfile(CaptureTier.A, 400, ("mbp", "trade", "bbo")),
        CaptureTier.B: CaptureProfile(CaptureTier.B, 150, ("mbp", "trade", "bbo")),
        CaptureTier.C: CaptureProfile(CaptureTier.C, 5, ("mbp", "trade", "bbo")),
    },
}


def capture_profile(venue: str, tier: CaptureTier | str) -> CaptureProfile:
    venue_key = str(venue).strip().lower()
    tier_key = tier if isinstance(tier, CaptureTier) else CaptureTier(str(tier).upper())
    try:
        return _PROFILES[venue_key][tier_key]
    except KeyError as exc:
        raise ValueError(f"unsupported capture venue: {venue_key}") from exc


def classify_l2_frequency(timestamps_ms: Sequence[object], *, max_interval_ms: int) -> dict[str, object]:
    """Measure useful L2 cadence from observed timestamps only."""
    if type(max_interval_ms) is not int or max_interval_ms <= 0:
        return {"status": "UNMEASURABLE", "reason": "INTERVAL_INVALID", "paper_read_only": True}
    values = [value for value in timestamps_ms if type(value) is int and value > 0]
    if len(values) < 2 or values != sorted(values):
        return {"status": "UNMEASURABLE", "reason": "TIMESTAMPS_INSUFFICIENT_OR_UNORDERED", "paper_read_only": True}
    gaps = [b - a for a, b in zip(values, values[1:])]
    return {"status": "PROVEN" if max(gaps) <= max_interval_ms else "MORE_DATA", "sample_count": len(values), "min_interval_ms": min(gaps), "max_interval_ms": max(gaps), "mean_interval_ms": sum(gaps) / len(gaps), "paper_read_only": True, "real_execution": False}


__all__ = ["CaptureProfile", "CaptureTier", "MarketCaptureEvidence", "capture_profile", "capture_score", "classify_l2_frequency", "decide_capture_tier"]
