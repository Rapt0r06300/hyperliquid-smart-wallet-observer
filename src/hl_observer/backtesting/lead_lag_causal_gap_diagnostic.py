"""Legacy gap-diagnostic facade backed by canonical Lead-Lag diagnostics v4.

This filename is retained for historical imports only. It deliberately contains
no independent gap/cadence classifier. All event classification is delegated to
``lead_lag_causal_diagnostics.diagnose_causal_book_coverage`` so cumulative
counters, loader incompleteness and event-local deltas have one meaning across
the repository.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.lead_lag_causal_diagnostics import (
    DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)

SCHEMA_VERSION = "hypersmart.lead_lag_causal_book_coverage.v4"
EXECUTABLE_BOOK_LIMIT_MS = DIAGNOSTIC_MAX_BOOK_DELAY_MS


def diagnose_causal_book_availability(
    shocks: Sequence[Mapping[str, Any]],
    books: Sequence[Mapping[str, Any]],
    *,
    max_book_delay_ms: int = EXECUTABLE_BOOK_LIMIT_MS,
    microstructure_meta: Mapping[str, Any] | None = None,
    coin: str = "ETH",
) -> dict[str, Any]:
    """Compatibility wrapper; canonical v4 owns every classification."""

    result = diagnose_causal_book_coverage(
        shocks,
        {str(coin).upper(): list(books)},
        dict(microstructure_meta or {}),
        coin=coin,
        max_book_delay_ms=max_book_delay_ms,
    )
    return {
        **result,
        "schema_version": SCHEMA_VERSION,
        "compatibility_api": "lead_lag_causal_gap_diagnostic.v1->canonical.v4",
        "purpose": "DIAGNOSE_COLLECTOR_GAP_VS_RECORDED_BOOK_CADENCE",
        "strategy_parameters_changed": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "EXECUTABLE_BOOK_LIMIT_MS",
    "SCHEMA_VERSION",
    "diagnose_causal_book_availability",
]
