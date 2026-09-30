"""Bounded causal L2 checkpoints for Lead-Lag research.

The periodic public L2 stream is useful for continuous context but cannot
guarantee a book observation within the replay's 750 ms causal window.  This
module detects the already-declared Binance shock online and describes one
bounded, read-only Hyperliquid ``/info`` checkpoint request.

There is deliberately no network client here.  The collector owns transport,
durability and source health; this module only provides deterministic signal
semantics and strict validation of a real L2 response.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

DIAGNOSTIC_SHOCK_THRESHOLD_BPS = 8.0
ECONOMIC_SHOCK_THRESHOLD_BPS = 20.0
SHOCK_WINDOW_MS = 1_000
SHOCK_COOLDOWN_MS = 5_000


def _positive(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


@dataclass(frozen=True, slots=True)
class LeadLagCheckpointConfig:
    """Frozen collection limits; none of these values select economic PnL."""

    window_ms: int = SHOCK_WINDOW_MS
    diagnostic_threshold_bps: float = DIAGNOSTIC_SHOCK_THRESHOLD_BPS
    economic_threshold_bps: float = ECONOMIC_SHOCK_THRESHOLD_BPS
    cooldown_ms: int = SHOCK_COOLDOWN_MS
    max_requests_per_minute: int = 30
    max_diagnostic_requests_per_minute: int = 10
    economic_request_reserve: int = 10
    allowed_coins: tuple[str, ...] = ("ETH",)

    def __post_init__(self) -> None:
        if self.window_ms <= 0 or self.cooldown_ms < 0:
            raise ValueError("invalid Lead-Lag checkpoint timing")
        if not 0 < self.diagnostic_threshold_bps <= self.economic_threshold_bps:
            raise ValueError("invalid Lead-Lag checkpoint thresholds")
        if self.max_requests_per_minute <= 0:
            raise ValueError("max_requests_per_minute must be positive")
        if not 0 <= self.max_diagnostic_requests_per_minute <= self.max_requests_per_minute:
            raise ValueError("invalid diagnostic request budget")
        if not 0 <= self.economic_request_reserve <= self.max_requests_per_minute:
            raise ValueError("invalid economic request reserve")


@dataclass(frozen=True, slots=True)
class LeadLagCheckpointRequest:
    coin: str
    trigger_event_id: str
    trigger_ts_ms: int
    trigger_monotonic_ns: int
    window_start_ts_ms: int
    lead_start_price: float
    lead_trigger_price: float
    lead_shock_bps: float
    direction: int
    threshold_class: str

    @property
    def economic_threshold_crossed(self) -> bool:
        return self.threshold_class == "ECONOMIC"

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "trigger_event_id": self.trigger_event_id,
            "trigger_ts_ms": self.trigger_ts_ms,
            "trigger_monotonic_ns": self.trigger_monotonic_ns,
            "window_start_ts_ms": self.window_start_ts_ms,
            "lead_start_price": self.lead_start_price,
            "lead_trigger_price": self.lead_trigger_price,
            "lead_shock_bps": self.lead_shock_bps,
            "direction": self.direction,
            "threshold_class": self.threshold_class,
            "economic_threshold_crossed": self.economic_threshold_crossed,
        }


class RollingShockCheckpointDetector:
    """Streaming equivalent of ``detect_rolling_shocks`` without lookahead.

    Diagnostic requests never consume the reserve kept for 20 bps economic
    shocks.  A prior diagnostic shock also cannot suppress a later economic
    shock during the same five-second interval.
    """

    def __init__(self, config: LeadLagCheckpointConfig | None = None) -> None:
        self.config = config or LeadLagCheckpointConfig()
        self._allowed = {coin.strip().upper() for coin in self.config.allowed_coins}
        self._windows: dict[str, deque[tuple[int, int, float]]] = {}
        self._last_economic_ms: dict[str, int] = {}
        self._last_diagnostic_ms: dict[str, int] = {}
        self._request_times_ms: deque[int] = deque()
        self._diagnostic_times_ms: deque[int] = deque()

    def _prune_budget(self, now_ms: int) -> None:
        cutoff = int(now_ms) - 60_000
        while self._request_times_ms and self._request_times_ms[0] <= cutoff:
            self._request_times_ms.popleft()
        while self._diagnostic_times_ms and self._diagnostic_times_ms[0] <= cutoff:
            self._diagnostic_times_ms.popleft()

    def _budget_allows(self, now_ms: int, *, economic: bool) -> bool:
        self._prune_budget(now_ms)
        if len(self._request_times_ms) >= self.config.max_requests_per_minute:
            return False
        if economic:
            return True
        diagnostic_total_limit = max(
            0,
            self.config.max_requests_per_minute - self.config.economic_request_reserve,
        )
        return bool(
            len(self._request_times_ms) < diagnostic_total_limit
            and len(self._diagnostic_times_ms)
            < self.config.max_diagnostic_requests_per_minute
        )

    def observe(
        self,
        *,
        coin: str,
        price: object,
        received_monotonic_ns: int,
        received_wall_ms: int,
        event_id: str,
    ) -> LeadLagCheckpointRequest | None:
        selected_coin = str(coin or "").strip().upper()
        parsed_price = _positive(price)
        monotonic_ns = int(received_monotonic_ns)
        wall_ms = int(received_wall_ms)
        if (
            selected_coin not in self._allowed
            or parsed_price is None
            or monotonic_ns <= 0
            or wall_ms < 1_500_000_000_000
        ):
            return None

        window = self._windows.setdefault(selected_coin, deque())
        if window and monotonic_ns <= window[-1][0]:
            return None
        window.append((monotonic_ns, wall_ms, parsed_price))
        window_ns = self.config.window_ms * 1_000_000
        while len(window) > 1 and monotonic_ns - window[0][0] > window_ns:
            window.popleft()
        if len(window) < 2:
            return None

        _, base_wall_ms, base_price = window[0]
        shock_bps = (parsed_price - base_price) / base_price * 10_000.0
        magnitude = abs(shock_bps)
        economic = magnitude >= self.config.economic_threshold_bps
        if not economic and magnitude < self.config.diagnostic_threshold_bps:
            return None

        if economic:
            previous_ms = self._last_economic_ms.get(selected_coin, -10**18)
        else:
            previous_ms = max(
                self._last_economic_ms.get(selected_coin, -10**18),
                self._last_diagnostic_ms.get(selected_coin, -10**18),
            )
        if wall_ms - previous_ms < self.config.cooldown_ms:
            return None
        if not self._budget_allows(wall_ms, economic=economic):
            return None

        self._request_times_ms.append(wall_ms)
        threshold_class = "ECONOMIC" if economic else "DIAGNOSTIC"
        if economic:
            self._last_economic_ms[selected_coin] = wall_ms
        else:
            self._last_diagnostic_ms[selected_coin] = wall_ms
            self._diagnostic_times_ms.append(wall_ms)
        return LeadLagCheckpointRequest(
            coin=selected_coin,
            trigger_event_id=str(event_id),
            trigger_ts_ms=wall_ms,
            trigger_monotonic_ns=monotonic_ns,
            window_start_ts_ms=int(base_wall_ms),
            lead_start_price=float(base_price),
            lead_trigger_price=float(parsed_price),
            lead_shock_bps=float(shock_bps),
            direction=1 if shock_bps > 0 else -1,
            threshold_class=threshold_class,
        )


@dataclass(frozen=True, slots=True)
class ValidatedL2Book:
    coin: str
    exchange_ts_ms: int
    bids: tuple[Mapping[str, Any] | Sequence[Any], ...]
    asks: tuple[Mapping[str, Any] | Sequence[Any], ...]
    bid_depth_usd: float
    ask_depth_usd: float

    def wrapped_message(self, request: LeadLagCheckpointRequest) -> dict[str, Any]:
        return {
            "channel": "l2Book",
            "data": {
                "coin": self.coin,
                "time": self.exchange_ts_ms,
                "levels": [list(self.bids), list(self.asks)],
            },
            "causal_checkpoint": request.as_dict(),
        }


def _validated_levels(
    raw_levels: object,
) -> tuple[tuple[Mapping[str, Any] | Sequence[Any], ...], float]:
    if not isinstance(raw_levels, Sequence) or isinstance(raw_levels, (str, bytes, bytearray)):
        raise ValueError("invalid L2 side")
    valid: list[Mapping[str, Any] | Sequence[Any]] = []
    depth = 0.0
    for raw in raw_levels:
        if isinstance(raw, Mapping):
            price = _positive(raw.get("px", raw.get("price")))
            size = _positive(raw.get("sz", raw.get("size")))
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            price = _positive(raw[0]) if len(raw) >= 1 else None
            size = _positive(raw[1]) if len(raw) >= 2 else None
        else:
            price = size = None
        if price is None or size is None:
            raise ValueError("invalid L2 level")
        valid.append(raw)
        depth += price * size
    if not valid:
        raise ValueError("empty L2 side")
    return tuple(valid), depth


def validate_l2_book_payload(
    payload: Mapping[str, Any],
    *,
    expected_coin: str,
) -> ValidatedL2Book:
    """Validate a real Hyperliquid ``l2Book`` response, fail closed."""

    if not isinstance(payload, Mapping):
        raise ValueError("l2Book response is not an object")
    coin = str(payload.get("coin") or "").strip().upper()
    if not coin or coin != str(expected_coin).strip().upper():
        raise ValueError("l2Book coin mismatch")
    exchange_ts = _positive(payload.get("time"))
    levels = payload.get("levels")
    if exchange_ts is None or not isinstance(levels, Sequence) or len(levels) < 2:
        raise ValueError("incomplete l2Book response")
    bids, bid_depth = _validated_levels(levels[0])
    asks, ask_depth = _validated_levels(levels[1])

    def first_price(row: Mapping[str, Any] | Sequence[Any]) -> float:
        if isinstance(row, Mapping):
            value = row.get("px", row.get("price"))
        else:
            value = row[0]
        parsed = _positive(value)
        if parsed is None:
            raise ValueError("invalid top of book")
        return parsed

    if first_price(asks[0]) < first_price(bids[0]):
        raise ValueError("crossed l2Book response")
    return ValidatedL2Book(
        coin=coin,
        exchange_ts_ms=int(exchange_ts),
        bids=bids,
        asks=asks,
        bid_depth_usd=float(bid_depth),
        ask_depth_usd=float(ask_depth),
    )


__all__ = [
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "ECONOMIC_SHOCK_THRESHOLD_BPS",
    "LeadLagCheckpointConfig",
    "LeadLagCheckpointRequest",
    "RollingShockCheckpointDetector",
    "SHOCK_COOLDOWN_MS",
    "SHOCK_WINDOW_MS",
    "ValidatedL2Book",
    "validate_l2_book_payload",
]
