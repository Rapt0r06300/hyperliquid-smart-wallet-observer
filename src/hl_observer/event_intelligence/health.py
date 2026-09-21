"""Bridge World Monitor coverage into Alina's fail-closed source health model."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from hl_observer.event_intelligence.external_event import ExternalEvent
from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent
from hl_observer.realtime.source_health import SourceHealth, evaluer_sante


def evaluate_worldmonitor_health(
    events: Iterable[WorldMonitorEvent],
    *,
    coverage_state: str,
    last_fetch_ms: int | None,
    now_ms: int,
    max_age_ms: int = 60_000,
    fetch_ok: bool = True,
) -> SourceHealth:
    """Evaluate technical health separately from whether fresh signals exist."""

    now = int(now_ms)
    max_age = max(1, int(max_age_ms))
    state = str(coverage_state or "").strip().casefold()
    clock_reliable = last_fetch_ms is None or int(last_fetch_ms) <= now
    source_active = bool(fetch_ok) and state not in {
        "unavailable",
        "error",
        "disabled",
    }

    if last_fetch_ms is None:
        age_ms: float | None = None
    elif int(last_fetch_ms) > now:
        age_ms = None
    else:
        age_ms = float(now - int(last_fetch_ms))

    if state == "stale":
        age_ms = float(max_age + 1)

    known_states = {
        "complete",
        "current",
        "partial",
        "stale",
        "unavailable",
        "error",
        "disabled",
    }
    incomplete = 1 if state == "partial" or state not in known_states else 0

    fresh_signals = 0
    for row in events:
        if not row.usable_for_signal:
            continue
        ingest_ts_ms = int(row.event.ingest_ts_ms)
        if ingest_ts_ms > now:
            clock_reliable = False
            continue
        if now - ingest_ts_ms <= max_age:
            fresh_signals += 1

    return evaluer_sante(
        fresh_entry_deltas=fresh_signals,
        fresh_follow_signals=0,
        market_data_age_ms=age_ms,
        max_market_data_age_ms=float(max_age),
        contrat_incomplet=incomplete,
        horloge_fiable=clock_reliable,
        source_principale_active=source_active,
    )


def evaluate_direct_source_health(
    events: Iterable[ExternalEvent],
    *,
    last_fetch_ms: int | None,
    now_ms: int,
    max_age_ms: int,
    fetch_ok: bool = True,
    contract_complete: bool = True,
) -> SourceHealth:
    """Generic health gate for direct primary/official event sources."""

    now = int(now_ms)
    max_age = max(1, int(max_age_ms))
    clock_reliable = last_fetch_ms is None or int(last_fetch_ms) <= now
    if last_fetch_ms is None or int(last_fetch_ms) > now:
        age_ms = None
    else:
        age_ms = float(now - int(last_fetch_ms))

    fresh = 0
    for event in events:
        ts = int(event.ingest_ts_ms)
        if ts > now:
            clock_reliable = False
            continue
        if now - ts <= max_age:
            fresh += 1

    return evaluer_sante(
        fresh_entry_deltas=fresh,
        fresh_follow_signals=0,
        market_data_age_ms=age_ms,
        max_market_data_age_ms=float(max_age),
        contrat_incomplet=0 if contract_complete else 1,
        horloge_fiable=clock_reliable,
        source_principale_active=bool(fetch_ok),
    )


@dataclass(frozen=True, slots=True)
class IntelligenceGap:
    source: str
    detected_at_ms: int
    last_success_ms: int | None
    gap_age_ms: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class CoverageReport:
    expected_families: tuple[str, ...]
    observed_families: tuple[str, ...]
    missing_families: tuple[str, ...]
    coverage_ratio: float


def detect_intelligence_gap(
    *,
    source: str,
    last_success_ms: int | None,
    now_ms: int,
    max_age_ms: int,
    fetch_ok: bool,
) -> IntelligenceGap | None:
    now = int(now_ms)
    if not fetch_ok:
        age = None if last_success_ms is None else max(0, now - int(last_success_ms))
        return IntelligenceGap(str(source), now, last_success_ms, age, "FETCH_FAILED")
    if last_success_ms is None:
        return IntelligenceGap(str(source), now, None, None, "NEVER_OBSERVED")
    age = now - int(last_success_ms)
    if age < 0:
        return IntelligenceGap(str(source), now, last_success_ms, None, "CLOCK_INCOHERENT")
    if age > int(max_age_ms):
        return IntelligenceGap(str(source), now, last_success_ms, age, "SOURCE_STALE")
    return None


def coverage_by_family(
    events: Iterable[WorldMonitorEvent],
    *,
    expected_families: Iterable[str],
) -> CoverageReport:
    expected = tuple(sorted({str(value) for value in expected_families if str(value)}))
    observed = tuple(sorted({str(row.kind) for row in events if row.usable_for_signal and str(row.kind)}))
    missing = tuple(value for value in expected if value not in set(observed))
    ratio = 1.0 if not expected else (len(expected) - len(missing)) / len(expected)
    return CoverageReport(expected, observed, missing, round(ratio, 6))


__all__ = [
    "CoverageReport",
    "IntelligenceGap",
    "coverage_by_family",
    "detect_intelligence_gap",
    "evaluate_direct_source_health",
    "evaluate_worldmonitor_health",
]
