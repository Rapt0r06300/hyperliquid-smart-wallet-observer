"""CollectionRecorder (V12 — câblage Fondation A+E dans la Collecte B).

Composes the SourceRegistry (capability A) and the RawStore (capability E) into a
single best-effort recorder that the read-only Hyperliquid /info client calls once
per fetch. It captures provenance (which source, when, ok/error, item count) and
stores the raw response deduplicated by content hash, so the decision layer can ask
``usable(request_type)`` (deny-by-default) before trusting any data.

SAFETY: pure bookkeeping over REAL fetched data. It records what was actually
returned (never fabricates), places no order, and every public method is wrapped so
a recorder failure can NEVER break or alter the collection path.
"""

from __future__ import annotations

import os

from hl_observer.sources.models import (
    FetchProvenance,
    SourceDefinition,
    SourceHealthSnapshot,
    SourceKind,
    SourceStatus,
)
from hl_observer.sources.registry import SourceRegistry
from hl_observer.storage.raw_store import RawStore, make_raw_event
from hl_observer.storage.run_context import RunContext
from hl_observer.utils.time import now_ms as _now_ms


def _safe_len(payload: object) -> int | None:
    try:
        if isinstance(payload, (list, dict, tuple, str)):
            return len(payload)
    except Exception:
        return None
    return None


