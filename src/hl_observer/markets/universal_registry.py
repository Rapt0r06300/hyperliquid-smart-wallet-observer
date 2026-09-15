"""Universal point-in-time market registry for discovery, native and history coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from hl_observer.collection.native_venue_market import canonical_coin


class AvailabilityStatus(StrEnum):
    NATIVE_LIVE = "NATIVE_LIVE"
    HISTORICAL_ONLY = "HISTORICAL_ONLY"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    SPECIALIZED = "SPECIALIZED"
    UNAVAILABLE = "UNAVAILABLE"
    REQUIRES_KEY = "REQUIRES_KEY"


class DiscoveryEventType(StrEnum):
    NEW_MARKET = "NEW_MARKET"
    NEW_PERP = "NEW_PERP"
    NEW_VENUE = "NEW_VENUE"
    DELISTED = "DELISTED"
    REACTIVATED = "REACTIVATED"


@dataclass(frozen=True, slots=True)
class MarketInstrument:
    venue: str
    exchange_symbol: str
    status: AvailabilityStatus
    market_type: str = "perp"
    active: bool = True
    historical: bool = False
    discovery: bool = False
    specialized: bool = False


@dataclass(slots=True)
class RegisteredMarket:
    coin: str
    instruments: dict[str, MarketInstrument] = field(default_factory=dict)
    volume_24h: float | None = None
    open_interest: float | None = None
    liquidity: float | None = None
    replay_quality: str = "UNMEASURABLE"

    @property
    def venue_count(self) -> int:
        return sum(item.active for item in self.instruments.values())

    @property
    def native_venue_count(self) -> int:
        return len(self.hot_path_venues)

    @property
    def hot_path_venues(self) -> tuple[str, ...]:
        return tuple(sorted(item.venue for item in self.instruments.values() if item.active and item.status is AvailabilityStatus.NATIVE_LIVE))

    @property
    def historical_venue_count(self) -> int:
        return sum(item.active and item.historical for item in self.instruments.values())


@dataclass(frozen=True, slots=True)
class DiscoveryEvent:
    event_type: DiscoveryEventType
    coin: str
    venue: str
    exchange_symbol: str
    observed_at_ms: int


@dataclass(frozen=True, slots=True)
class HotCandidate:
    coin: str
    reason: str
    created_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True, slots=True)
class CandidateScore:
    coin: str
    score: float
    venue_count: int
    native_venue_count: int
    historical_venue_count: int
    replay_quality: str
    hot_path_eligible: bool


class UniversalMarketRegistry:
    """Single aggregation layer; discovery metadata never becomes market data."""

    def __init__(self, *, native_venues: Iterable[str] = (), hot_candidate_hours: int = 72) -> None:
        self.native_venues = {str(venue).strip().lower() for venue in native_venues}
        self.hot_candidate_ms = max(1, int(hot_candidate_hours)) * 3_600_000
        self._markets: dict[str, RegisteredMarket] = {}
        self._snapshot_active: dict[tuple[str, str], dict[str, Any]] = {}
        self._hot: dict[str, HotCandidate] = {}

    def register(
        self,
        coin: str,
        venue: str,
        exchange_symbol: str,
        *,
        native: bool = False,
        historical: bool = False,
        discovery: bool = False,
        specialized: bool = False,
        requires_key: bool = False,
        available: bool = True,
        active: bool = True,
        market_type: str = "perp",
    ) -> MarketInstrument:
        base = canonical_coin(coin)
        venue_key = str(venue).strip().lower()
        if native and venue_key in self.native_venues:
            status = AvailabilityStatus.NATIVE_LIVE
        elif specialized:
            status = AvailabilityStatus.REQUIRES_KEY if requires_key else AvailabilityStatus.SPECIALIZED
        elif historical:
            status = AvailabilityStatus.HISTORICAL_ONLY
        elif discovery and available:
            status = AvailabilityStatus.DISCOVERY_ONLY
        else:
            status = AvailabilityStatus.UNAVAILABLE
        instrument = MarketInstrument(
            venue=venue_key,
            exchange_symbol=str(exchange_symbol).strip().upper(),
            status=status,
            market_type=str(market_type).lower(),
            active=bool(active),
            historical=bool(historical),
            discovery=bool(discovery),
            specialized=bool(specialized),
        )
        self._markets.setdefault(base, RegisteredMarket(base)).instruments[venue_key] = instrument
        return instrument

    def market(self, coin: str) -> RegisteredMarket:
        return self._markets[canonical_coin(coin)]

    def update_metrics(self, coin: str, *, volume_24h: float | None = None, open_interest: float | None = None, liquidity: float | None = None, replay_quality: str | None = None) -> None:
        market = self._markets.setdefault(canonical_coin(coin), RegisteredMarket(canonical_coin(coin)))
        market.volume_24h = _positive(volume_24h)
        market.open_interest = _positive(open_interest)
        market.liquidity = _positive(liquidity)
        if replay_quality:
            market.replay_quality = str(replay_quality).upper()

    def candidates(self, *, min_native_venues: int = 2) -> list[CandidateScore]:
        quality_points = {"UNMEASURABLE": 0, "BRONZE": 5, "SILVER": 12, "GOLD": 20}
        rows: list[CandidateScore] = []
        for market in self._markets.values():
            score = (
                min(market.venue_count, 8) * 5
                + min(market.native_venue_count, 6) * 12
                + min(market.historical_venue_count, 4) * 5
                + quality_points.get(market.replay_quality, 0)
                + _scale(market.volume_24h, 1_000_000)
                + _scale(market.open_interest, 250_000)
                + _scale(market.liquidity, 50_000)
            )
            rows.append(CandidateScore(market.coin, round(score, 3), market.venue_count, market.native_venue_count, market.historical_venue_count, market.replay_quality, market.native_venue_count >= max(1, min_native_venues)))
        return sorted(rows, key=lambda row: (-row.score, row.coin))

    def apply_snapshot(self, rows: Iterable[Mapping[str, Any]], *, observed_at_ms: int) -> list[DiscoveryEvent]:
        current: dict[tuple[str, str], dict[str, Any]] = {}
        events: list[DiscoveryEvent] = []
        previous_coins = {coin for coin, _venue in self._snapshot_active}
        for raw in rows:
            coin = canonical_coin(str(raw.get("coin") or raw.get("canonical_coin") or ""))
            venue = str(raw.get("venue") or "").strip().lower()
            symbol = str(raw.get("symbol") or raw.get("exchange_symbol") or "").strip().upper()
            if not coin or not venue or not symbol or raw.get("active") is False:
                continue
            key = (coin, venue)
            item = dict(raw)
            item.update({"coin": coin, "venue": venue, "symbol": symbol})
            current[key] = item
            old = self._snapshot_active.get(key)
            if old is None:
                was_known = coin in previous_coins
                event_type = DiscoveryEventType.NEW_VENUE if was_known else DiscoveryEventType.NEW_MARKET
                events.append(DiscoveryEvent(event_type, coin, venue, symbol, int(observed_at_ms)))
                if bool(raw.get("perpetual")):
                    events.append(DiscoveryEvent(DiscoveryEventType.NEW_PERP, coin, venue, symbol, int(observed_at_ms)))
                self._enqueue(coin, event_type.value, int(observed_at_ms))
            elif old.get("active") is False:
                events.append(DiscoveryEvent(DiscoveryEventType.REACTIVATED, coin, venue, symbol, int(observed_at_ms)))
                self._enqueue(coin, DiscoveryEventType.REACTIVATED.value, int(observed_at_ms))
            self.register(coin, venue, symbol, native=venue in self.native_venues, discovery=True, active=True, market_type="perp" if raw.get("perpetual") else str(raw.get("market_type") or "spot"))
        for key, old in self._snapshot_active.items():
            if key not in current and old.get("active") is not False:
                coin, venue = key
                events.append(DiscoveryEvent(DiscoveryEventType.DELISTED, coin, venue, str(old["symbol"]), int(observed_at_ms)))
                current[key] = {**old, "active": False}
                if coin in self._markets and venue in self._markets[coin].instruments:
                    prior = self._markets[coin].instruments[venue]
                    self._markets[coin].instruments[venue] = MarketInstrument(**{**asdict(prior), "active": False})
        self._snapshot_active = current
        return events

    def hot_candidates(self, *, now_ms: int) -> list[HotCandidate]:
        self._hot = {coin: item for coin, item in self._hot.items() if item.expires_at_ms >= int(now_ms)}
        return sorted(self._hot.values(), key=lambda item: (item.expires_at_ms, item.coin))

    def _enqueue(self, coin: str, reason: str, now_ms: int) -> None:
        self._hot[coin] = HotCandidate(coin, reason, now_ms, now_ms + self.hot_candidate_ms)

    def dump(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "markets": {coin: {"coin": row.coin, "instruments": {venue: {**asdict(item), "status": item.status.value} for venue, item in row.instruments.items()}, "volume_24h": row.volume_24h, "open_interest": row.open_interest, "liquidity": row.liquidity, "replay_quality": row.replay_quality} for coin, row in sorted(self._markets.items())},
            "hot_candidates": [asdict(row) for row in self._hot.values()],
        }
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)

    def register_specialized_sources(self) -> None:
        """Expose existing context adapters in this registry without hot-path promotion."""
        from hl_observer.venues.registre_venues import registre
        for venue, capabilities in registre().items():
            if venue in self.native_venues or venue in {"binance", "hyperliquid"}:
                continue
            self.register(venue, venue, venue, specialized=True, requires_key=capabilities.get("pull_live") == "REQUIRES_KEY", active=False)


def _positive(value: float | None) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _scale(value: float | None, unit: float) -> float:
    return min(10.0, (value or 0.0) / unit) if value is not None else 0.0


__all__ = ["AvailabilityStatus", "CandidateScore", "DiscoveryEvent", "DiscoveryEventType", "HotCandidate", "MarketInstrument", "RegisteredMarket", "UniversalMarketRegistry"]
