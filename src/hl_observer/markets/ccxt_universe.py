"""Broad public market discovery through CCXT, isolated from native hot paths."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

SOURCE = "CCXT"
DISCOVERY_ONLY = "DISCOVERY_ONLY"
NATIVE_ELIGIBLE = "NATIVE_ELIGIBLE"
DEFAULT_EXCHANGES = (
    "hyperliquid",
    "binanceusdm",
    "bybit",
    "okx",
    "gateio",
    "bitget",
    "kucoinfutures",
    "krakenfutures",
    "coinbase",
    "mexc",
    "htx",
    "cryptocom",
    "phemex",
    "bitmex",
    "deribit",
    "coinex",
)
VENUE_ALIASES = {
    "binanceusdm": "binance",
    "binancecoinm": "binance",
    "gate": "gateio",
    "kucoinfutures": "kucoin",
    "krakenfutures": "kraken",
}
CCXT_EXCHANGE_CLASS_ALIASES = {"gateio": "gate"}
NATIVE_VENUES = frozenset({"hyperliquid", "binance", "bybit", "okx", "gate", "gateio", "bitget"})


class CanonicalCCXTMarket(BaseModel):
    venue: str
    exchange_symbol: str
    canonical_base: str
    quote: str
    market_type: Literal["spot", "perp", "future"]
    active: bool
    linear: bool | None = None
    inverse: bool | None = None
    settle_currency: str | None = None
    contract_size: float | None = None
    discovered_at: str
    source: Literal["CCXT"] = SOURCE
    discovery_status: Literal["NATIVE_ELIGIBLE", "DISCOVERY_ONLY"]

    @property
    def canonical_coin(self) -> str:
        return self.canonical_base

    @property
    def base(self) -> str:
        return self.canonical_base

    @property
    def settle(self) -> str | None:
        return self.settle_currency

    @property
    def spot(self) -> bool:
        return self.market_type == "spot"

    @property
    def perpetual(self) -> bool:
        return self.market_type == "perp"

    @property
    def future(self) -> bool:
        return self.market_type == "future"

    @property
    def identity(self) -> str:
        return f"{self.venue}|{self.exchange_symbol}"


class AggregatedCoin(BaseModel):
    canonical_base: str
    venues: list[str] = Field(default_factory=list)
    venue_count: int = 0
    native_venues: list[str] = Field(default_factory=list)
    discovery_only_venues: list[str] = Field(default_factory=list)
    discovery_status: Literal["NATIVE_ELIGIBLE", "DISCOVERY_ONLY"] = DISCOVERY_ONLY
    hot_path_eligible: bool = False


class VenueDiscoveryStatus(BaseModel):
    status: Literal["OK", "ERROR"]
    markets_discovered: int = 0
    attempts: int = 0
    error: str | None = None
    last_successful_discovery: str | None = None


class CCXTUniverseResult(BaseModel):
    discovered_at: str
    source: Literal["CCXT"] = SOURCE
    markets: list[CanonicalCCXTMarket] = Field(default_factory=list)
    universe: dict[str, AggregatedCoin] = Field(default_factory=dict)
    new_markets: list[CanonicalCCXTMarket] = Field(default_factory=list)
    removed_markets: list[CanonicalCCXTMarket] = Field(default_factory=list)
    new_venues_by_coin: dict[str, list[str]] = Field(default_factory=dict)
    multi_venue_candidates_2: list[str] = Field(default_factory=list)
    multi_venue_candidates_3: list[str] = Field(default_factory=list)
    native_collection_candidates: list[str] = Field(default_factory=list)
    coverage_by_venue: dict[str, int] = Field(default_factory=dict)
    venue_status: dict[str, VenueDiscoveryStatus] = Field(default_factory=dict)
    errors_by_venue: dict[str, str] = Field(default_factory=dict)

    def markets_on_at_least(self, minimum_venues: int) -> list[AggregatedCoin]:
        return [row for row in self.universe.values() if row.venue_count >= minimum_venues]

    def native_candidate_coins(self, minimum_native_venues: int = 1) -> list[str]:
        """Coins allowed to proceed to native collection, never CCXT market data."""
        if minimum_native_venues <= 1:
            return list(self.native_collection_candidates)
        return [
            coin
            for coin, row in self.universe.items()
            if len(row.native_venues) >= max(1, int(minimum_native_venues))
        ]


class CCXTUniverseScout:
    """Discover public markets broadly while keeping native collectors authoritative."""

    def __init__(
        self,
        *,
        exchanges: list[str] | tuple[str, ...] = DEFAULT_EXCHANGES,
        exchange_factory: Callable[[str], Any] | None = None,
        snapshot_path: str | Path = "data/ccxt_universe.json",
        timeout_seconds: float = 10.0,
        max_attempts: int = 2,
        include_spot: bool = False,
        native_venues: set[str] | frozenset[str] = NATIVE_VENUES,
    ) -> None:
        self.exchanges = tuple(
            dict.fromkeys(str(item).strip().lower() for item in exchanges if str(item).strip())
        )[:25]
        self.timeout_seconds = min(60.0, max(0.1, float(timeout_seconds)))
        self.max_attempts = min(3, max(1, int(max_attempts)))
        self.include_spot = bool(include_spot)
        self.snapshot_path = Path(snapshot_path)
        self.native_venues = frozenset(_canonical_venue(item) for item in native_venues)
        self.exchange_factory = exchange_factory or self._default_exchange_factory

    async def scan(self) -> CCXTUniverseResult:
        discovered_at = datetime.now(UTC).isoformat()
        previous = self._load_snapshot()
        rows = await asyncio.gather(*(self._scan_venue(exchange_id, discovered_at) for exchange_id in self.exchanges))
        markets: list[CanonicalCCXTMarket] = []
        statuses: dict[str, VenueDiscoveryStatus] = {}
        successful_venues: set[str] = set()
        for venue, venue_markets, status in rows:
            statuses[venue] = status
            markets.extend(venue_markets)
            if status.status == "OK":
                successful_venues.add(venue)
        markets = _deduplicate(markets)
        previous_markets = _snapshot_markets(previous)
        previous_by_id = {item.identity: item for item in previous_markets}
        current_by_id = {item.identity: item for item in markets}
        new_markets = sorted(
            (item for key, item in current_by_id.items() if key not in previous_by_id),
            key=_market_sort_key,
        )
        removed_markets = sorted(
            (
                item
                for key, item in previous_by_id.items()
                if item.venue in successful_venues and key not in current_by_id
            ),
            key=_market_sort_key,
        )
        universe = _aggregate(markets, self.native_venues)
        previous_venues = _venues_by_coin(previous_markets)
        new_venues_by_coin = {
            coin: sorted(set(row.venues) - previous_venues.get(coin, set()))
            for coin, row in universe.items()
            if coin in previous_venues
            and set(row.venues) - previous_venues.get(coin, set())
        }
        result = CCXTUniverseResult(
            discovered_at=discovered_at,
            markets=markets,
            universe=universe,
            new_markets=new_markets,
            removed_markets=removed_markets,
            new_venues_by_coin=new_venues_by_coin,
            multi_venue_candidates_2=[coin for coin, row in universe.items() if row.venue_count >= 2],
            multi_venue_candidates_3=[coin for coin, row in universe.items() if row.venue_count >= 3],
            native_collection_candidates=[coin for coin, row in universe.items() if row.native_venues],
            coverage_by_venue={venue: status.markets_discovered for venue, status in statuses.items()},
            venue_status=statuses,
            errors_by_venue={venue: status.error or "unknown error" for venue, status in statuses.items() if status.status == "ERROR"},
        )
        if successful_venues:
            preserved = [item for item in previous_markets if item.venue not in successful_venues]
            self._write_snapshot(result, _deduplicate([*markets, *preserved]))
        return result

    async def _scan_venue(
        self, exchange_id: str, discovered_at: str
    ) -> tuple[str, list[CanonicalCCXTMarket], VenueDiscoveryStatus]:
        venue = _canonical_venue(exchange_id)
        last_error = "unavailable"
        for attempt in range(1, self.max_attempts + 1):
            client: Any | None = None
            try:
                client = self.exchange_factory(exchange_id)
                raw = await asyncio.wait_for(
                    asyncio.to_thread(client.load_markets), timeout=self.timeout_seconds
                )
                if not isinstance(raw, Mapping):
                    raise TypeError("load_markets returned a non-mapping payload")
                markets = [
                    normalized
                    for market in raw.values()
                    if isinstance(market, Mapping)
                    and (normalized := self._normalize_market(venue, market, discovered_at)) is not None
                ]
                markets = _deduplicate(markets)
                return venue, markets, VenueDiscoveryStatus(
                    status="OK",
                    markets_discovered=len(markets),
                    attempts=attempt,
                    last_successful_discovery=discovered_at,
                )
            except Exception as exc:  # noqa: BLE001 - each external venue is an isolation boundary.
                last_error = f"{type(exc).__name__}: {exc}"[:300]
            finally:
                if client is not None:
                    await _close_client(client)
        previous_success = _previous_success(self._load_snapshot(), venue)
        return venue, [], VenueDiscoveryStatus(
            status="ERROR",
            attempts=self.max_attempts,
            error=last_error,
            last_successful_discovery=previous_success,
        )

    def _normalize_market(
        self, venue: str, market: Mapping[str, Any], discovered_at: str
    ) -> CanonicalCCXTMarket | None:
        market_type = _market_type(market)
        if market_type is None or (market_type == "spot" and not self.include_spot):
            return None
        base = _clean_currency(market.get("base"))
        quote = _clean_currency(market.get("quote"))
        symbol = str(market.get("symbol") or market.get("id") or "").strip().upper()
        if not base or not quote or not symbol:
            return None
        native = venue in self.native_venues
        return CanonicalCCXTMarket(
            venue=venue,
            exchange_symbol=symbol,
            canonical_base=base,
            quote=quote,
            market_type=market_type,
            active=market.get("active") is not False,
            linear=_optional_bool(market.get("linear")),
            inverse=_optional_bool(market.get("inverse")),
            settle_currency=_clean_currency(market.get("settle")) or None,
            contract_size=_optional_positive_float(market.get("contractSize")),
            discovered_at=discovered_at,
            discovery_status=NATIVE_ELIGIBLE if native else DISCOVERY_ONLY,
        )

    def _default_exchange_factory(self, exchange_id: str) -> Any:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("CCXT is required: install project dependencies") from exc
        class_id = CCXT_EXCHANGE_CLASS_ALIASES.get(exchange_id, exchange_id)
        exchange_class = getattr(ccxt, class_id, None)
        if exchange_class is None:
            raise ValueError(f"unsupported CCXT exchange: {exchange_id}")
        return exchange_class({"enableRateLimit": True, "timeout": int(self.timeout_seconds * 1_000)})

    def _load_snapshot(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_snapshot(
        self, result: CCXTUniverseResult, snapshot_markets: list[CanonicalCCXTMarket]
    ) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.model_dump(mode="json")
        payload["markets"] = [item.model_dump(mode="json") for item in snapshot_markets]
        temporary = self.snapshot_path.with_suffix(self.snapshot_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.snapshot_path)


def _canonical_venue(value: object) -> str:
    venue = str(value or "").strip().lower()
    return VENUE_ALIASES.get(venue, venue)


def _clean_currency(value: object) -> str:
    return str(value or "").strip().upper()


def _market_type(market: Mapping[str, Any]) -> Literal["spot", "perp", "future"] | None:
    if market.get("swap") is True or str(market.get("type", "")).lower() == "swap":
        return "perp"
    if market.get("future") is True or str(market.get("type", "")).lower() == "future":
        return "future"
    if market.get("spot") is True or str(market.get("type", "")).lower() == "spot":
        return "spot"
    return None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_positive_float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _deduplicate(markets: list[CanonicalCCXTMarket]) -> list[CanonicalCCXTMarket]:
    unique = {item.identity: item for item in markets}
    return sorted(unique.values(), key=_market_sort_key)


def _market_sort_key(item: CanonicalCCXTMarket) -> tuple[str, str, str]:
    return item.canonical_base, item.venue, item.exchange_symbol


def _venues_by_coin(markets: list[CanonicalCCXTMarket]) -> dict[str, set[str]]:
    output: dict[str, set[str]] = {}
    for market in markets:
        output.setdefault(market.canonical_base, set()).add(market.venue)
    return output


def _aggregate(
    markets: list[CanonicalCCXTMarket], native_venues: frozenset[str]
) -> dict[str, AggregatedCoin]:
    venues_by_coin = _venues_by_coin([market for market in markets if market.active])
    output: dict[str, AggregatedCoin] = {}
    for coin in sorted(venues_by_coin):
        venues = sorted(venues_by_coin[coin])
        native = sorted(set(venues) & native_venues)
        discovery_only = sorted(set(venues) - native_venues)
        output[coin] = AggregatedCoin(
            canonical_base=coin,
            venues=venues,
            venue_count=len(venues),
            native_venues=native,
            discovery_only_venues=discovery_only,
            discovery_status=NATIVE_ELIGIBLE if native else DISCOVERY_ONLY,
            hot_path_eligible=len(native) >= 2,
        )
    return output


def _snapshot_markets(snapshot: Mapping[str, Any]) -> list[CanonicalCCXTMarket]:
    rows = snapshot.get("markets", [])
    if not isinstance(rows, list):
        return []
    output: list[CanonicalCCXTMarket] = []
    for row in rows:
        try:
            output.append(CanonicalCCXTMarket.model_validate(row))
        except (TypeError, ValueError):
            continue
    return _deduplicate(output)


def _previous_success(snapshot: Mapping[str, Any], venue: str) -> str | None:
    statuses = snapshot.get("venue_status", {})
    if not isinstance(statuses, Mapping) or not isinstance(statuses.get(venue), Mapping):
        return None
    value = statuses[venue].get("last_successful_discovery")
    return str(value) if value else None


def load_native_collection_candidates(snapshot_path: str | Path) -> list[str]:
    """Load only approved coin names from a scout snapshot; ignore all CCXT prices/data."""
    try:
        payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    rows = payload.get("native_collection_candidates", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return sorted({_clean_currency(item) for item in rows if _clean_currency(item)})


async def _close_client(client: Any) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


__all__ = [
    "AggregatedCoin",
    "CCXTUniverseResult",
    "CCXTUniverseScout",
    "CanonicalCCXTMarket",
    "DEFAULT_EXCHANGES",
    "DISCOVERY_ONLY",
    "NATIVE_ELIGIBLE",
    "NATIVE_VENUES",
    "VenueDiscoveryStatus",
    "load_native_collection_candidates",
]
