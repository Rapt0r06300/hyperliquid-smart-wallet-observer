"""Runtime coordinator for native Bybit/OKX public market data.

The coordinator is intentionally read-only.  It discovers public perpetual markets,
routes public websocket messages into deterministic venue states, and exposes one
freshness-gated store to Cross-Venue and Lead-Lag.  Existing Hyperliquid/Binance
collectors can feed the same store through :meth:`ingest_external_bbo` without any
execution capability.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.arbitrage.cross_source_comparator import (
    CrossSourceDiscrepancy,
    compare_cross_source_prices,
)
from hl_observer.collection.bybit_market_data import BybitMarketState, BybitPublicClient
from hl_observer.collection.bitget_market_data import BitgetMarketState, BitgetPublicClient
from hl_observer.collection.coin_universe import note_coins
from hl_observer.collection.gate_market_data import GateMarketState, GatePublicClient
from hl_observer.collection.native_venue_market import MultiVenueMarketStore, NativeMarketSnapshot
from hl_observer.collection.okx_market_data import OkxMarketState, OkxPublicClient
from hl_observer.markets.ccxt_universe import load_native_collection_candidates

SCHEMA_VERSION = "alina.native_venue_coordinator.v1"


class NativeVenueCoordinator:
    """Unify public market data from HL, Binance, Bybit and OKX.

    Bybit and OKX are collected natively here. Hyperliquid/Binance remain owned by
    their existing collectors and can publish their BBO into this coordinator with
    ``ingest_external_bbo``. All strategy-facing reads are fail-closed on freshness.
    """

    def __init__(
        self,
        *,
        bybit_client: Any | None = None,
        okx_client: Any | None = None,
        gate_client: Any | None = None,
        bitget_client: Any | None = None,
        stale_after_ms: int = 1_000,
        max_symbols_per_venue: int = 100,
        ccxt_snapshot_path: str | Path | None = "data/ccxt_universe.json",
    ) -> None:
        self.stale_after_ms = int(stale_after_ms)
        self.max_symbols_per_venue = max(1, int(max_symbols_per_venue))
        self.bybit_client = bybit_client or BybitPublicClient()
        self.okx_client = okx_client or OkxPublicClient()
        self.gate_client = gate_client or GatePublicClient()
        self.bitget_client = bitget_client or BitgetPublicClient()
        self.store = MultiVenueMarketStore(stale_after_ms=self.stale_after_ms)
        self.registry: dict[str, dict[str, str]] = {}
        self._bybit_states: dict[str, BybitMarketState] = {}
        self._okx_states: dict[str, OkxMarketState] = {}
        self._gate_states: dict[str, GateMarketState] = {}
        self._bitget_states: dict[str, BitgetMarketState] = {}
        self._clock_sync: dict[str, dict[str, float | int | str]] = {}
        self.ccxt_snapshot_path = Path(ccxt_snapshot_path) if ccxt_snapshot_path else None
        self._ccxt_priority = set(
            load_native_collection_candidates(self.ccxt_snapshot_path)
            if self.ccxt_snapshot_path
            else []
        )

    def discover(self, *, now_s: float | None = None) -> dict[str, dict[str, str]]:
        """Discover live USDT perpetuals from both public REST APIs.

        Failure of one venue does not fabricate markets from that venue. If a venue
        fails, discoveries from the other venue remain available.
        """
        if self.ccxt_snapshot_path:
            self._ccxt_priority = set(
                load_native_collection_candidates(self.ccxt_snapshot_path)
            )
        discovered: dict[str, dict[str, str]] = {}
        for venue, client in (("bybit", self.bybit_client), ("okx", self.okx_client), ("gate", self.gate_client), ("bitget", self.bitget_client)):
            try:
                rows = client.discover_usdt_perpetuals()
            except Exception:
                rows = []
            for coin, exchange_symbol in rows:
                base = str(coin or "").strip().upper()
                symbol = str(exchange_symbol or "").strip().upper()
                if base and symbol:
                    discovered.setdefault(base, {})[venue] = symbol
        self.registry = dict(sorted(discovered.items()))
        note_coins(self.registry.keys(), now_s=time.time() if now_s is None else now_s)
        return {coin: dict(venues) for coin, venues in self.registry.items()}

    def refresh_clock_sync(self) -> dict[str, dict[str, float | int | str]]:
        """Measure public venue clocks and retain RTT/offset evidence."""
        samples: dict[str, dict[str, float | int | str]] = {}
        for venue, client in (("bybit", self.bybit_client), ("okx", self.okx_client)):
            measure = getattr(client, "measure_clock_sync", None)
            if not callable(measure):
                continue
            try:
                sample = measure()
            except Exception as exc:
                samples[venue] = {"status": "UNAVAILABLE", "error": type(exc).__name__}
                continue
            row = sample.as_dict() if hasattr(sample, "as_dict") else dict(sample)
            row["status"] = "OK"
            samples[venue] = row
        self._clock_sync = samples
        return {venue: dict(row) for venue, row in samples.items()}

    def _with_clock_sync(self, payload: Mapping[str, object], venue: str) -> dict[str, object]:
        message = dict(payload)
        sync = self._clock_sync.get(venue)
        if not sync or sync.get("status") != "OK":
            return message
        meta = message.get("_alina_transport")
        transport = dict(meta) if isinstance(meta, Mapping) else {}
        transport["clock_offset_ms"] = sync.get("offset_ms")
        transport["clock_probe_rtt_ms"] = sync.get("rtt_ms")
        message["_alina_transport"] = transport
        return message

    def symbols_for(self, venue: str) -> list[str]:
        venue_key = str(venue).strip().lower()
        # Prefer assets visible on multiple venues; then fill remaining capacity.
        ranked = sorted(
            self.registry.items(),
            key=lambda item: (item[0] not in self._ccxt_priority, -len(item[1]), item[0]),
        )
        symbols = [venues[venue_key] for _coin, venues in ranked if venue_key in venues]
        return symbols[: self.max_symbols_per_venue]

    def ingest_external_bbo(
        self,
        *,
        venue: str,
        coin: str,
        exchange_symbol: str,
        bid: float,
        ask: float,
        exchange_ts_ms: int,
        receive_ts_ms: int,
        now_ms: int | None = None,
    ) -> NativeMarketSnapshot:
        """Normalize an existing read-only Hyperliquid/Binance BBO into the store."""
        snapshot = NativeMarketSnapshot.build(
            venue=venue,
            coin=coin,
            exchange_symbol=exchange_symbol,
            bid=bid,
            ask=ask,
            exchange_ts_ms=exchange_ts_ms,
            receive_ts_ms=receive_ts_ms,
            now_ms=now_ms,
            stale_after_ms=self.stale_after_ms,
        )
        self.store.put(snapshot)
        return snapshot

    def ingest_bybit(
        self,
        payload: Mapping[str, object],
        *,
        receive_ts_ms: int | None = None,
        now_ms: int | None = None,
    ) -> NativeMarketSnapshot | None:
        message = dict(payload)
        symbol = _bybit_symbol(message)
        if not symbol:
            return None
        state = self._bybit_states.setdefault(
            symbol,
            BybitMarketState(symbol=symbol, stale_after_ms=self.stale_after_ms),
        )
        topic = str(message.get("topic") or "")
        if topic.startswith("orderbook.") or str(message.get("type") or "") == "snapshot":
            state.apply_orderbook(message, receive_ts_ms=receive_ts_ms)
        elif topic.startswith("tickers.") or _looks_like_bybit_ticker(message):
            state.apply_ticker(message, receive_ts_ms=receive_ts_ms)
        else:
            return None
        snapshot = state.snapshot(now_ms=now_ms)
        self.store.put(snapshot)
        return snapshot

    def ingest_okx(
        self,
        payload: Mapping[str, object],
        *,
        receive_ts_ms: int | None = None,
        now_ms: int | None = None,
    ) -> NativeMarketSnapshot | None:
        message = dict(payload)
        inst_id = _okx_inst_id(message)
        if not inst_id:
            return None
        state = self._okx_states.setdefault(
            inst_id,
            OkxMarketState(inst_id=inst_id, stale_after_ms=self.stale_after_ms),
        )
        state.apply(message, receive_ts_ms=receive_ts_ms)
        snapshot = state.snapshot(now_ms=now_ms)
        self.store.put(snapshot)
        return snapshot

    def ingest_gate(self, payload: Mapping[str, object], *, receive_ts_ms: int | None = None, now_ms: int | None = None) -> NativeMarketSnapshot | None:
        data = payload.get("result") if isinstance(payload.get("result"), Mapping) else payload
        contract = str((data if isinstance(data, Mapping) else {}).get("contract") or (data if isinstance(data, Mapping) else {}).get("s") or "").upper()
        if not contract: return None
        state = self._gate_states.setdefault(contract, GateMarketState(contract=contract, stale_after_ms=self.stale_after_ms))
        channel = str(payload.get("channel") or payload.get("event") or "").lower()
        (state.apply_ticker(dict(data)) if "ticker" in channel else state.apply_book(dict(data), receive_ts_ms=receive_ts_ms))
        snapshot = state.snapshot(now_ms=now_ms); self.store.put(snapshot); return snapshot

    def ingest_bitget(self, payload: Mapping[str, object], *, receive_ts_ms: int | None = None, now_ms: int | None = None) -> NativeMarketSnapshot | None:
        arg = payload.get("arg") or {}; symbol = str(arg.get("instId") if isinstance(arg, Mapping) else "").upper()
        if not symbol: return None
        state = self._bitget_states.setdefault(symbol, BitgetMarketState(symbol=symbol, stale_after_ms=self.stale_after_ms))
        state.apply(dict(payload), receive_ts_ms=receive_ts_ms); snapshot = state.snapshot(now_ms=now_ms); self.store.put(snapshot); return snapshot

    def candidate_coins(self, *, now_ms: int, min_venues: int = 2) -> list[str]:
        return self.store.candidate_coins(now_ms=now_ms, min_venues=min_venues)

    def cross_venue_rows(self, coin: str, *, now_ms: int) -> list[CrossSourceDiscrepancy]:
        return compare_cross_source_prices(self.store.cross_source_prices(coin, now_ms=now_ms))

    def lead_lag_rows(self, coin: str, *, now_ms: int) -> list[dict[str, float | int | str]]:
        return self.store.lead_lag_rows(coin, now_ms=now_ms)

    def health(self, *, now_ms: int | None = None) -> dict[str, object]:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        candidates = self.candidate_coins(now_ms=now, min_venues=2)
        return {
            "schema": SCHEMA_VERSION,
            "registry_coins": len(self.registry),
            "bybit_symbols": len(self.symbols_for("bybit")),
            "okx_symbols": len(self.symbols_for("okx")),
            "gate_symbols": len(self.symbols_for("gate")),
            "bitget_symbols": len(self.symbols_for("bitget")),
            "candidate_coins_2plus_venues": candidates,
            "ccxt_native_candidates_prioritized": len(self._ccxt_priority),
            "clock_sync": {venue: dict(row) for venue, row in self._clock_sync.items()},
            "real_execution": False,
        }

    async def run_bybit(self) -> None:
        symbols = self.symbols_for("bybit")
        if not symbols:
            return
        async for payload in self.bybit_client.messages(symbols):
            now = int(time.time() * 1000)
            self.ingest_bybit(self._with_clock_sync(payload, "bybit"), now_ms=now)

    async def run_okx(self) -> None:
        symbols = self.symbols_for("okx")
        if not symbols:
            return
        async for payload in self.okx_client.messages(symbols):
            now = int(time.time() * 1000)
            self.ingest_okx(self._with_clock_sync(payload, "okx"), now_ms=now)

    async def run_gate(self) -> None:
        symbols = self.symbols_for("gate")
        if not symbols: return
        async for payload in self.gate_client.messages(symbols):
            now = int(time.time() * 1000); self.ingest_gate(payload, receive_ts_ms=now, now_ms=now)

    async def run_bitget(self) -> None:
        symbols = self.symbols_for("bitget")
        if not symbols: return
        async for payload in self.bitget_client.messages(symbols):
            now = int(time.time() * 1000); self.ingest_bitget(payload, receive_ts_ms=now, now_ms=now)

    async def run(self, *, discover_first: bool = True) -> None:
        """Run both native public collectors until cancelled."""
        if discover_first or not self.registry:
            await asyncio.to_thread(self.discover)
        await asyncio.to_thread(self.refresh_clock_sync)
        await asyncio.gather(self.run_bybit(), self.run_okx(), self.run_gate(), self.run_bitget())


def _bybit_symbol(payload: Mapping[str, object]) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        symbol = str(data.get("s") or data.get("symbol") or "").upper()
        if symbol:
            return symbol
    if isinstance(data, list) and data and isinstance(data[0], dict):
        symbol = str(data[0].get("symbol") or data[0].get("s") or "").upper()
        if symbol:
            return symbol
    topic = str(payload.get("topic") or "")
    return topic.rsplit(".", 1)[-1].upper() if "." in topic else ""


def _looks_like_bybit_ticker(payload: Mapping[str, object]) -> bool:
    data = payload.get("data")
    item: Mapping[str, object] | None = None
    if isinstance(data, dict):
        item = data
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        item = data[0]
    return bool(item and any(key in item for key in ("lastPrice", "markPrice", "fundingRate")))


def _okx_inst_id(payload: Mapping[str, object]) -> str:
    arg = payload.get("arg")
    if isinstance(arg, dict):
        value = str(arg.get("instId") or "").upper()
        if value:
            return value
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get("instId") or "").upper()
    return ""


__all__ = ["NativeVenueCoordinator", "SCHEMA_VERSION"]
