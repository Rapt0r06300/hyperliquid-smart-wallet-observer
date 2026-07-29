"""Small, strict helpers for paper-accounting truth.

The live UI, replay jobs, and reports must agree on the same accounting
vocabulary.  This module deliberately contains no strategy decisions and no
network access.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

ACCOUNTING_SCHEMA_VERSION = "HS_ACCOUNTING_V2"


def first_not_none(*values: T | None) -> T | None:
    """Return the first present value while preserving legitimate zeroes."""

    for value in values:
        if value is not None:
            return value
    return None


def finite_number(value: object) -> float | None:
    """Parse a finite number; unknown and non-finite values stay unknown."""

    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def separate_entry_cost_usdc(position: dict[str, Any]) -> float | None:
    """Return the still-unrealized entry cost carried by a paper position.

    ``0`` is returned only when the entry cost is explicitly embedded in the
    recorded entry price or an explicit zero cost is present. Missing cost
    evidence stays ``None`` so callers cannot silently turn an unknown cost
    into free execution.
    """

    if position.get("fee_already_embedded_in_entry_price") is True:
        return 0.0
    raw_cost = first_not_none(
        position.get("entry_costs"),
        position.get("entry_cost_usdc"),
        position.get("entry_costs_usdc"),
    )
    cost = finite_number(raw_cost)
    if cost is None or cost < 0:
        return None
    return cost


def allocated_entry_cost_usdc(
    position: dict[str, Any],
    *,
    close_quantity: object,
    open_quantity: object,
) -> float | None:
    """Allocate a position's carried entry cost to an exact close quantity."""

    entry_cost = separate_entry_cost_usdc(position)
    close_size = finite_number(close_quantity)
    open_size = finite_number(open_quantity)
    if entry_cost is None or close_size is None or open_size is None:
        return None
    close_size = abs(close_size)
    open_size = abs(open_size)
    if open_size <= 0 or close_size < 0 or close_size > open_size + 1e-12:
        return None
    return entry_cost * min(1.0, close_size / open_size)


def round_trip_net_pnl_usdc(
    *,
    gross_pnl_usdc: object,
    entry_cost_usdc: object,
    exit_cost_usdc: object,
    funding_cost_usdc: object = 0.0,
) -> float | None:
    """Compute net paper PnL only when every requested component is known."""

    gross = finite_number(gross_pnl_usdc)
    entry = finite_number(entry_cost_usdc)
    exit_cost = finite_number(exit_cost_usdc)
    funding = finite_number(funding_cost_usdc)
    if None in (gross, entry, exit_cost, funding):
        return None
    assert gross is not None
    assert entry is not None
    assert exit_cost is not None
    assert funding is not None
    if entry < 0 or exit_cost < 0:
        return None
    return gross - entry - exit_cost - funding


@dataclass(frozen=True, slots=True)
class NamedRoiMetrics:
    pnl_usdc: float
    roi_on_initial_capital_pct: float | None
    roi_on_peak_margin_pct: float | None
    roi_on_average_capital_at_risk_pct: float | None
    initial_capital_usdc: float
    peak_margin_usdc: float | None
    average_capital_at_risk_usdc: float | None

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


def named_roi_metrics(
    *,
    pnl_usdc: object,
    initial_capital_usdc: object,
    peak_margin_usdc: object | None = None,
    average_capital_at_risk_usdc: object | None = None,
) -> NamedRoiMetrics:
    """Compute only explicitly named ROI denominators.

    A missing or invalid denominator produces ``None``.  In particular,
    ``initial capital - cash`` is never substituted for deployed capital.
    """

    pnl = finite_number(pnl_usdc)
    initial = finite_number(initial_capital_usdc)
    peak = finite_number(peak_margin_usdc)
    average = finite_number(average_capital_at_risk_usdc)
    if pnl is None:
        raise ValueError("pnl_usdc must be finite")
    if initial is None or initial <= 0:
        raise ValueError("initial_capital_usdc must be finite and positive")

    def ratio(denominator: float | None) -> float | None:
        if denominator is None or denominator <= 0:
            return None
        return round(pnl / denominator * 100.0, 10)

    return NamedRoiMetrics(
        pnl_usdc=pnl,
        roi_on_initial_capital_pct=ratio(initial),
        roi_on_peak_margin_pct=ratio(peak),
        roi_on_average_capital_at_risk_pct=ratio(average),
        initial_capital_usdc=initial,
        peak_margin_usdc=peak,
        average_capital_at_risk_usdc=average,
    )


def read_session_starting_equity(state_path: Path) -> float | None:
    """Read the declared session baseline without inventing a default."""

    try:
        payload: Any = json.loads(Path(state_path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = finite_number(payload.get("simulation_starting_equity_usdt"))
    return value if value is not None and value > 0 else None


__all__ = [
    "ACCOUNTING_SCHEMA_VERSION",
    "NamedRoiMetrics",
    "allocated_entry_cost_usdc",
    "finite_number",
    "first_not_none",
    "named_roi_metrics",
    "read_session_starting_equity",
    "round_trip_net_pnl_usdc",
    "separate_entry_cost_usdc",
]
