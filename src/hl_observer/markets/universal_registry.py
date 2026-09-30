"""Universal point-in-time market registry for discovery, native and history coverage."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

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
    NEW_SPOT = "NEW_SPOT"
    NEW_DEX_PAIR = "NEW_DEX_PAIR"
    NEW_VENUE = "NEW_VENUE"
    DELISTED = "DELISTED"
    REACTIVATED = "REACTIVATED"


@dataclass(frozen=True, slots=True)
class MarketInstrument:
    venue: str
    exchange_symbol: str
    status: AvailabilityStatus
    market_type: str = "perp"
    quote: str | None = None
    settle: str | None = None
    linear: bool | None = None
    inverse: bool | None = None
    contract_size: float | None = None
    active: bool = True
    native: bool = False
    historical: bool = False
    discovery: bool = False
    specialized: bool = False
    requires_key: bool = False
    replay_quality: str = "UNMEASURABLE"
    first_observed_at_ms: int | None = None
    last_observed_at_ms: int | None = None

    @property
    def identity(self) -> str:
        return _instrument_key(self.venue, self.exchange_symbol, self.market_type, self.settle)


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
        return len({item.venue for item in self.instruments.values() if item.active})

    @property
    def native_venue_count(self) -> int:
        return len(self.hot_path_venues)

    @property
    def hot_path_venues(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.venue
                    for item in self.instruments.values()
                    if item.active and item.status is AvailabilityStatus.NATIVE_LIVE
                }
            )
        )

    @property
    def historical_venue_count(self) -> int:
        return len({item.venue for item in self.instruments.values() if item.active and item.historical})

    @property
    def status(self) -> AvailabilityStatus:
        priority = {
            AvailabilityStatus.NATIVE_LIVE: 0,
            AvailabilityStatus.HISTORICAL_ONLY: 1,
            AvailabilityStatus.DISCOVERY_ONLY: 2,
            AvailabilityStatus.SPECIALIZED: 3,
            AvailabilityStatus.REQUIRES_KEY: 4,
            AvailabilityStatus.UNAVAILABLE: 5,
        }
        active = [item.status for item in self.instruments.values() if item.active]
        return min(active, key=priority.__getitem__) if active else AvailabilityStatus.UNAVAILABLE

    def instruments_for_venue(self, venue: str) -> tuple[MarketInstrument, ...]:
        venue_key = _canonical_venue(venue)
        return tuple(
            sorted(
                (item for item in self.instruments.values() if item.venue == venue_key),
                key=lambda item: item.identity,
            )
        )


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
    source: str = ""
    venues: tuple[str, ...] = ()


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
        self.native_venues = {_canonical_venue(venue) for venue in native_venues}
        self.hot_candidate_ms = max(1, int(hot_candidate_hours)) * 3_600_000
        self._markets: dict[str, RegisteredMarket] = {}
        self._snapshot_active: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        self._hot: dict[str, HotCandidate] = {}
        self._specialized_sources: dict[str, AvailabilityStatus] = {}

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
        quote: str | None = None,
        settle: str | None = None,
        linear: bool | None = None,
        inverse: bool | None = None,
        contract_size: float | None = None,
        replay_quality: str = "UNMEASURABLE",
        first_observed_at_ms: int | None = None,
        last_observed_at_ms: int | None = None,
    ) -> MarketInstrument:
        base = canonical_coin(coin)
        venue_key = _canonical_venue(venue)
        symbol = str(exchange_symbol).strip().upper()
        market_kind = str(market_type).strip().lower()
        settle_key = _currency(settle)
        key = _instrument_key(venue_key, symbol, market_kind, settle_key)
        prior = self._markets.get(base, RegisteredMarket(base)).instruments.get(key)
        native = bool(native or (prior and prior.native))
        historical = bool(historical or (prior and prior.historical))
        discovery = bool(discovery or (prior and prior.discovery))
        specialized = bool(specialized or (prior and prior.specialized))
        requires_key = bool(requires_key or (prior and prior.requires_key))
        if native and venue_key in self.native_venues:
            status = AvailabilityStatus.NATIVE_LIVE
        elif historical:
            status = AvailabilityStatus.HISTORICAL_ONLY
        elif discovery and available:
            status = AvailabilityStatus.DISCOVERY_ONLY
        elif requires_key:
            status = AvailabilityStatus.REQUIRES_KEY
        elif specialized:
            status = AvailabilityStatus.SPECIALIZED
        else:
            status = AvailabilityStatus.UNAVAILABLE
        instrument = MarketInstrument(
            venue=venue_key,
            exchange_symbol=symbol,
            status=status,
            market_type=market_kind,
            quote=_currency(quote) or (prior.quote if prior else None),
            settle=settle_key or (prior.settle if prior else None),
            linear=linear if linear is not None else (prior.linear if prior else None),
            inverse=inverse if inverse is not None else (prior.inverse if prior else None),
            contract_size=_positive(contract_size)
            if contract_size is not None
            else (prior.contract_size if prior else None),
            active=bool(active),
            native=native,
            historical=bool(historical),
            discovery=bool(discovery),
            specialized=bool(specialized),
            requires_key=requires_key,
            replay_quality=str(replay_quality or (prior.replay_quality if prior else "UNMEASURABLE")).upper(),
            first_observed_at_ms=_earliest(
                first_observed_at_ms, prior.first_observed_at_ms if prior else None
            ),
            last_observed_at_ms=_latest(last_observed_at_ms, prior.last_observed_at_ms if prior else None),
        )
        self._markets.setdefault(base, RegisteredMarket(base)).instruments[key] = instrument
        return instrument

    def market(self, coin: str) -> RegisteredMarket:
        return self._markets[canonical_coin(coin)]

    @property
    def coins(self) -> tuple[str, ...]:
        return tuple(sorted(self._markets))

    @property
    def specialized_sources(self) -> dict[str, AvailabilityStatus]:
        return dict(self._specialized_sources)

    def coins_at_least_venues(self, minimum: int) -> list[str]:
        return sorted(row.coin for row in self._markets.values() if row.venue_count >= max(1, int(minimum)))

    def coins_at_least_native_venues(self, minimum: int) -> list[str]:
        return sorted(
            row.coin for row in self._markets.values() if row.native_venue_count >= max(1, int(minimum))
        )

    def summary(self, *, min_native_venues: int = 2) -> dict[str, int]:
        instruments = [item for market in self._markets.values() for item in market.instruments.values()]
        return {
            "coins": len(self._markets),
            "instruments": len(instruments),
            "native_live": sum(
                item.active and item.status is AvailabilityStatus.NATIVE_LIVE for item in instruments
            ),
            "discovery_only": sum(
                item.active and item.status is AvailabilityStatus.DISCOVERY_ONLY for item in instruments
            ),
            "historical_only": sum(
                item.active and item.status is AvailabilityStatus.HISTORICAL_ONLY for item in instruments
            ),
            "multi_venue_2+": len(self.coins_at_least_venues(2)),
            "hot_path_eligible": len(self.coins_at_least_native_venues(min_native_venues)),
        }

    def ingest_ccxt(self, result: Any) -> list[DiscoveryEvent]:
        """Register CCXT discovery metadata without routing CCXT data to hot paths."""
        markets = tuple(getattr(result, "markets", result))
        observed_at_ms = _iso_ms(getattr(result, "discovered_at", None))
        if observed_at_ms is None and markets:
            observed_at_ms = _iso_ms(getattr(markets[0], "discovered_at", None))
        if observed_at_ms is None:
            observed_at_ms = int(datetime.now().timestamp() * 1000)
        return self.apply_snapshot(
            (
                {
                    "coin": row.canonical_base,
                    "venue": row.venue,
                    "symbol": row.exchange_symbol,
                    "active": bool(getattr(row, "active", True)),
                    "market_type": getattr(row, "market_type", "perp"),
                    "perpetual": getattr(row, "market_type", "perp") == "perp",
                    "quote": getattr(row, "quote", None),
                    "settle": getattr(row, "settle_currency", None),
                    "linear": getattr(row, "linear", None),
                    "inverse": getattr(row, "inverse", None),
                    "contract_size": getattr(row, "contract_size", None),
                    "source": "ccxt",
                }
                for row in markets
            ),
            observed_at_ms=observed_at_ms,
            source="ccxt",
        )

    def ingest_historical_capabilities(self, hub: Any, requests: Iterable[Any]) -> None:
        """Expose already configured historical capabilities without fetching data."""
        for request in requests:
            if not hub.supports(request):
                continue
            coin = canonical_coin(request.canonical_coin)
            venue = _canonical_venue(request.venue)
            symbol = str(request.exchange_symbol).strip().upper()
            existing = (
                item
                for item in self._markets.get(coin, RegisteredMarket(coin)).instruments.values()
                if item.venue == venue and item.exchange_symbol == symbol
            )
            prior = next(existing, None)
            if prior is None:
                self.register(coin, venue, symbol, historical=True)
                continue
            self.register(
                coin,
                venue,
                symbol,
                native=prior.native,
                historical=True,
                discovery=prior.discovery,
                specialized=prior.specialized,
                requires_key=prior.requires_key,
                active=prior.active,
                market_type=prior.market_type,
                quote=prior.quote,
                settle=prior.settle,
                linear=prior.linear,
                inverse=prior.inverse,
                contract_size=prior.contract_size,
                replay_quality=prior.replay_quality,
                first_observed_at_ms=prior.first_observed_at_ms,
                last_observed_at_ms=prior.last_observed_at_ms,
            )

    def update_metrics(
        self,
        coin: str,
        *,
        volume_24h: float | None = None,
        open_interest: float | None = None,
        liquidity: float | None = None,
        replay_quality: str | None = None,
    ) -> None:
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
                + (10 if market.coin in self._hot else 0)
            )
            rows.append(
                CandidateScore(
                    market.coin,
                    round(score, 3),
                    market.venue_count,
                    market.native_venue_count,
                    market.historical_venue_count,
                    market.replay_quality,
                    market.native_venue_count >= max(1, min_native_venues),
                )
            )
        return sorted(rows, key=lambda row: (-row.score, row.coin))

    def apply_snapshot(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        observed_at_ms: int,
        source: str = "default",
    ) -> list[DiscoveryEvent]:
        scope = str(source or "default").strip().lower()
        previous = {key: value for key, value in self._snapshot_active.items() if key[0] == scope}
        current: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        events: list[DiscoveryEvent] = []
        previous_coins = {key[1] for key in previous}
        for raw in rows:
            coin = canonical_coin(str(raw.get("coin") or raw.get("canonical_coin") or ""))
            venue = _canonical_venue(raw.get("venue") or "")
            symbol = str(raw.get("symbol") or raw.get("exchange_symbol") or "").strip().upper()
            if not coin or not venue or not symbol or raw.get("active") is False:
                continue
            market_type = "perp" if raw.get("perpetual") else str(raw.get("market_type") or "spot")
            settle = _currency(raw.get("settle") or raw.get("settle_currency"))
            key = (scope, coin, venue, symbol, f"{market_type}|{settle or ''}")
            item = dict(raw)
            item.update({"_scope": scope, "coin": coin, "venue": venue, "symbol": symbol})
            current[key] = item
            old = previous.get(key)
            if old is None:
                was_known = (
                    coin in self._markets
                    or coin in previous_coins
                    or any(entry[1] == coin for entry in current if entry != key)
                )
                venue_was_known = any(
                    instrument.active and instrument.venue == venue
                    for instrument in self._markets.get(coin, RegisteredMarket(coin)).instruments.values()
                ) or any(entry[1:3] == (coin, venue) for entry in current if entry != key)
                is_dex_pair = bool(raw.get("dex_pair")) or market_type == "dex"
                events.append(
                    DiscoveryEvent(DiscoveryEventType.NEW_MARKET, coin, venue, symbol, int(observed_at_ms))
                )
                event_type = DiscoveryEventType.NEW_DEX_PAIR if is_dex_pair else DiscoveryEventType.NEW_MARKET
                if is_dex_pair:
                    events.append(DiscoveryEvent(event_type, coin, venue, symbol, int(observed_at_ms)))
                if was_known and not venue_was_known:
                    events.append(
                        DiscoveryEvent(DiscoveryEventType.NEW_VENUE, coin, venue, symbol, int(observed_at_ms))
                    )
                if bool(raw.get("perpetual")) or market_type == "perp":
                    events.append(
                        DiscoveryEvent(DiscoveryEventType.NEW_PERP, coin, venue, symbol, int(observed_at_ms))
                    )
                elif market_type == "spot":
                    events.append(
                        DiscoveryEvent(DiscoveryEventType.NEW_SPOT, coin, venue, symbol, int(observed_at_ms))
                    )
                self._enqueue(
                    coin,
                    event_type.value,
                    int(observed_at_ms),
                    source=str(raw.get("source") or scope),
                    venue=venue,
                )
            elif old.get("active") is False:
                events.append(
                    DiscoveryEvent(DiscoveryEventType.REACTIVATED, coin, venue, symbol, int(observed_at_ms))
                )
                self._enqueue(
                    coin,
                    DiscoveryEventType.REACTIVATED.value,
                    int(observed_at_ms),
                    source=str(raw.get("source") or scope),
                    venue=venue,
                )
            self.register(
                coin,
                venue,
                symbol,
                native=venue in self.native_venues,
                discovery=True,
                active=True,
                market_type=market_type,
                quote=raw.get("quote"),
                settle=settle,
                linear=raw.get("linear"),
                inverse=raw.get("inverse"),
                contract_size=raw.get("contract_size"),
                first_observed_at_ms=observed_at_ms,
                last_observed_at_ms=observed_at_ms,
            )
        for key, old in previous.items():
            if key not in current and old.get("active") is not False:
                _, coin, venue, symbol, type_and_settle = key
                events.append(
                    DiscoveryEvent(
                        DiscoveryEventType.DELISTED, coin, venue, str(old["symbol"]), int(observed_at_ms)
                    )
                )
                current[key] = {**old, "active": False}
                market_type, _, settle = type_and_settle.partition("|")
                instrument_key = _instrument_key(venue, symbol, market_type, settle or None)
                if coin in self._markets and instrument_key in self._markets[coin].instruments:
                    prior = self._markets[coin].instruments[instrument_key]
                    self._markets[coin].instruments[instrument_key] = MarketInstrument(
                        **{**asdict(prior), "active": False, "last_observed_at_ms": int(observed_at_ms)}
                    )
        self._snapshot_active = {
            **{key: value for key, value in self._snapshot_active.items() if key[0] != scope},
            **current,
        }
        return events

    def ingest_dex(self, result: Any, *, observed_at_ms: int) -> list[DiscoveryEvent]:
        """Ingest normalized DEX metadata while preserving failed provider snapshots."""
        events: list[DiscoveryEvent] = []
        candidates = tuple(getattr(result, "candidates", ()))
        for provider in getattr(result, "successful_providers", ()):
            provider_rows = [row for row in candidates if row.source == provider]
            events.extend(
                self.apply_snapshot(
                    (
                        {
                            "coin": row.coin,
                            "venue": row.venue,
                            "symbol": row.pool_id,
                            "market_type": "dex",
                            "dex_pair": True,
                            "quote": row.pair.partition("/")[2] or None,
                            "active": row.active,
                            "source": row.source,
                        }
                        for row in provider_rows
                    ),
                    observed_at_ms=int(observed_at_ms),
                    source=f"dex:{provider}",
                )
            )
            for row in provider_rows:
                market = self.market(row.coin)
                self.update_metrics(
                    row.coin,
                    volume_24h=max(market.volume_24h or 0.0, row.volume_24h_usd),
                    liquidity=max(market.liquidity or 0.0, row.liquidity_usd),
                )
        return events

    def hot_candidates(self, *, now_ms: int) -> list[HotCandidate]:
        self._hot = {coin: item for coin, item in self._hot.items() if item.expires_at_ms >= int(now_ms)}
        return sorted(self._hot.values(), key=lambda item: (item.expires_at_ms, item.coin))

    def _enqueue(self, coin: str, reason: str, now_ms: int, *, source: str = "", venue: str = "") -> None:
        prior = self._hot.get(coin)
        venues = tuple(sorted({*(prior.venues if prior else ()), *([venue] if venue else [])}))
        self._hot[coin] = HotCandidate(
            coin,
            reason,
            now_ms,
            now_ms + self.hot_candidate_ms,
            source,
            venues,
        )

    def dump(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 3,
            "native_venues": sorted(self.native_venues),
            "hot_candidate_ms": self.hot_candidate_ms,
            "markets": {
                coin: {
                    "coin": row.coin,
                    "instruments": {
                        key: {**asdict(item), "status": item.status.value}
                        for key, item in row.instruments.items()
                    },
                    "volume_24h": row.volume_24h,
                    "open_interest": row.open_interest,
                    "liquidity": row.liquidity,
                    "replay_quality": row.replay_quality,
                }
                for coin, row in sorted(self._markets.items())
            },
            "hot_candidates": [asdict(row) for row in self._hot.values()],
            "snapshot_active": list(self._snapshot_active.values()),
            "specialized_sources": {
                key: value.value for key, value in sorted(self._specialized_sources.items())
            },
        }
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)

    @classmethod
    def load(cls, path: str | Path) -> UniversalMarketRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        registry = cls(native_venues=payload.get("native_venues", ()))
        registry.hot_candidate_ms = int(payload.get("hot_candidate_ms", registry.hot_candidate_ms))
        for coin, row in payload.get("markets", {}).items():
            market = RegisteredMarket(
                coin=canonical_coin(coin),
                volume_24h=row.get("volume_24h"),
                open_interest=row.get("open_interest"),
                liquidity=row.get("liquidity"),
                replay_quality=str(row.get("replay_quality") or "UNMEASURABLE"),
            )
            for raw in row.get("instruments", {}).values():
                item = dict(raw)
                item["status"] = AvailabilityStatus(item["status"])
                instrument = MarketInstrument(**item)
                market.instruments[instrument.identity] = instrument
            registry._markets[market.coin] = market
        registry._hot = {
            row["coin"]: HotCandidate(**{**row, "venues": tuple(row.get("venues", ()))})
            for row in payload.get("hot_candidates", [])
        }
        registry._specialized_sources = {
            key: AvailabilityStatus(value) for key, value in payload.get("specialized_sources", {}).items()
        }
        for raw in payload.get("snapshot_active", []):
            item = dict(raw)
            scope = str(item.get("_scope") or "default").strip().lower()
            coin = canonical_coin(item.get("coin", ""))
            venue = _canonical_venue(item.get("venue", ""))
            symbol = str(item.get("symbol") or item.get("exchange_symbol") or "").upper()
            market_type = "perp" if item.get("perpetual") else str(item.get("market_type") or "spot")
            settle = _currency(item.get("settle") or item.get("settle_currency"))
            registry._snapshot_active[(scope, coin, venue, symbol, f"{market_type}|{settle or ''}")] = item
        return registry

    def register_specialized_sources(self) -> None:
        """Expose existing context adapters in this registry without hot-path promotion."""
        from hl_observer.venues.registre_venues import registre

        for venue, capabilities in registre().items():
            if venue in self.native_venues or venue in {"binance", "hyperliquid"}:
                continue
            self._specialized_sources[_canonical_venue(venue)] = (
                AvailabilityStatus.REQUIRES_KEY
                if capabilities.get("pull_live") == "REQUIRES_KEY"
                else AvailabilityStatus.SPECIALIZED
            )


def _canonical_venue(value: object) -> str:
    venue = str(value or "").strip().lower()
    return {
        "binanceusdm": "binance",
        "binancecoinm": "binance",
        "gateio": "gate",
        "krakenfutures": "kraken",
    }.get(venue, venue)


def _currency(value: object) -> str | None:
    cleaned = str(value or "").strip().upper()
    return cleaned or None


def _instrument_key(venue: str, symbol: str, market_type: str, settle: str | None) -> str:
    return "|".join(
        (
            _canonical_venue(venue),
            str(symbol).strip().upper(),
            str(market_type).strip().lower(),
            _currency(settle) or "",
        )
    )


def _earliest(current: int | None, prior: int | None) -> int | None:
    values = [int(value) for value in (current, prior) if value is not None]
    return min(values) if values else None


def _latest(current: int | None, prior: int | None) -> int | None:
    values = [int(value) for value in (current, prior) if value is not None]
    return max(values) if values else None


def _iso_ms(value: object) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _positive(value: float | None) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _scale(value: float | None, unit: float) -> float:
    return min(10.0, (value or 0.0) / unit) if value is not None else 0.0


__all__ = [
    "AvailabilityStatus",
    "CandidateScore",
    "DiscoveryEvent",
    "DiscoveryEventType",
    "HotCandidate",
    "MarketInstrument",
    "RegisteredMarket",
    "UniversalMarketRegistry",
]