class CollectionRecorder:
    def __init__(
        self,
        *,
        registry: SourceRegistry | None = None,
        raw_store: RawStore | None = None,
        context: RunContext = RunContext.LIVE,
        stale_after_ms: int = 60_000,
        run_id: str | None = None,
        config_hash: str | None = None,
        code_hash: str | None = None,
        git_head: str | None = None,
    ) -> None:
        self.registry = registry or SourceRegistry(stale_after_ms=stale_after_ms)
        self.raw_store = raw_store or RawStore()
        self.context = context
        self.run_id = str(run_id or f"{context.value.lower()}-{os.getpid()}")
        self.config_hash = config_hash
        self.code_hash = code_hash
        self.git_head = git_head
        self._counter = 0
        self.recorder_failures = 0
        self.last_recorder_error: str | None = None

    def _origin(self) -> str:
        if self.context is RunContext.LIVE:
            return "LIVE_REAL"
        if self.context in (RunContext.BACKTEST, RunContext.REPLAY):
            return "RECORDED_REAL"
        if self.context is RunContext.TEST_FIXTURE:
            return "TEST_FIXTURE"
        return "UNKNOWN"

    def _provenance(
        self,
        *,
        source_id: str,
        request_id: str,
        timestamp: int,
        ok: bool,
        error: str | None,
        item_count: int | None,
    ) -> FetchProvenance:
        return FetchProvenance(
            source_id=source_id,
            request_id=request_id,
            fetched_at_ms=timestamp,
            received_at_ms=timestamp,
            written_at_ms=timestamp,
            origin=self._origin(),
            run_id=self.run_id,
            config_hash=self.config_hash,
            code_hash=self.code_hash,
            git_head=self.git_head,
            ok=bool(ok),
            data_quality="OK" if ok else "BAD",
            error=error,
            item_count=item_count,
        )

    def _failure_health(
        self,
        *,
        source_id: str,
        timestamp: int,
        exc: BaseException,
    ) -> SourceHealthSnapshot:
        self.recorder_failures += 1
        self.last_recorder_error = f"{type(exc).__name__}: {exc}"
        try:
            self.registry.record_fetch(
                self._provenance(
                    source_id=source_id,
                    request_id=f"{source_id}:{timestamp}:recorder-failure:{self.recorder_failures}",
                    timestamp=timestamp,
                    ok=False,
                    error=f"RECORDER_FAILURE: {self.last_recorder_error}",
                    item_count=None,
                )
            )
            return self.registry.health(source_id, now_ms=timestamp)
        except Exception:
            return SourceHealthSnapshot(
                source_id=source_id,
                status=SourceStatus.DOWN,
                last_fetch_ms=timestamp,
                consecutive_errors=1,
                samples=1,
                last_error=self.last_recorder_error,
                reasons=("RECORDER_FAILURE",),
            )

    # ---- internals ----
    @staticmethod
    def source_id(request_type: str) -> str:
        return f"hl_info:{request_type}"

    @staticmethod
    def ws_source_id(channel: str) -> str:
        clean = str(channel or "unknown").strip() or "unknown"
        return f"hl_ws:{clean}"

    def _ensure_registered(self, request_type: str) -> str:
        sid = self.source_id(request_type)
        if not self.registry.is_registered(sid):
            self.registry.register(SourceDefinition(
                source_id=sid,
                kind=SourceKind.HL_INFO_REST,
                endpoint_or_channel=f"/info:{request_type}",
                description=f"Hyperliquid /info {request_type} (read-only)",
            ))
        return sid

    def _ensure_ws_registered(self, channel: str) -> str:
        sid = self.ws_source_id(channel)
        if not self.registry.is_registered(sid):
            self.registry.register(SourceDefinition(
                source_id=sid,
                kind=SourceKind.HL_WS,
                endpoint_or_channel=f"ws:{channel}",
                description=f"Hyperliquid WebSocket {channel} (read-only)",
            ))
        return sid

    # ---- recording ----
    def record_rest(
        self,
        *,
        request_type: str,
        response: object = None,
        ok: bool = True,
        error: str | None = None,
        now_ms: int | None = None,
    ) -> SourceHealthSnapshot | None:
        """Record one /info fetch. Best-effort: never raises, never blocks collection."""
        try:
            sid = self._ensure_registered(request_type)
            ts = int(now_ms if now_ms is not None else _now_ms())
            self._counter += 1
            request_id = f"{sid}:{ts}:{self._counter}"
            item_count = _safe_len(response)
            self.registry.record_fetch(self._provenance(
                source_id=sid,
                request_id=request_id,
                timestamp=ts,
                ok=ok,
                error=error,
                item_count=item_count,
            ))
            if ok and response is not None:
                # RawStore dedups identical responses (replay-safe); the registry
                # still records every fetch attempt above (for health/latency).
                self.raw_store.put(make_raw_event(
                    source_id=sid,
                    kind=f"/info:{request_type}",
                    payload=response,
                    fetched_at_ms=ts,
                    context=self.context,
                    item_count=item_count,
                    request_id=request_id,
                    origin=self._origin(),
                    received_at_ms=ts,
                    written_at_ms=ts,
                    run_id=self.run_id,
                    config_hash=self.config_hash,
                    code_hash=self.code_hash,
                    git_head=self.git_head,
                ))
            return self.registry.health(sid, now_ms=ts)
        except Exception as exc:
            sid = self.source_id(request_type)
            ts = int(now_ms if now_ms is not None else _now_ms())
            return self._failure_health(source_id=sid, timestamp=ts, exc=exc)

    def record_ws(
        self,
        *,
        channel: str,
        message: object = None,
        ok: bool = True,
        error: str | None = None,
        now_ms: int | None = None,
    ) -> SourceHealthSnapshot | None:
        """Record one read-only WebSocket message. Best-effort and non-blocking."""
        try:
            sid = self._ensure_ws_registered(channel)
            ts = int(now_ms if now_ms is not None else _now_ms())
            self._counter += 1
            request_id = f"{sid}:{ts}:{self._counter}"
            item_count = _safe_len(message)
            self.registry.record_fetch(self._provenance(
                source_id=sid,
                request_id=request_id,
                timestamp=ts,
                ok=ok,
                error=error,
                item_count=item_count,
            ))
            if ok and message is not None:
                self.raw_store.put(make_raw_event(
                    source_id=sid,
                    kind=f"ws:{channel}",
                    payload=message,
                    fetched_at_ms=ts,
                    context=self.context,
                    item_count=item_count,
                    request_id=request_id,
                    origin=self._origin(),
                    received_at_ms=ts,
                    written_at_ms=ts,
                    run_id=self.run_id,
                    config_hash=self.config_hash,
                    code_hash=self.code_hash,
                    git_head=self.git_head,
                ))
            return self.registry.health(sid, now_ms=ts)
        except Exception as exc:
            sid = self.ws_source_id(channel)
            ts = int(now_ms if now_ms is not None else _now_ms())
            return self._failure_health(source_id=sid, timestamp=ts, exc=exc)

    # ---- read-only queries ----
    def health(self, request_type: str, *, now_ms: int | None = None) -> SourceHealthSnapshot:
        ts = int(now_ms if now_ms is not None else _now_ms())
        return self.registry.health(self.source_id(request_type), now_ms=ts)

    def usable(self, request_type: str, *, now_ms: int | None = None) -> bool:
        ts = int(now_ms if now_ms is not None else _now_ms())
        return self.registry.is_usable(self.source_id(request_type), now_ms=ts)

    def all_health(self, *, now_ms: int | None = None) -> list[SourceHealthSnapshot]:
        ts = int(now_ms if now_ms is not None else _now_ms())
        return self.registry.all_health(now_ms=ts)

    def summary(self, *, now_ms: int | None = None) -> dict[str, object]:
        """Dashboard-ready aggregate, derived only from recorded real fetches."""
        ts = int(now_ms if now_ms is not None else _now_ms())
        rows = self.registry.all_health(now_ms=ts)
        by_status: dict[str, int] = {}
        for r in rows:
            key = r.status.value if hasattr(r.status, "value") else str(r.status)
            by_status[key] = by_status.get(key, 0) + 1
        return {
            "sources": len(rows),
            "by_status": by_status,
            "usable": sum(1 for r in rows if r.usable),
            "raw_events_stored": self.raw_store.count(context=self.context),
            "recorder_failures": self.recorder_failures,
            "last_recorder_error": self.last_recorder_error,
        }


__all__ = ["CollectionRecorder"]
