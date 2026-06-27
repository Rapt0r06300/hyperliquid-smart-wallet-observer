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

from hl_observer.sources.models import (
    FetchProvenance,
    SourceDefinition,
    SourceHealthSnapshot,
    SourceKind,
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
    ) -> None:
        self.registry = registry or SourceRegistry(stale_after_ms=stale_after_ms)
        self.raw_store = raw_store or RawStore()
        self.context = context
        self._counter = 0

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
            self.registry.record_fetch(FetchProvenance(
                source_id=sid,
                request_id=request_id,
                fetched_at_ms=ts,
                ok=bool(ok),
                data_quality="OK" if ok else "BAD",
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
                ))
            return self.registry.health(sid, now_ms=ts)
        except Exception:
            return None

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
            self.registry.record_fetch(FetchProvenance(
                source_id=sid,
                request_id=request_id,
                fetched_at_ms=ts,
                ok=bool(ok),
                data_quality="OK" if ok else "BAD",
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
                ))
            return self.registry.health(sid, now_ms=ts)
        except Exception:
            return None

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
        }


__all__ = ["CollectionRecorder"]
