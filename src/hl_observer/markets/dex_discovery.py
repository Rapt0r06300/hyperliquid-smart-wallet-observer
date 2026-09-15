"""Small public DEX discovery radar; metadata only, never an execution path."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.request import Request, urlopen

_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}$")


@dataclass(frozen=True, slots=True)
class DexCandidate:
    coin: str
    source: str
    chain: str
    venue: str
    pair: str
    pool_id: str
    pool_url: str | None
    price_usd: float | None
    liquidity_usd: float
    volume_24h_usd: float
    transactions_24h: int | None
    pair_created_at_ms: int | None
    observed_at_ms: int
    active: bool = True


@dataclass(frozen=True, slots=True)
class DexDiscoveryResult:
    candidates: tuple[DexCandidate, ...]
    successful_providers: tuple[str, ...]
    errors_by_provider: dict[str, str]


class DexDiscoveryProvider(Protocol):
    name: str

    def discover(self, *, now_ms: int) -> Sequence[DexCandidate]: ...


class GeckoTerminalProvider:
    """Discover recent public pools through GeckoTerminal's unauthenticated API."""

    name = "geckoterminal"

    def __init__(
        self,
        *,
        networks: Iterable[str] = ("eth", "solana", "base"),
        fetch_json: Callable[[str], Mapping[str, Any]] | None = None,
        min_liquidity_usd: float = 25_000,
        min_volume_24h_usd: float = 10_000,
        max_pair_age_hours: int = 168,
    ) -> None:
        self.networks = tuple(dict.fromkeys(str(network).strip().lower() for network in networks))
        self.fetch_json = fetch_json or _fetch_json
        self.min_liquidity_usd = max(0.0, float(min_liquidity_usd))
        self.min_volume_24h_usd = max(0.0, float(min_volume_24h_usd))
        self.max_pair_age_ms = max(1, int(max_pair_age_hours)) * 3_600_000
        self.errors_by_network: dict[str, str] = {}

    def discover(self, *, now_ms: int) -> list[DexCandidate]:
        rows: list[DexCandidate] = []
        self.errors_by_network = {}
        successful_networks = 0
        for network in self.networks:
            try:
                payload = self.fetch_json(
                    "https://api.geckoterminal.com/api/v2/"
                    f"networks/{network}/new_pools?include=base_token,quote_token,dex&page=1"
                )
                rows.extend(self._normalize(payload, network=network, now_ms=int(now_ms)))
                successful_networks += 1
            except Exception as exc:  # providers are deliberately isolated
                self.errors_by_network[network] = str(exc)
        if self.networks and successful_networks == 0:
            details = "; ".join(f"{key}: {value}" for key, value in self.errors_by_network.items())
            raise RuntimeError(details or "all GeckoTerminal networks failed")
        return sorted(rows, key=lambda row: (row.chain, row.venue, row.pool_id))

    def _normalize(self, payload: Mapping[str, Any], *, network: str, now_ms: int) -> list[DexCandidate]:
        included = {
            (str(item.get("type") or ""), str(item.get("id") or "")): item
            for item in payload.get("included", ())
            if isinstance(item, Mapping)
        }
        rows: list[DexCandidate] = []
        for raw in payload.get("data", ()):
            if not isinstance(raw, Mapping):
                continue
            attributes = raw.get("attributes")
            relationships = raw.get("relationships")
            if not isinstance(attributes, Mapping) or not isinstance(relationships, Mapping):
                continue
            base_id = _relationship_id(relationships, "base_token")
            quote_id = _relationship_id(relationships, "quote_token")
            dex_id = _relationship_id(relationships, "dex")
            base = _included_symbol(included, "token", base_id)
            quote = _included_symbol(included, "token", quote_id)
            if not base or not quote or not _SYMBOL.fullmatch(base):
                continue
            liquidity = _number(attributes.get("reserve_in_usd"))
            volume = _nested_number(attributes, "volume_usd", "h24")
            created_at_ms = _iso_ms(attributes.get("pool_created_at"))
            if liquidity is None or liquidity < self.min_liquidity_usd:
                continue
            if volume is None or volume < self.min_volume_24h_usd:
                continue
            if created_at_ms is not None and not 0 <= now_ms - created_at_ms <= self.max_pair_age_ms:
                continue
            buys = _nested_number(attributes, "transactions", "h24", "buys")
            sells = _nested_number(attributes, "transactions", "h24", "sells")
            transactions = int((buys or 0) + (sells or 0)) if buys is not None or sells is not None else None
            pool_id = str(raw.get("id") or attributes.get("address") or "").strip()
            if not pool_id:
                continue
            venue = dex_id or "unknown_dex"
            address = str(attributes.get("address") or "").strip()
            rows.append(
                DexCandidate(
                    coin=base,
                    source=self.name,
                    chain=network,
                    venue=venue.lower(),
                    pair=f"{base}/{quote}",
                    pool_id=pool_id,
                    pool_url=(
                        f"https://www.geckoterminal.com/{network}/pools/{address}" if address else None
                    ),
                    price_usd=_number(attributes.get("base_token_price_usd")),
                    liquidity_usd=liquidity,
                    volume_24h_usd=volume,
                    transactions_24h=transactions,
                    pair_created_at_ms=created_at_ms,
                    observed_at_ms=now_ms,
                )
            )
        return rows


class DexDiscoveryRadar:
    def __init__(self, providers: Iterable[DexDiscoveryProvider]) -> None:
        self.providers = tuple(providers)

    def discover(self, *, now_ms: int) -> DexDiscoveryResult:
        candidates: list[DexCandidate] = []
        successful: list[str] = []
        errors: dict[str, str] = {}
        for provider in self.providers:
            try:
                candidates.extend(provider.discover(now_ms=int(now_ms)))
                successful.append(provider.name)
            except Exception as exc:
                errors[provider.name] = str(exc)
        unique = {(row.source, row.chain, row.pool_id): row for row in candidates}
        return DexDiscoveryResult(
            candidates=tuple(sorted(unique.values(), key=lambda row: (row.source, row.chain, row.pool_id))),
            successful_providers=tuple(sorted(set(successful))),
            errors_by_provider=errors,
        )


def _fetch_json(url: str) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "AlinaSmartFlow/1"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed public provider URL
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("GeckoTerminal response is not an object")
    return payload


def _relationship_id(relationships: Mapping[str, Any], name: str) -> str:
    relation = relationships.get(name)
    if not isinstance(relation, Mapping) or not isinstance(relation.get("data"), Mapping):
        return ""
    return str(relation["data"].get("id") or "").strip()


def _included_symbol(
    included: Mapping[tuple[str, str], Mapping[str, Any]], item_type: str, item_id: str
) -> str:
    item = included.get((item_type, item_id), {})
    attributes = item.get("attributes", {})
    if not isinstance(attributes, Mapping):
        return ""
    return str(attributes.get("symbol") or "").strip().upper()


def _nested_number(value: Mapping[str, Any], *path: str) -> float | None:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return _number(current)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _iso_ms(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


__all__ = [
    "DexCandidate",
    "DexDiscoveryProvider",
    "DexDiscoveryRadar",
    "DexDiscoveryResult",
    "GeckoTerminalProvider",
]
