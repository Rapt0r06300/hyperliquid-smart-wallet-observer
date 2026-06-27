"""SourceRegistry (V12 capability A — Fondation).

In-memory registry of data sources + their fetch provenance, with a computed,
deny-by-default health per source. The decision layer asks ``is_usable(source_id)``
before trusting any data: a source that has never fetched, is failing, or is
stale is NOT usable → the upstream gate turns that into NO_TRADE.

Deterministic and pure (caller passes timestamps); no I/O, no network, no order.
"""

from __future__ import annotations

from collections import deque

from hl_observer.sources.models import (
    FetchProvenance,
    SourceDefinition,
    SourceHealthSnapshot,
    SourceStatus,
)


class SourceRegistry:
    def __init__(
        self,
        *,
        history_per_source: int = 50,
        stale_after_ms: int = 60_000,
        down_consecutive_errors: int = 3,
        degraded_success_rate: float = 0.80,
    ) -> None:
        self._defs: dict[str, SourceDefinition] = {}
        self._history: dict[str, deque[FetchProvenance]] = {}
        self._seen_requests: dict[str, set[str]] = {}
        self._history_per_source = max(1, history_per_source)
        self._stale_after_ms = max(1, stale_after_ms)
        self._down_consecutive_errors = max(1, down_consecutive_errors)
        self._degraded_success_rate = degraded_success_rate

    # ---- registration ----
    def register(self, definition: SourceDefinition) -> None:
        self._defs[definition.source_id] = definition
        self._history.setdefault(definition.source_id, deque(maxlen=self._history_per_source))
        self._seen_requests.setdefault(definition.source_id, set())

    def definitions(self) -> list[SourceDefinition]:
        return list(self._defs.values())

    def is_registered(self, source_id: str) -> bool:
        return source_id in self._defs

    # ---- provenance ----
    def record_fetch(self, prov: FetchProvenance) -> bool:
        """Record a fetch. Returns False if it's a duplicate request_id (deduped)."""
        sid = prov.source_id
        if sid not in self._history:
            # auto-register unknown source as a placeholder so provenance is never lost
            self._history[sid] = deque(maxlen=self._history_per_source)
            self._seen_requests[sid] = set()
        seen = self._seen_requests[sid]
        if prov.request_id in seen:
            return False
        seen.add(prov.request_id)
        self._history[sid].append(prov)
        # bound the dedupe set roughly to the history window
        if len(seen) > self._history_per_source * 4:
            self._seen_requests[sid] = set(p.request_id for p in self._history[sid])
        return True

    # ---- health ----
    def health(self, source_id: str, *, now_ms: int) -> SourceHealthSnapshot:
        hist = self._history.get(source_id)
        if not hist:
            return SourceHealthSnapshot(
                source_id=source_id, status=SourceStatus.UNKNOWN, reasons=("NO_FETCH_YET",)
            )
        samples = list(hist)
        n = len(samples)
        oks = [p for p in samples if p.ok]
        success_rate = len(oks) / n if n else 0.0
        last_fetch_ms = max(p.fetched_at_ms for p in samples)
        last_ok_ms = max((p.fetched_at_ms for p in oks), default=None)
        age_ms = (now_ms - last_ok_ms) if last_ok_ms is not None else None

        # consecutive errors at the tail
        consecutive_errors = 0
        for p in reversed(samples):
            if p.ok:
                break
            consecutive_errors += 1

        reasons: list[str] = []
        if last_ok_ms is None:
            status = SourceStatus.DOWN
            reasons.append("NO_SUCCESSFUL_FETCH")
        elif consecutive_errors >= self._down_consecutive_errors:
            status = SourceStatus.DOWN
            reasons.append(f"CONSECUTIVE_ERRORS={consecutive_errors}")
        elif age_ms is not None and age_ms > self._stale_after_ms:
            status = SourceStatus.STALE
            reasons.append(f"LAST_OK_AGE_MS={age_ms}>{self._stale_after_ms}")
        elif success_rate < self._degraded_success_rate or any(
            p.data_quality in ("DEGRADED", "BAD") for p in samples[-3:]
        ):
            status = SourceStatus.DEGRADED
            reasons.append(f"SUCCESS_RATE={success_rate:.2f}")
        else:
            status = SourceStatus.OK

        last_error = next((p.error for p in reversed(samples) if p.error), None)
        return SourceHealthSnapshot(
            source_id=source_id,
            status=status,
            last_ok_ms=last_ok_ms,
            last_fetch_ms=last_fetch_ms,
            age_ms=age_ms,
            consecutive_errors=consecutive_errors,
            success_rate=round(success_rate, 4),
            samples=n,
            last_error=last_error,
            reasons=tuple(reasons),
        )

    def is_usable(self, source_id: str, *, now_ms: int) -> bool:
        """Deny-by-default: a disabled / unknown / stale / down source is NOT usable."""
        definition = self._defs.get(source_id)
        if definition is not None and not definition.enabled:
            return False
        return self.health(source_id, now_ms=now_ms).usable

    def all_health(self, *, now_ms: int) -> list[SourceHealthSnapshot]:
        ids = set(self._defs) | set(self._history)
        return [self.health(sid, now_ms=now_ms) for sid in sorted(ids)]


__all__ = ["SourceRegistry"]
