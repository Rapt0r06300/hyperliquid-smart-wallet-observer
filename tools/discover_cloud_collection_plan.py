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


def discover_cloud_universe(
    *,
    min_venues: int = 2,
    max_coins: int = 120,
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
    majors = {"BTC": 0, "ETH": 1, "SOL": 2, "HYPE": 3}
    ranked.sort(
        key=lambda item: (
            -len(item[1]),
            majors.get(item[0], 99),
            item[0],
        )
    )
    if max_coins > 0:
        ranked = ranked[: int(max_coins)]

    rows = [
        {
            "coin": coin,
            "venue_count": len(symbols),
            "symbols": dict(sorted(symbols.items())),
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
        "batches": batches,
        "errors": errors,
        "read_only": True,
        "real_execution": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--min-venues", type=int, default=2)
    parser.add_argument("--max-coins", type=int, default=120)
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
    if plan["selected_coin_count"] <= 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
