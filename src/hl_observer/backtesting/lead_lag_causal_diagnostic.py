"""Compatibility facade for the canonical Lead-Lag causal diagnostic.

The authoritative classifier lives in ``lead_lag_causal_diagnostics.py``.
This module keeps the older public function name so historical callers do not
break, but it contains no independent gap logic. In particular, cumulative
``gap_count``/``reconnect_count`` values are never sufficient by themselves:
only the canonical event-local delta/window logic can classify a recorded gap.

The 8 bps threshold remains diagnostic-only. It never changes the frozen 20 bps
economic strategy, creates trades or certifies PnL.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.lead_lag_causal_diagnostics import (
    DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    ECONOMIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)

SCHEMA_VERSION = "hypersmart.lead_lag_causal_book_coverage.v4"
DEFAULT_MAX_BOOK_DELAY_MS = DIAGNOSTIC_MAX_BOOK_DELAY_MS
DEFAULT_LOOKAHEAD_MS = 15_000


def diagnose_causal_book_availability(
    shocks: Sequence[Mapping[str, Any]],
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    coin: str = "ETH",
    max_book_delay_ms: int = DEFAULT_MAX_BOOK_DELAY_MS,
    lookahead_ms: int = DEFAULT_LOOKAHEAD_MS,
    diagnostic_threshold_bps: float = DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    microstructure_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Delegate all causal classification to the canonical v4 implementation.

    ``lookahead_ms`` and ``diagnostic_threshold_bps`` remain accepted for API
    compatibility/provenance only. The classifier itself receives the causal
    books and the event-window loader metadata. Supplying no metadata is
    fail-closed: the wrapper cannot invent ``SCAN_INCOMPLETE`` or gap evidence.
    """

    canonical = diagnose_causal_book_coverage(
        shocks,
        l2_history,
        dict(microstructure_meta or {}),
        coin=coin,
        max_book_delay_ms=max_book_delay_ms,
    )
    counts = canonical.get("classifications")
    if not isinstance(counts, Mapping):
        counts = {}

    executable = int(counts.get("EXECUTABLE_CAUSAL_BOOK", 0) or 0)
    explicit_gap = int(counts.get("EXPLICIT_RECORDED_FEED_GAP", 0) or 0)
    quality_rejected = int(
        counts.get("BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY", 0) or 0
    )
    late = int(counts.get("CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF", 0) or 0)
    no_later = int(counts.get("NO_LATER_BOOK_RECORDED_NO_GAP_PROOF", 0) or 0)
    inconclusive = int(counts.get("INCONCLUSIVE_DIAGNOSTIC_SCAN", 0) or 0)

    if executable:
        conclusion = "EXECUTABLE_BOOKS_EXIST_IN_DIAGNOSTIC_SAMPLE"
    elif explicit_gap:
        conclusion = "COLLECTION_GAPS_EXPLAIN_AT_LEAST_PART_OF_MISSING_EXECUTION_EVIDENCE"
    elif quality_rejected:
        conclusion = "BOOKS_EXIST_BUT_DATA_QUALITY_GATE_BLOCKS_EXECUTION"
    elif inconclusive:
        conclusion = "DIAGNOSTIC_SCAN_INCOMPLETE_FAIL_CLOSED"
    elif late:
        conclusion = "RECORDED_BOOKS_ARE_CAUSAL_BUT_TOO_LATE_FOR_750MS_BUDGET"
    elif no_later:
        conclusion = "NO_EXECUTABLE_BOOK_AND_NO_EXPLICIT_GAP_PROOF"
    else:
        conclusion = "NO_DIAGNOSTIC_SHOCKS"

    # Preserve a few aggregate aliases used by historical reports while keeping
    # the canonical schema/classification/event rows untouched.
    return {
        **canonical,
        "schema_version": SCHEMA_VERSION,
        "purpose": "SOURCE_COVERAGE_DIAGNOSTIC_ONLY_NOT_ECONOMIC_TUNING",
        "compatibility_api": "lead_lag_causal_diagnostic.v1->canonical.v4",
        "diagnostic_shock_threshold_bps": float(diagnostic_threshold_bps),
        "economic_shock_threshold_bps_unchanged": float(
            ECONOMIC_SHOCK_THRESHOLD_BPS
        ),
        "economic_threshold_unchanged": True,
        "diagnostic_lookahead_ms_legacy_only": max(0, int(lookahead_ms)),
        "book_count": sum(len(rows) for rows in l2_history.values()),
        "executable_book_events": executable,
        "explicit_collection_gap_events": explicit_gap,
        "quality_rejected_events": quality_rejected,
        "late_book_events": late,
        "gap_unproven_events": late + no_later,
        "inconclusive_scan_events": inconclusive,
        "conclusion": conclusion,
        "creates_trades": False,
        "changes_strategy_parameters": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DEFAULT_LOOKAHEAD_MS",
    "DEFAULT_MAX_BOOK_DELAY_MS",
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "SCHEMA_VERSION",
    "diagnose_causal_book_availability",
]
