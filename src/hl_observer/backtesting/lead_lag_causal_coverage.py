"""Diagnostic causal de couverture carnet pour Lead-Lag.

Ce module ne sélectionne aucune stratégie et ne modifie aucun seuil économique.
Il répond à une question plus simple et plus dure : pour un choc déjà observé,
avions-nous un carnet Hyperliquid causal et exploitable assez vite, ou la preuve
est-elle absente/incomplète ?

Le seuil 8 bps est uniquement un seuil de *diagnostic de source* utilisé pour
autopsier les événements rares déjà observés. Le mécanisme économique V3 reste
figé à son seuil propre (20 bps dans ``lead_lag_queue_replay``).

PAPER / READ-ONLY uniquement. Aucune surface d'exécution.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_causal_book_coverage.v1"
DIAGNOSTIC_SHOCK_THRESHOLD_BPS = 8.0
ECONOMIC_SHOCK_THRESHOLD_BPS = 20.0
DEFAULT_MAX_BOOK_DELAY_MS = 750
DEFAULT_GAP_EVIDENCE_HORIZON_MS = 5_000


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _int_ms(value: object) -> int | None:
    parsed = _finite(value)
    if parsed is None or parsed <= 0:
        return None
    return int(parsed)


def _quality_reasons(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("quality_reasons")
    if isinstance(raw, str):
        return [item.strip() for item in raw.split("|") if item.strip()]
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _explicit_gap_evidence(row: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    gap_count = int(_finite(row.get("gap_count")) or 0)
    reconnect_count = int(_finite(row.get("reconnect_count")) or 0)
    if gap_count > 0:
        reasons.append(f"gap_count={gap_count}")
    if reconnect_count > 0:
        reasons.append(f"reconnect_count={reconnect_count}")
    for reason in _quality_reasons(row):
        lowered = reason.casefold()
        if "gap" in lowered or "reconnect" in lowered or "sequence" in lowered:
            reasons.append(reason)
    return bool(reasons), reasons


def _loader_complete_for_event(
    event_ts_ms: int,
    microstructure_meta: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    """Return whether every loader window covering the event completed.

    A loader budget/time stop is *not* market evidence. If the diagnostic loader
    did not finish, the result must stay inconclusive rather than being labelled
    as a market-side absence.
    """

    top_stop = str(microstructure_meta.get("stopped_reason") or "UNKNOWN")
    per_window = microstructure_meta.get("per_window")
    windows = microstructure_meta.get("windows")
    reasons: list[str] = []

    if not isinstance(per_window, Sequence) or not isinstance(windows, Sequence):
        if top_stop != "COMPLETED":
            reasons.append(f"loader={top_stop}")
            return False, reasons
        return True, reasons

    matched = False
    for index, window in enumerate(windows):
        if not isinstance(window, Mapping):
            continue
        start_ms = _int_ms(window.get("start_ms"))
        end_ms = _int_ms(window.get("end_ms"))
        if start_ms is None or end_ms is None or not (start_ms <= event_ts_ms <= end_ms):
            continue
        matched = True
        meta = per_window[index] if index < len(per_window) else None
        stop = str(meta.get("stopped_reason") or "UNKNOWN") if isinstance(meta, Mapping) else "UNKNOWN"
        if stop != "COMPLETED":
            reasons.append(f"window[{index}]={stop}")

    if not matched and top_stop != "COMPLETED":
        reasons.append(f"loader={top_stop}")
    return not reasons, reasons


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = max(0.0, min(1.0, float(fraction))) * (len(clean) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return clean[lower]
    weight = position - lower
    return clean[lower] * (1.0 - weight) + clean[upper] * weight


def diagnose_causal_book_coverage(
    shocks: Sequence[Mapping[str, Any]],
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    microstructure_meta: Mapping[str, Any],
    coin: str = "ETH",
    max_book_delay_ms: int = DEFAULT_MAX_BOOK_DELAY_MS,
    gap_evidence_horizon_ms: int = DEFAULT_GAP_EVIDENCE_HORIZON_MS,
    diagnostic_threshold_bps: float = DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    economic_threshold_bps: float = ECONOMIC_SHOCK_THRESHOLD_BPS,
) -> dict[str, Any]:
    """Classify source coverage around already-observed Lead-Lag shocks.

    Classification is intentionally fail-closed:

    - ``EXECUTABLE_CAUSAL_BOOK``: first observable book is <= max delay and data gate ready;
    - ``CAUSAL_BOOK_PRESENT_QUALITY_REJECTED``: timely book exists but fails its data gate;
    - ``CAUSAL_BOOK_TOO_LATE``: a later causal book exists, with no explicit collector gap proof;
    - ``EXPLICIT_COLLECTOR_GAP_EVIDENCE``: nearby causal evidence itself records gap/reconnect;
    - ``NO_RECORDED_BOOK_NO_EXPLICIT_GAP``: no nearby book and no explicit gap evidence;
    - ``INCONCLUSIVE_LOADER_PARTIAL``: local diagnostic scan did not complete.

    Importantly, absence of a row is never by itself called a collector gap.
    """

    selected_coin = str(coin).upper()
    books = sorted(
        [dict(row) for row in l2_history.get(selected_coin, ()) if _int_ms(row.get("ts_ms")) is not None],
        key=lambda row: int(row["ts_ms"]),
    )
    timestamps = [int(row["ts_ms"]) for row in books]
    max_delay = max(0, int(max_book_delay_ms))
    gap_horizon = max(max_delay, int(gap_evidence_horizon_ms))

    events: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    observed_delays: list[float] = []

    for raw_shock in sorted(
        (dict(row) for row in shocks if _int_ms(row.get("trigger_ts_ms")) is not None),
        key=lambda row: int(row["trigger_ts_ms"]),
    ):
        trigger_ms = int(raw_shock["trigger_ts_ms"])
        loader_complete, loader_reasons = _loader_complete_for_event(
            trigger_ms,
            microstructure_meta,
        )
        index = bisect.bisect_left(timestamps, trigger_ms)
        first_book = books[index] if index < len(books) else None
        previous_book = books[index - 1] if index > 0 else None
        first_delay = (
            float(int(first_book["ts_ms"]) - trigger_ms)
            if first_book is not None
            else None
        )
        if first_delay is not None and first_delay >= 0:
            observed_delays.append(first_delay)

        nearby_rows: list[Mapping[str, Any]] = []
        if previous_book is not None and trigger_ms - int(previous_book["ts_ms"]) <= gap_horizon:
            nearby_rows.append(previous_book)
        if first_book is not None and int(first_book["ts_ms"]) - trigger_ms <= gap_horizon:
            nearby_rows.append(first_book)

        gap_reasons: list[str] = []
        for row in nearby_rows:
            has_gap, reasons = _explicit_gap_evidence(row)
            if has_gap:
                gap_reasons.extend(reasons)
        gap_reasons = sorted(set(gap_reasons))

        if not loader_complete:
            classification = "INCONCLUSIVE_LOADER_PARTIAL"
        elif first_book is not None and first_delay is not None and 0 <= first_delay <= max_delay:
            if first_book.get("data_gate_ready") is True:
                classification = "EXECUTABLE_CAUSAL_BOOK"
            else:
                classification = "CAUSAL_BOOK_PRESENT_QUALITY_REJECTED"
        elif gap_reasons:
            classification = "EXPLICIT_COLLECTOR_GAP_EVIDENCE"
        elif first_book is not None:
            classification = "CAUSAL_BOOK_TOO_LATE"
        else:
            classification = "NO_RECORDED_BOOK_NO_EXPLICIT_GAP"

        counts[classification] = counts.get(classification, 0) + 1
        events.append(
            {
                "trigger_ts_ms": trigger_ms,
                "lead_shock_bps": _finite(raw_shock.get("lead_shock_bps")),
                "direction": int(_finite(raw_shock.get("direction")) or 0),
                "classification": classification,
                "first_causal_book_ts_ms": int(first_book["ts_ms"]) if first_book is not None else None,
                "first_causal_book_delay_ms": first_delay,
                "first_book_data_gate_ready": (
                    first_book.get("data_gate_ready") is True if first_book is not None else None
                ),
                "first_book_received_ts_ms": (
                    _int_ms(first_book.get("received_ts_ms")) if first_book is not None else None
                ),
                "first_book_written_ts_ms": (
                    _int_ms(first_book.get("written_ts_ms")) if first_book is not None else None
                ),
                "previous_book_ts_ms": int(previous_book["ts_ms"]) if previous_book is not None else None,
                "explicit_gap_evidence": bool(gap_reasons),
                "gap_evidence_reasons": gap_reasons,
                "loader_complete": loader_complete,
                "loader_reasons": loader_reasons,
            }
        )

    executable = counts.get("EXECUTABLE_CAUSAL_BOOK", 0)
    total = len(events)
    conclusive = total - counts.get("INCONCLUSIVE_LOADER_PARTIAL", 0)
    return {
        "schema_version": SCHEMA_VERSION,
        "coin": selected_coin,
        "diagnostic_only": True,
        "diagnostic_shock_threshold_bps": float(diagnostic_threshold_bps),
        "economic_shock_threshold_bps_unchanged": float(economic_threshold_bps),
        "max_executable_book_delay_ms": max_delay,
        "explicit_gap_evidence_horizon_ms": gap_horizon,
        "event_count": total,
        "conclusive_event_count": conclusive,
        "classification_counts": counts,
        "executable_event_count": executable,
        "executable_event_ratio": (executable / conclusive if conclusive > 0 else None),
        "first_book_delay_p50_ms": _percentile(observed_delays, 0.50),
        "first_book_delay_p95_ms": _percentile(observed_delays, 0.95),
        "events": events,
        "interpretation_rule": (
            "ABSENCE_IS_NOT_A_GAP; ONLY_RECORDED_GAP_RECONNECT_OR_SEQUENCE_EVIDENCE_CAN_PROVE_COLLECTION_GAP"
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DEFAULT_GAP_EVIDENCE_HORIZON_MS",
    "DEFAULT_MAX_BOOK_DELAY_MS",
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "ECONOMIC_SHOCK_THRESHOLD_BPS",
    "SCHEMA_VERSION",
    "diagnose_causal_book_coverage",
]
