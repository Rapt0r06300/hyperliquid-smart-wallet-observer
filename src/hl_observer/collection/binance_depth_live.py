"""Live public Binance USD-M deep-L2 collector.

Implements the official snapshot + diff-depth reconstruction protocol without any
authenticated/account endpoint. WebSocket frames are stamped at receipt with wall and
monotonic clocks, persisted as replayable TickEnvelope evidence, and reconstructed by
BinanceDepthOrchestrator. A reconnect or continuity break always requires a new REST
snapshot before the book becomes exploitable again.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import httpx
import websockets

from hl_observer.collection.binance_depth_orchestrator import (
    BUFFERISE,
    BinanceDepthOrchestrator,
)
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

REST_BASE_URL = "https://fapi.binance.com"
WS_BASE_URL = "wss://fstream.binance.com/public/stream"
SCHEMA_VERSION = "alina.binance_usdm_l2_live.v1"


def parse_depth_frame(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize a USD-M diff-depth frame, including combined-stream wrappers."""
    raw = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(raw, Mapping) or str(raw.get("e") or "") != "depthUpdate":
        return None
    symbol = str(raw.get("s") or "").strip().upper()
    try:
        first = int(raw["U"])
        last = int(raw["u"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not symbol or first <= 0 or last < first:
        return None
    previous = _int_or_none(raw.get("pu"))
    bids = raw.get("b") if isinstance(raw.get("b"), list) else []
    asks = raw.get("a") if isinstance(raw.get("a"), list) else []
    return {
        "symbol": symbol,
        "U": first,
        "u": last,
        "pu": previous,
        "bids": bids,
        "asks": asks,
        "event_ts_ms": _int_or_none(raw.get("E")),
        "transaction_ts_ms": _int_or_none(raw.get("T")),
        "raw": dict(raw),
    }


class BinanceDepthLiveCollector:
    """Collect and reconstruct public USD-M L2 for many symbols on one WS."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        rest_base_url: str = REST_BASE_URL,
        ws_base_url: str = WS_BASE_URL,
        snapshot_limit: int = 1000,
        publication_depth: int = 200,
        http_client: httpx.AsyncClient | None = None,
        tick_sink: Callable[[TickEnvelope], Any] | None = None,
        publication_sink: Callable[[str, Mapping[str, Any]], Any] | None = None,
    ) -> None:
        self.symbols = tuple(
            sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        )
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_base_url = ws_base_url.rstrip("/")
        self.snapshot_limit = int(snapshot_limit)
        if self.snapshot_limit not in {5, 10, 20, 50, 100, 500, 1000}:
            raise ValueError("unsupported Binance snapshot_limit")
        self.publication_depth = max(1, min(int(publication_depth), self.snapshot_limit))
        self._owns_http = http_client is None
        self.http = http_client or httpx.AsyncClient(
            base_url=self.rest_base_url,
            timeout=10.0,
        )
        self.tick_sink = tick_sink
        self.publication_sink = publication_sink
        self.states = {
            symbol: BinanceDepthOrchestrator(futures=True)
            for symbol in self.symbols
        }
        self._resync_pending: set[str] = set()
        self.frames_received = 0
        self.snapshots_received = 0
        self.resync_failures = 0
        self.publications = 0
        self.reconnects = 0
        self.last_error = ""

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    def websocket_url(self) -> str:
        streams = "/".join(f"{symbol.lower()}@depth@100ms" for symbol in self.symbols)
        return f"{self.ws_base_url}?streams={streams}"

    def state(self, symbol: str) -> BinanceDepthOrchestrator:
        key = str(symbol).strip().upper()
        if key not in self.states:
            raise KeyError(key)
        return self.states[key]

    async def resync_symbol(self, symbol: str, *, connection_id: str) -> dict[str, Any] | None:
        """Fetch one public REST snapshot and replay all already-buffered WS diffs."""
        key = str(symbol).strip().upper()
        state = self.states.get(key)
        if state is None:
            return None
        send_wall_ms = int(time.time() * 1_000)
        try:
            response = await self.http.get(
                "/fapi/v1/depth",
                params={"symbol": key, "limit": self.snapshot_limit},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self.resync_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:500]
            return None
        receive_mono_ns = time.monotonic_ns()
        receive_wall_ms = int(time.time() * 1_000)

        # If the socket changed while HTTP was in flight, this snapshot belongs to
        # the old epoch and must not re-anchor the new connection.
        if state.connection_id not in {None, connection_id}:
            return None
        try:
            last_update_id = int(payload["lastUpdateId"])
        except (KeyError, TypeError, ValueError, OverflowError):
            self.resync_failures += 1
            self.last_error = "INVALID_SNAPSHOT_LAST_UPDATE_ID"
            return None

        bids = payload.get("bids") if isinstance(payload.get("bids"), list) else []
        asks = payload.get("asks") if isinstance(payload.get("asks"), list) else []
        exchange_ts_ms = _int_or_none(payload.get("T")) or _int_or_none(payload.get("E"))
        result = state.sur_snapshot(
            last_update_id=last_update_id,
            bids=bids,
            asks=asks,
            exchange_ts_ms=exchange_ts_ms,
            receive_ts_ms=receive_wall_ms,
            receive_mono_ns=receive_mono_ns,
            connection_id=connection_id,
        )
        self.snapshots_received += 1
        self._emit_tick(
            TickEnvelope(
                source_id="binance_usdm_public",
                channel="l2Book_snapshot",
                instrument=key,
                event_kind=FeedEventKind.SNAPSHOT,
                raw_payload=payload,
                exchange_ts_ms=exchange_ts_ms,
                received_ts_ms=receive_wall_ms,
                local_monotonic_ns=receive_mono_ns,
                connection_id=connection_id,
                sequence=last_update_id,
                gap_count=0,
                provenance={
                    "url": f"{self.rest_base_url}/fapi/v1/depth",
                    "network": "mainnet",
                    "access": "read_only",
                    "transport": "https",
                    "authenticated": False,
                    "snapshot_limit": self.snapshot_limit,
                    "request_send_wall_ms": send_wall_ms,
                    "request_receive_wall_ms": receive_wall_ms,
                    "gap_count_semantics": "event_delta",
                },
                parsed_summary={
                    "bid_levels": len(bids),
                    "ask_levels": len(asks),
                    "needs_resnapshot": bool(result["needs_snapshot"]),
                    "cumulative_gap_count": state.gap_count,
                    "book_state": (
                        "BUFFERING_SNAPSHOT"
                        if bool(result["needs_snapshot"])
                        else "EXPLOITABLE"
                    ),
                    "data_gate_ready": False,
                },
            )
        )
        publication = state.publier(self.publication_depth)
        self._emit_publication(key, publication)
        self.last_error = ""
        return publication

    async def run(self) -> None:
        """Run until cancelled; reconnects are observable and always re-snapshot."""
        if not self.symbols:
            return
        attempt = 0
        try:
            while True:
                connection_id = f"bin-depth-{uuid.uuid4().hex}"
                try:
                    async with websockets.connect(
                        self.websocket_url(),
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=5,
                        max_size=2**23,
                    ) as socket:
                        attempt = 0
                        async for raw_text in socket:
                            receive_mono_ns = time.monotonic_ns()
                            receive_wall_ms = int(time.time() * 1_000)
                            try:
                                payload = json.loads(raw_text)
                            except (TypeError, ValueError):
                                continue
                            if not isinstance(payload, Mapping):
                                continue
                            frame = parse_depth_frame(payload)
                            if frame is None:
                                continue
                            symbol = frame["symbol"]
                            state = self.states.get(symbol)
                            if state is None:
                                continue
                            self.frames_received += 1
                            gaps_before = state.gap_count
                            status = state.sur_diff(
                                U=frame["U"],
                                u=frame["u"],
                                pu=frame["pu"],
                                bids=frame["bids"],
                                asks=frame["asks"],
                                exchange_ts_ms=(
                                    frame["transaction_ts_ms"] or frame["event_ts_ms"]
                                ),
                                receive_ts_ms=receive_wall_ms,
                                receive_mono_ns=receive_mono_ns,
                                connection_id=connection_id,
                            )
                            gap_delta = max(0, state.gap_count - gaps_before)
                            if status == BUFFERISE:
                                book_state = "BUFFERING_SNAPSHOT"
                            elif status.startswith("DESYNC"):
                                book_state = "DESYNC"
                            else:
                                book_state = "EXPLOITABLE"
                            self._emit_tick(
                                TickEnvelope(
                                    source_id="binance_usdm_public",
                                    channel="l2Book",
                                    instrument=symbol,
                                    event_kind=FeedEventKind.INCREMENTAL,
                                    raw_payload=frame["raw"],
                                    exchange_ts_ms=(
                                        frame["transaction_ts_ms"] or frame["event_ts_ms"]
                                    ),
                                    received_ts_ms=receive_wall_ms,
                                    local_monotonic_ns=receive_mono_ns,
                                    connection_id=connection_id,
                                    sequence=frame["u"],
                                    gap_count=gap_delta,
                                    provenance={
                                        "url": self.websocket_url(),
                                        "network": "mainnet",
                                        "access": "read_only",
                                        "transport": "websocket",
                                        "authenticated": False,
                                        "stream": "diff_depth_100ms",
                                        "gap_count_semantics": "event_delta",
                                    },
                                    parsed_summary={
                                        "first_update_id": frame["U"],
                                        "previous_update_id": frame["pu"],
                                        "book_state": book_state,
                                        "cumulative_gap_count": state.gap_count,
                                        "buffer_overflow_count": state.buffer_overflow_count,
                                        "data_gate_ready": False,
                                    },
                                )
                            )
                            if state.besoin_resnapshot():
                                self._schedule_resync(symbol, connection_id)
                            elif status != BUFFERISE:
                                self._emit_publication(
                                    symbol,
                                    state.publier(self.publication_depth),
                                )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.reconnects += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"[:500]
                    await asyncio.sleep(min(30.0, 2.0 ** min(attempt, 5)))
                    attempt += 1
        finally:
            await self.close()

    def health(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "symbols": len(self.symbols),
            "frames_received": self.frames_received,
            "snapshots_received": self.snapshots_received,
            "resync_failures": self.resync_failures,
            "publications": self.publications,
            "reconnects": self.reconnects,
            "pending_resyncs": len(self._resync_pending),
            "books_exploitable": sum(
                1 for state in self.states.values() if not state.besoin_resnapshot()
            ),
            "last_error": self.last_error,
            "read_only": True,
            "real_execution": False,
        }

    def _schedule_resync(self, symbol: str, connection_id: str) -> None:
        if symbol in self._resync_pending:
            return
        self._resync_pending.add(symbol)

        async def worker() -> None:
            try:
                await self.resync_symbol(symbol, connection_id=connection_id)
            finally:
                self._resync_pending.discard(symbol)

        asyncio.create_task(worker())

    def _emit_tick(self, envelope: TickEnvelope) -> None:
        if self.tick_sink is not None:
            self.tick_sink(envelope)

    def _emit_publication(self, symbol: str, publication: Mapping[str, Any]) -> None:
        self.publications += 1
        if self.publication_sink is not None:
            self.publication_sink(symbol, publication)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "BinanceDepthLiveCollector",
    "REST_BASE_URL",
    "SCHEMA_VERSION",
    "WS_BASE_URL",
    "parse_depth_frame",
]
