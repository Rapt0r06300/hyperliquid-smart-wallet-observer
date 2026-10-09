"""Live public Binance USD-M deep-L2 collector.

Implements the official snapshot + diff-depth reconstruction protocol without any
authenticated/account endpoint. WebSocket frames are stamped at receipt with wall and
monotonic clocks, persisted as replayable TickEnvelope evidence, and reconstructed by
BinanceDepthOrchestrator. A reconnect or continuity break always requires a fresh public
snapshot before the book becomes exploitable again. REST is preferred; Binance's public
WebSocket API depth request is the full-depth fallback when REST egress is restricted.
"""
from __future__ import annotations

import asyncio
import inspect
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
from hl_observer.collection.depth_capacity import capacity_tape_envelope
from hl_observer.collection.feed_integrity import ClockSyncSample, estimate_clock_sync
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

REST_BASE_URL = "https://fapi.binance.com"
WS_BASE_URL = "wss://fstream.binance.com/public/stream"
# Production-only: the official Binance Futures connector labels
# stream.binancefuture.com as Testnet UM. Full-L2 fallback stays on the separate
# production WS API (ws-fapi.binance.com), never on a testnet stream host.
WS_FALLBACK_BASE_URLS: tuple[str, ...] = ()
WS_API_URL = "wss://ws-fapi.binance.com/ws-fapi/v1"
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
        ws_fallback_urls: Iterable[str] = WS_FALLBACK_BASE_URLS,
        ws_api_url: str = WS_API_URL,
        snapshot_limit: int = 1000,
        publication_depth: int = 200,
        partial_fallback_levels: int = 20,
        rest_retry_cooldown_s: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
        tick_sink: Callable[[TickEnvelope], Any] | None = None,
        publication_sink: Callable[[str, Mapping[str, Any]], Any] | None = None,
        clock_sync_provider: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self.symbols = tuple(
            sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        )
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_base_url = ws_base_url.rstrip("/")
        self.ws_fallback_urls = tuple(
            dict.fromkeys(
                str(url).rstrip("/")
                for url in ws_fallback_urls
                if str(url).strip()
                and str(url).rstrip("/") != self.ws_base_url
            )
        )
        self.last_ws_base_url = self.ws_base_url
        self.last_ws_error = ""
        self.ws_api_url = ws_api_url.rstrip("/")
        self.snapshot_limit = int(snapshot_limit)
        if self.snapshot_limit not in {5, 10, 20, 50, 100, 500, 1000}:
            raise ValueError("unsupported Binance snapshot_limit")
        self.publication_depth = max(1, min(int(publication_depth), self.snapshot_limit))
        self.partial_fallback_levels = int(partial_fallback_levels)
        if self.partial_fallback_levels not in {5, 10, 20}:
            raise ValueError("partial_fallback_levels must be one of 5, 10, 20")
        self._owns_http = http_client is None
        self.http = http_client or httpx.AsyncClient(
            base_url=self.rest_base_url,
            timeout=10.0,
        )
        self.tick_sink = tick_sink
        self.publication_sink = publication_sink
        self.clock_sync_provider = clock_sync_provider
        self.states = {
            symbol: BinanceDepthOrchestrator(futures=True)
            for symbol in self.symbols
        }
        self._resync_pending: set[str] = set()
        self._rest_unavailable_symbols: set[str] = set()
        self._full_snapshot_unavailable_symbols: set[str] = set()
        self.rest_retry_cooldown_s = max(1.0, float(rest_retry_cooldown_s))
        self._next_rest_retry_monotonic: dict[str, float] = {}
        self.frames_received = 0
        self.snapshots_received = 0
        self.ws_api_snapshots_received = 0
        self.ws_api_failures = 0
        self._snapshot_clock_sample: ClockSyncSample | None = None
        self._snapshot_clock_source = ""
        self.resync_failures = 0
        self.publications = 0
        self.partial_fallback_frames = 0
        self.partial_fallback_publications = 0
        self.reconnects = 0
        self.last_error = ""

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    def _ws_candidates(self) -> tuple[str, ...]:
        return (self.ws_base_url, *self.ws_fallback_urls)

    def websocket_url(self, base_url: str | None = None) -> str:
        streams = "/".join(
            stream
            for symbol in self.symbols
            for stream in (
                f"{symbol.lower()}@depth@100ms",
                f"{symbol.lower()}@depth{self.partial_fallback_levels}@100ms",
            )
        )
        endpoint = str(base_url or self.last_ws_base_url or self.ws_base_url).rstrip("/")
        return f"{endpoint}?streams={streams}"

    def state(self, symbol: str) -> BinanceDepthOrchestrator:
        key = str(symbol).strip().upper()
        if key not in self.states:
            raise KeyError(key)
        return self.states[key]

    async def _fetch_ws_api_snapshot(
        self,
        symbol: str,
    ) -> tuple[dict[str, Any], int, int, int]:
        """Fetch a public full-depth snapshot through Binance's WebSocket API."""
        # Binance documents a string request id and its own published depth
        # response examples do not guarantee an echoed value. Keep the request id
        # in the documented compact hex shape; the dedicated socket carries only
        # this one request, so success is validated from status + depth payload.
        request_id = uuid.uuid4().hex
        send_wall_ms = int(time.time() * 1_000)
        async with websockets.connect(
            self.ws_api_url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
            open_timeout=10,
            max_size=2**23,
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "id": request_id,
                        "method": "depth",
                        "params": {
                            "symbol": symbol,
                            "limit": self.snapshot_limit,
                        },
                    }
                )
            )
            raw = await asyncio.wait_for(socket.recv(), timeout=10.0)
        receive_mono_ns = time.monotonic_ns()
        receive_wall_ms = int(time.time() * 1_000)
        response = json.loads(raw)
        if not isinstance(response, Mapping):
            raise RuntimeError("BINANCE_WS_API_DEPTH_INVALID_RESPONSE")
        try:
            response_status = int(response.get("status") or 0)
        except (TypeError, ValueError, OverflowError):
            raise RuntimeError("BINANCE_WS_API_DEPTH_STATUS_INVALID") from None
        if response_status != 200:
            error_payload = response.get("error")
            error_detail = (
                json.dumps(
                    error_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                if error_payload is not None
                else ""
            )
            raise RuntimeError(
                (
                    f"BINANCE_WS_API_DEPTH_STATUS_{response_status}:"
                    f"id={response.get('id')!r}:error={error_detail}"
                )[:1000]
            )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise RuntimeError("BINANCE_WS_API_DEPTH_RESULT_MISSING")
        payload = dict(result)
        if (
            not isinstance(payload.get("bids"), list)
            or not isinstance(payload.get("asks"), list)
        ):
            raise RuntimeError("BINANCE_WS_API_DEPTH_BOOK_MISSING")
        return payload, send_wall_ms, receive_wall_ms, receive_mono_ns

    async def resync_symbol(self, symbol: str, *, connection_id: str) -> dict[str, Any] | None:
        """Fetch a public snapshot and replay all already-buffered WS diffs."""
        key = str(symbol).strip().upper()
        state = self.states.get(key)
        if state is None:
            return None

        snapshot_source = "rest"
        snapshot_url = f"{self.rest_base_url}/fapi/v1/depth"
        snapshot_transport = "https"
        send_wall_ms = int(time.time() * 1_000)
        rest_error = ""
        rest_retry_at = self._next_rest_retry_monotonic.get(key, 0.0)
        rest_allowed = time.monotonic() >= rest_retry_at
        if rest_allowed:
            try:
                response = await self.http.get(
                    "/fapi/v1/depth",
                    params={"symbol": key, "limit": self.snapshot_limit},
                )
                response.raise_for_status()
                payload = response.json()
                receive_mono_ns = time.monotonic_ns()
                receive_wall_ms = int(time.time() * 1_000)
                self._rest_unavailable_symbols.discard(key)
                self._next_rest_retry_monotonic.pop(key, None)
            except Exception as exc:
                rest_error = f"{type(exc).__name__}: {exc}"[:500]
                self._rest_unavailable_symbols.add(key)
                self._next_rest_retry_monotonic[key] = (
                    time.monotonic() + self.rest_retry_cooldown_s
                )
        else:
            rest_error = "REST_RETRY_COOLDOWN"

        if rest_error:
            try:
                (
                    payload,
                    send_wall_ms,
                    receive_wall_ms,
                    receive_mono_ns,
                ) = await self._fetch_ws_api_snapshot(key)
            except Exception as ws_exc:
                self.ws_api_failures += 1
                self.resync_failures += 1
                self._full_snapshot_unavailable_symbols.add(key)
                self.last_error = (
                    f"REST={rest_error};WS_API={type(ws_exc).__name__}: {ws_exc}"
                )[:1000]
                return None
            snapshot_source = "websocket_api"
            snapshot_url = self.ws_api_url
            snapshot_transport = "websocket"
            self.ws_api_snapshots_received += 1
            self._full_snapshot_unavailable_symbols.discard(key)

        # If the diff-stream socket changed while the snapshot request was in flight,
        # the snapshot belongs to the old epoch and must not re-anchor the new connection.
        if state.connection_id not in {None, connection_id}:
            return None
        try:
            last_update_id = int(payload["lastUpdateId"])
        except (KeyError, TypeError, ValueError, OverflowError):
            self.resync_failures += 1
            self._full_snapshot_unavailable_symbols.add(key)
            self.last_error = "INVALID_SNAPSHOT_LAST_UPDATE_ID"
            return None

        bids = payload.get("bids") if isinstance(payload.get("bids"), list) else []
        asks = payload.get("asks") if isinstance(payload.get("asks"), list) else []
        if not bids or not asks:
            self.resync_failures += 1
            self._full_snapshot_unavailable_symbols.add(key)
            self.last_error = "EMPTY_SNAPSHOT_BOOK"
            return None

        exchange_ts_ms = _int_or_none(payload.get("T")) or _int_or_none(payload.get("E"))
        server_output_ts_ms = _int_or_none(payload.get("E"))
        if server_output_ts_ms is not None:
            self._snapshot_clock_sample = estimate_clock_sync(
                venue="binance",
                server_ts_ms=server_output_ts_ms,
                send_wall_ts_ms=send_wall_ms,
                receive_wall_ts_ms=receive_wall_ms,
            )
            self._snapshot_clock_source = f"{snapshot_source}_depth_roundtrip"
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
        self._full_snapshot_unavailable_symbols.discard(key)
        await self._emit_tick(
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
                    "url": snapshot_url,
                    "network": "mainnet",
                    "access": "read_only",
                    "transport": snapshot_transport,
                    "authenticated": False,
                    "snapshot_source": snapshot_source,
                    "snapshot_limit": self.snapshot_limit,
                    "request_send_wall_ms": send_wall_ms,
                    "request_receive_wall_ms": receive_wall_ms,
                    "rest_error_before_fallback": rest_error or None,
                    "gap_count_semantics": "event_delta",
                },
                parsed_summary={
                    **self._clock_evidence(),
                    "bid_levels": len(bids),
                    "ask_levels": len(asks),
                    "needs_resnapshot": bool(result["needs_snapshot"]),
                    "cumulative_gap_count": state.gap_count,
                    "book_state": (
                        "BUFFERING_SNAPSHOT"
                        if bool(result["needs_snapshot"])
                        else "EXPLOITABLE"
                    ),
                    "snapshot_source": snapshot_source,
                    "data_gate_ready": False,
                },
            )
        )
        publication = state.publier(self.publication_depth)
        await self._emit_publication(key, publication, source_raw_l2_payload=payload)
        self.last_error = ""
        return publication

    async def run(self) -> None:
        """Run until cancelled; reconnects are observable and always re-snapshot."""
        if not self.symbols:
            return
        attempt = 0
        candidates = self._ws_candidates()
        candidate_index = 0
        try:
            while True:
                connection_id = f"bin-depth-{uuid.uuid4().hex}"
                endpoint = candidates[candidate_index % len(candidates)]
                self.last_ws_base_url = endpoint
                try:
                    async with websockets.connect(
                        self.websocket_url(endpoint),
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=5,
                        max_size=2**23,
                    ) as socket:
                        attempt = 0
                        self.last_ws_error = ""
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
                            stream_name = str(payload.get("stream") or "")
                            is_partial_fallback_frame = (
                                f"@depth{self.partial_fallback_levels}@" in stream_name
                            )
                            if is_partial_fallback_frame:
                                self.partial_fallback_frames += 1
                                if symbol in self._full_snapshot_unavailable_symbols:
                                    await self._emit_partial_fallback(
                                        symbol,
                                        frame,
                                        connection_id=connection_id,
                                        receive_wall_ms=receive_wall_ms,
                                        receive_mono_ns=receive_mono_ns,
                                    )
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
                            await self._emit_tick(
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
                                        **self._clock_evidence(),
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
                                await self._emit_publication(
                                    symbol,
                                    state.publier(self.publication_depth),
                                    source_raw_l2_payload=frame["raw"],
                                )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.reconnects += 1
                    self.last_ws_error = f"{type(exc).__name__}: {exc}"[:500]
                    self.last_error = self.last_ws_error
                    candidate_index += 1
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
            "ws_api_snapshots_received": self.ws_api_snapshots_received,
            "ws_api_failures": self.ws_api_failures,
            "resync_failures": self.resync_failures,
            "publications": self.publications,
            "partial_fallback_frames": self.partial_fallback_frames,
            "partial_fallback_publications": self.partial_fallback_publications,
            "partial_fallback_levels": self.partial_fallback_levels,
            "rest_unavailable_symbols": sorted(self._rest_unavailable_symbols),
            "rest_retry_cooldown_s": self.rest_retry_cooldown_s,
            "rest_retry_deferred_symbols": sorted(
                symbol
                for symbol, retry_at in self._next_rest_retry_monotonic.items()
                if retry_at > time.monotonic()
            ),
            "full_snapshot_unavailable_symbols": sorted(
                self._full_snapshot_unavailable_symbols
            ),
            "reconnects": self.reconnects,
            "ws_base_url": self.last_ws_base_url,
            "ws_candidates": list(self._ws_candidates()),
            "ws_last_error": self.last_ws_error,
            "pending_resyncs": len(self._resync_pending),
            "books_exploitable": sum(
                1 for state in self.states.values() if not state.besoin_resnapshot()
            ),
            "last_error": self.last_error,
            "clock_sync": self.clock_evidence(),
            "read_only": True,
            "real_execution": False,
        }

    async def _emit_partial_fallback(
        self,
        symbol: str,
        frame: Mapping[str, Any],
        *,
        connection_id: str,
        receive_wall_ms: int,
        receive_mono_ns: int,
    ) -> None:
        """Persist bounded WS-only L2 when the official REST snapshot is unavailable.

        This is intentionally NOT promoted to a full reconstructed book: the
        publication is marked PARTIAL_L2_FALLBACK and data_gate_ready=False.
        It preserves real top-of-book depth instead of dropping the venue to zero.
        """
        bids = list(frame.get("bids") or [])[: self.partial_fallback_levels]
        asks = list(frame.get("asks") or [])[: self.partial_fallback_levels]
        if not bids or not asks:
            return
        exchange_ts_ms = frame.get("transaction_ts_ms") or frame.get("event_ts_ms")
        publication = {
            "schema_version": "alina.binance_usdm_partial_l2_fallback.v1",
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "exchange_ts_ms": exchange_ts_ms,
            "receive_ts_ms": receive_wall_ms,
            "receive_mono_ns": receive_mono_ns,
            "connection_id": connection_id,
            "sequence": frame.get("u"),
            "gap_count": 0,
            "quality": "PARTIAL_L2_FALLBACK",
            "partial_depth_levels": self.partial_fallback_levels,
            "rest_snapshot_available": False,
            "data_gate_ready": False,
            "read_only": True,
            "real_execution": False,
        }
        await self._emit_tick(
            TickEnvelope(
                source_id="binance_usdm_public",
                channel="l2Book_partial_snapshot",
                instrument=symbol,
                event_kind=FeedEventKind.SNAPSHOT,
                raw_payload=frame.get("raw") or {},
                exchange_ts_ms=_int_or_none(exchange_ts_ms),
                received_ts_ms=receive_wall_ms,
                local_monotonic_ns=receive_mono_ns,
                connection_id=connection_id,
                sequence=_int_or_none(frame.get("u")),
                gap_count=0,
                provenance={
                    "url": self.websocket_url(),
                    "network": "mainnet",
                    "access": "read_only",
                    "transport": "websocket",
                    "authenticated": False,
                    "stream": f"partial_depth_{self.partial_fallback_levels}_100ms",
                    "fallback_reason": "REST_SNAPSHOT_UNAVAILABLE",
                    "gap_count_semantics": "bounded_snapshot",
                },
                parsed_summary={
                    **self._clock_evidence(),
                    "bid_levels": len(bids),
                    "ask_levels": len(asks),
                    "book_state": "PARTIAL_L2_FALLBACK",
                    "partial_depth_levels": self.partial_fallback_levels,
                    "data_gate_ready": False,
                },
            )
        )
        self.partial_fallback_publications += 1
        await self._emit_publication(
            symbol,
            publication,
            source_raw_l2_payload=frame.get("raw"),
        )

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

    def clock_evidence(self) -> dict[str, Any]:
        """Return the best public clock evidence currently available."""
        if self.clock_sync_provider is not None:
            try:
                row = self.clock_sync_provider()
            except Exception:
                row = {}
            if isinstance(row, Mapping) and row:
                return dict(row)
        sample = self._snapshot_clock_sample
        if sample is None:
            return {}
        return {
            "clock_offset_ms": float(sample.offset_ms),
            "clock_probe_rtt_ms": float(sample.rtt_ms),
            "clock_uncertainty_ms": float(sample.uncertainty_ms),
            "clock_probe_server_ts_ms": int(sample.server_ts_ms),
            "clock_probe_receive_wall_ts_ms": int(sample.receive_wall_ts_ms),
            "clock_probe_source": self._snapshot_clock_source,
        }

    def _clock_evidence(self) -> dict[str, Any]:
        return self.clock_evidence()

    async def _emit_tick(self, envelope: TickEnvelope) -> None:
        if self.tick_sink is not None:
            result = self.tick_sink(envelope)
            if inspect.isawaitable(result):
                await result

    async def _emit_publication(
        self,
        symbol: str,
        publication: Mapping[str, Any],
        *,
        source_raw_l2_payload: Any | None = None,
    ) -> None:
        self.publications += 1
        capacity = capacity_tape_envelope(
            venue="binance",
            instrument=symbol,
            bids=publication.get("bids") if isinstance(publication.get("bids"), list) else [],
            asks=publication.get("asks") if isinstance(publication.get("asks"), list) else [],
            exchange_ts_ms=_int_or_none(publication.get("exchange_ts_ms")),
            received_ts_ms=_int_or_none(publication.get("receive_ts_ms")),
            receive_mono_ns=_int_or_none(publication.get("receive_mono_ns")),
            connection_id=str(publication.get("connection_id") or "") or None,
            sequence=_int_or_none(publication.get("sequence")),
            snapshot_id=_int_or_none(publication.get("sequence")),
            gap_count=int(publication.get("gap_count") or 0),
            quality=str(publication.get("quality") or ""),
            timing_evidence=self._clock_evidence(),
            source_raw_l2_payload=source_raw_l2_payload,
        )
        if capacity is not None:
            await self._emit_tick(capacity)
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
    "WS_API_URL",
    "WS_BASE_URL",
    "parse_depth_frame",
]
