"""Compatibility autopsy facade for canonical Lead-Lag causal diagnostics.

Historical callers may still provide a tape instead of an explicit shock list.
Shock detection is delegated to the queue replay helper and every book/gap
classification is delegated to ``lead_lag_causal_diagnostics`` v4. This module
contains no independent collector-gap semantics.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.lead_lag_causal_diagnostics import (
    DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage as _diagnose_canonical,
)
from hl_observer.backtesting.lead_lag_queue_replay import detect_rolling_shocks

SCHEMA_VERSION = "hypersmart.lead_lag_causal_book_coverage.v4"
DIAGNOSTIC_THRESHOLD_BPS = DIAGNOSTIC_SHOCK_THRESHOLD_BPS
DIAGNOSTIC_WINDOW_MS = 1_000
DIAGNOSTIC_COOLDOWN_MS = 5_000
MAX_EXECUTABLE_DELAY_MS = DIAGNOSTIC_MAX_BOOK_DELAY_MS


def diagnose_causal_book_coverage(
    tape: Mapping[str, Mapping[str, list]],
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    coin: str = "ETH",
    threshold_bps: float = DIAGNOSTIC_THRESHOLD_BPS,
    window_ms: int = DIAGNOSTIC_WINDOW_MS,
    cooldown_ms: int = DIAGNOSTIC_COOLDOWN_MS,
    max_delay_ms: int = MAX_EXECUTABLE_DELAY_MS,
    microstructure_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect diagnostic shocks, then delegate classification to canonical v4."""

    selected_coin = str(coin).upper()
    trades = list((tape.get(selected_coin) or {}).get("TRADE") or [])
    shocks = detect_rolling_shocks(
        trades,
        window_ms=window_ms,
        threshold_bps=threshold_bps,
        cooldown_ms=cooldown_ms,
    )
    result = _diagnose_canonical(
        shocks,
        l2_history,
        dict(microstructure_meta or {}),
        coin=selected_coin,
        max_book_delay_ms=max_delay_ms,
    )
    return {
        **result,
        "schema_version": SCHEMA_VERSION,
        "compatibility_api": "lead_lag_causal_autopsy.v1->canonical.v4",
        "diagnostic_threshold_bps": float(threshold_bps),
        "diagnostic_window_ms": int(window_ms),
        "diagnostic_cooldown_ms": int(cooldown_ms),
        "max_executable_delay_ms": int(max_delay_ms),
        "economic_threshold_changed": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DIAGNOSTIC_THRESHOLD_BPS",
    "MAX_EXECUTABLE_DELAY_MS",
    "diagnose_causal_book_coverage",
]
