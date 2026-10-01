"""Discover the exact multi-venue perpetual universe for cloud collection.

The planner preserves each venue's real exchange symbol. A canonical coin is only a
join key; collectors must never reconstruct venue symbols heuristically.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from hl_observer.collection.bybit_market_data import BybitPublicClient
from hl_observer.collection.bitget_market_data import BitgetPublicClient
from hl_observer.collection.gate_market_data import GatePublicClient
from hl_observer.collection.okx_market_data import OkxPublicClient
from hl_observer.config.cross_venue_instruments import BINANCE_PERP_EXCEPTIONS
from hl_observer.markets.universe import is_exotic_market

HL_INFO_URL = "https://api.hyperliquid.xyz/info"
BINANCE_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_TICKER_24H_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
BYBIT_TICKERS_URL = "https://api.bybit.com/v5/market/tickers"
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
GATE_TICKERS_URL = "https://api.gateio.ws/api/v4/futures/usdt/tickers"
BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"


def _hl_markets(*, timeout_s: float = 15.0) -> dict[str, str]:
    with httpx.Client(timeout=timeout_s) as client:
        response = client.post(HL_INFO_URL, json={"type": "meta"})
        response.raise_for_status()
        payload = response.json()
    universe = payload.get("universe") if isinstance(payload, dict) else None
    result: dict[str, str] = {}
    if not isinstance(universe, list):
        return result
    for row in universe:
        if not isinstance(row, dict):
            continue
        coin = str(row.get("name") or "").strip().upper()
        if not coin or bool(row.get("isDelisted")) or is_exotic_market(coin):
            continue
        result[coin] = coin
    return result


def _binance_reverse_aliases() -> dict[str, str]:
    result: dict[str, str] = {}
    for coin, symbol in BINANCE_PERP_EXCEPTIONS.items():
        if symbol:
            result[str(symbol).upper()] = str(coin).upper()
    return result


def _binance_markets(*, timeout_s: float = 15.0) -> dict[str, str]:
    reverse = _binance_reverse_aliases()
    with httpx.Client(timeout=timeout_s) as client:
        response = client.get(BINANCE_EXCHANGE_INFO_URL)
        response.raise_for_status()
        payload = response.json()
    rows = payload.get("symbols") if isinstance(payload, dict) else None
    result: dict[str, str] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if (
            not symbol
            or str(row.get("contractType") or "").upper() != "PERPETUAL"
            or str(row.get("status") or "").upper() != "TRADING"
            or str(row.get("quoteAsset") or "").upper() != "USDT"
        ):
            continue
        coin = reverse.get(symbol)
        if coin is None:
            coin = str(row.get("baseAsset") or "").strip().upper()
        if not coin or is_exotic_market(coin):
            continue
        result[coin] = symbol
    return result


def _normalize_against_hl(
    rows: list[tuple[str, str]],
    *,
    hl_coins: set[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_coin, symbol in rows:
        coin = str(raw_coin or "").strip().upper()
        if not coin:
            continue
        normalized = coin
        if normalized not in hl_coins and normalized.startswith("1000"):
            candidate = normalized[4:]
            if candidate in hl_coins:
                normalized = candidate
        if is_exotic_market(normalized):
            continue
        result[normalized] = str(symbol).strip().upper()
    return result



def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _liquidity_hints(
    venues: dict[str, dict[str, str]],
    *,
    timeout_s: float = 4.0,
) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    """Best-effort 24h notional hints used only for priority ordering.

    Discovery/selection never depends on these requests. Missing or malformed
    liquidity data therefore cannot remove a coin or stop collection.
    """
    hints: dict[str, dict[str, float]] = defaultdict(dict)
    errors: dict[str, str] = {}

    def record(venue: str, symbol: str, value: Any) -> None:
        notional = _positive_float(value)
        if notional is None:
            return
        reverse = {
            str(exchange_symbol).upper(): coin
            for coin, exchange_symbol in venues.get(venue, {}).items()
        }
        coin = reverse.get(str(symbol or "").upper())
        if coin:
            hints[coin][venue] = notional

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(HL_INFO_URL, json={"type": "metaAndAssetCtxs"})
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, list) and len(payload) >= 2:
            meta, contexts = payload[0], payload[1]
            universe = meta.get("universe") if isinstance(meta, dict) else None
            if isinstance(universe, list) and isinstance(contexts, list):
                for row, ctx in zip(universe, contexts):
                    if not isinstance(row, dict) or not isinstance(ctx, dict):
                        continue
                    record("hyperliquid", str(row.get("name") or ""), ctx.get("dayNtlVlm"))
    except Exception as exc:
        errors["hyperliquid"] = type(exc).__name__

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(BINANCE_TICKER_24H_URL)
            response.raise_for_status()
            payload = response.json()
        for row in payload if isinstance(payload, list) else []:
            if isinstance(row, dict):
                record("binance", str(row.get("symbol") or ""), row.get("quoteVolume"))
    except Exception as exc:
        errors["binance"] = type(exc).__name__

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(BYBIT_TICKERS_URL, params={"category": "linear"})
            response.raise_for_status()
            payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        rows = result.get("list") if isinstance(result, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                record("bybit", str(row.get("symbol") or ""), row.get("turnover24h"))
    except Exception as exc:
        errors["bybit"] = type(exc).__name__

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(OKX_TICKERS_URL, params={"instType": "SWAP"})
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            notional = _positive_float(row.get("volCcyQuote24h"))
            if notional is None:
                volume = _positive_float(row.get("volCcy24h"))
                last = _positive_float(row.get("last"))
                notional = volume * last if volume is not None and last is not None else None
            record("okx", str(row.get("instId") or ""), notional)
    except Exception as exc:
        errors["okx"] = type(exc).__name__

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(GATE_TICKERS_URL)
            response.raise_for_status()
            payload = response.json()
        for row in payload if isinstance(payload, list) else []:
            if not isinstance(row, dict):
                continue
            notional = (
                _positive_float(row.get("volume_24h_usd"))
                or _positive_float(row.get("volume_24h_quote"))
            )
            if notional is None:
                volume = _positive_float(row.get("volume_24h"))
                last = _positive_float(row.get("last"))
                notional = volume * last if volume is not None and last is not None else None
            record("gate", str(row.get("contract") or ""), notional)
    except Exception as exc:
        errors["gate"] = type(exc).__name__

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(BITGET_TICKERS_URL, params={"productType": "USDT-FUTURES"})
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            notional = (
                _positive_float(row.get("usdtVolume"))
                or _positive_float(row.get("quoteVolume"))
                or _positive_float(row.get("turnover24h"))
            )
            if notional is None:
                volume = _positive_float(row.get("baseVolume"))
                last = _positive_float(row.get("lastPr") or row.get("lastPrice"))
                notional = volume * last if volume is not None and last is not None else None
            record("bitget", str(row.get("symbol") or ""), notional)
    except Exception as exc:
        errors["bitget"] = type(exc).__name__

    return {
        coin: dict(sorted(per_venue.items()))
        for coin, per_venue in hints.items()
    }, errors


def _prioritize_without_filtering(
    ranked: list[tuple[str, dict[str, str]]],
    liquidity: dict[str, dict[str, float]],
) -> tuple[list[tuple[str, dict[str, str]]], bool]:
    """Reorder an already frozen selection; never add or remove a coin."""
    available_venues = {
        venue
        for coin, _symbols in ranked
        for venue in liquidity.get(coin, {})
    }
    if len(available_venues) < 2:
        return list(ranked), False
    base_rank = {coin: index for index, (coin, _symbols) in enumerate(ranked)}
    prioritized = sorted(
        ranked,
        key=lambda item: (
            -len(item[1]),
            -len(liquidity.get(item[0], {})),
            -sum(liquidity.get(item[0], {}).values()),
            base_rank[item[0]],
        ),
    )
    return prioritized, True


def discover_cloud_universe(
    *,
    min_venues: int = 2,
    max_coins: int = 0,
    batch_size: int = 8,
) -> dict[str, Any]:
    errors: dict[str, str] = {}
    venues: dict[str, dict[str, str]] = {}

    try:
        venues["hyperliquid"] = _hl_markets()
    except Exception as exc:
        venues["hyperliquid"] = {}
        errors["hyperliquid"] = type(exc).__name__

    hl_coins = set(venues["hyperliquid"])

    try:
        venues["binance"] = _binance_markets()
    except Exception as exc:
        venues["binance"] = {}
        errors["binance"] = type(exc).__name__

    try:
        client = BybitPublicClient()
        venues["bybit"] = _normalize_against_hl(
            client.discover_usdt_perpetuals(),
            hl_coins=hl_coins,
        )
    except Exception as exc:
        venues["bybit"] = {}
        errors["bybit"] = type(exc).__name__

    try:
        client = OkxPublicClient()
        venues["okx"] = _normalize_against_hl(
            client.discover_usdt_perpetuals(),
            hl_coins=hl_coins,
        )
    except Exception as exc:
        venues["okx"] = {}
        errors["okx"] = type(exc).__name__

    try:
        client = GatePublicClient()
        venues["gate"] = _normalize_against_hl(
            client.discover_usdt_perpetuals(),
            hl_coins=hl_coins,
        )
    except Exception as exc:
        venues["gate"] = {}
        errors["gate"] = type(exc).__name__

    try:
        client = BitgetPublicClient()
        venues["bitget"] = _normalize_against_hl(
            client.discover_usdt_perpetuals(),
            hl_coins=hl_coins,
        )
    except Exception as exc:
        venues["bitget"] = {}
        errors["bitget"] = type(exc).__name__

    joined: dict[str, dict[str, str]] = defaultdict(dict)
    for venue, mapping in venues.items():
        for coin, symbol in mapping.items():
            joined[coin][venue] = symbol

    minimum = max(1, int(min_venues))
    ranked = [
        (coin, symbols)
        for coin, symbols in joined.items()
        if len(symbols) >= minimum
    ]
    discovery_only = [
        (coin, symbols)
        for coin, symbols in joined.items()
        if len(symbols) < minimum
    ]
    majors = {"BTC": 0, "ETH": 1, "SOL": 2, "HYPE": 3}
    ranked.sort(
        key=lambda item: (
            -len(item[1]),
            majors.get(item[0], 99),
            item[0],
        )
    )
    discovery_only.sort(key=lambda item: item[0])

    # Freeze the legacy selection set first. Liquidity may only change processing
    # priority inside that exact set, so max_coins can never drop a coin that the
    # previous planner would have selected.
    if max_coins > 0:
        ranked = ranked[: int(max_coins)]
    selected_before_priority = {coin for coin, _symbols in ranked}

    liquidity: dict[str, dict[str, float]] = {}
    liquidity_errors: dict[str, str] = {}
    try:
        liquidity, liquidity_errors = _liquidity_hints(venues)
    except Exception as exc:
        liquidity_errors = {"planner": type(exc).__name__}
    ranked, liquidity_priority_active = _prioritize_without_filtering(ranked, liquidity)
    if {coin for coin, _symbols in ranked} != selected_before_priority:
        raise RuntimeError("liquidity priority changed frozen collection selection")

    rows = [
        {
            "coin": coin,
            "venue_count": len(symbols),
            "symbols": dict(sorted(symbols.items())),
            "liquidity_24h_usd_observed": round(
                sum(liquidity.get(coin, {}).values()), 6
            ),
            "liquidity_venue_count": len(liquidity.get(coin, {})),
            "liquidity_by_venue": dict(sorted(liquidity.get(coin, {}).items())),
        }
        for coin, symbols in ranked
    ]
    size = max(1, int(batch_size))
    batches = [
        {
            "batch_id": f"batch-{index // size:03d}",
            "coins": rows[index:index + size],
        }
        for index in range(0, len(rows), size)
    ]
    return {
        "schema": "alina.cloud_collection_plan.v1",
        "min_venues": minimum,
        "venue_market_counts": {
            venue: len(mapping) for venue, mapping in venues.items()
        },
        "selected_coin_count": len(rows),
        "selected": rows,
        "discovery_only": [
            {
                "coin": coin,
                "venue_count": len(symbols),
                "symbols": dict(sorted(symbols.items())),
                "tier": "C",
            }
            for coin, symbols in discovery_only
        ],
        "batches": batches,
        "priority": {
            "mode": (
                "venue_count_then_24h_notional_liquidity"
                if liquidity_priority_active
                else "legacy_venue_count_fallback"
            ),
            "non_destructive": True,
            "selection_set_preserved": True,
            "liquidity_source_count": len(
                {
                    venue
                    for per_coin in liquidity.values()
                    for venue in per_coin
                }
            ),
        },
        "errors": errors,
        "liquidity_errors": liquidity_errors,
        "read_only": True,
        "real_execution": False,
    }


def _plan_exit_code(plan: dict[str, Any]) -> int:
    """Keep healthy venue collection alive when discovery is partially degraded."""
    return 0 if int(plan.get("selected_coin_count") or 0) > 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--min-venues", type=int, default=2)
    parser.add_argument("--max-coins", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    plan = discover_cloud_universe(
        min_venues=args.min_venues,
        max_coins=args.max_coins,
        batch_size=args.batch_size,
    )
    rendered = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return _plan_exit_code(plan)


if __name__ == "__main__":
    raise SystemExit(main())
