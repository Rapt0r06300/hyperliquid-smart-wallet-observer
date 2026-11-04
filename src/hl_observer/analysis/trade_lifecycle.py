from __future__ import annotations

import math
from statistics import median
from typing import Any

from pydantic import BaseModel


class TradeLifecycle(BaseModel):
    wallet_address: str
    coin: str
    side: str | None = None
    status: str = "OPEN"
    realized_pnl_usdc: float | None = None
    confidence_score: float = 0.0
    native_trade_id: str | None = None
    source: str | None = None
    wallet_identity_proven: bool = False
    paper_eligible: bool = False
    refusal_reason: str | None = None


def classify_trade_lifecycle(
    *,
    wallet_address: str,
    coin: str,
    action: str,
    native_trade_id: Any,
    source: Any,
    wallet_identity_proven: Any,
    confidence_score: Any = 0.0,
    realized_pnl_usdc: Any = None,
) -> TradeLifecycle:
    """Create a fail-closed lifecycle record for completed public fills.

    An order/cancellation, an unproven wallet identity, or a missing native
    trade id is never promoted to a paper trade.  PnL is retained only as
    metadata and never made eligible by itself.
    """

    action_text = str(action or "").strip().upper()
    source_text = str(source or "").strip()
    trade_id = str(native_trade_id).strip() if native_trade_id is not None else ""
    try:
        confidence = float(confidence_score)
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        confidence = 0.0
    pnl: float | None
    if realized_pnl_usdc is None:
        pnl = None
    else:
        try:
            candidate = float(realized_pnl_usdc)
        except (TypeError, ValueError):
            candidate = math.nan
        pnl = candidate if math.isfinite(candidate) else None

    reason: str | None = None
    if not trade_id:
        reason = "NATIVE_TRADE_ID_MISSING"
    elif source_text not in {"user_fills", "public_fills", "live_user_fills"}:
        reason = "TRADE_SOURCE_UNAUTHENTICATED"
    elif wallet_identity_proven is not True:
        reason = "WALLET_IDENTITY_UNPROVEN"
    elif action_text in {"ORDER", "OPEN_ORDER", "CANCEL", "CANCELLED", "CANCELED"}:
        reason = "NON_TRADE_EVENT"
    elif confidence < 0.7:
        reason = "TRADE_CONFIDENCE_INSUFFICIENT"

    return TradeLifecycle(
        wallet_address=str(wallet_address).strip().lower(),
        coin=str(coin).strip().upper(),
        action=action_text or "UNKNOWN",
        status="OPEN" if reason is None else "UNMEASURABLE",
        realized_pnl_usdc=pnl,
        confidence_score=confidence,
        native_trade_id=trade_id or None,
        source=source_text or None,
        wallet_identity_proven=wallet_identity_proven is True,
        paper_eligible=reason is None,
        refusal_reason=reason,
    )


def robust_leader_score(
    pnl_observations: list[Any], *, min_observations: int = 3, trim_fraction: float = 0.2
) -> dict[str, Any]:
    """Bound a leader score so one exceptional gain cannot dominate it."""

    if isinstance(min_observations, bool) or min_observations < 1:
        return {"status": "UNMEASURABLE", "score": None, "reason": "MIN_OBSERVATIONS_INVALID"}
    try:
        trim = float(trim_fraction)
    except (TypeError, ValueError):
        trim = math.nan
    if not math.isfinite(trim) or trim < 0 or trim >= 0.5:
        return {"status": "UNMEASURABLE", "score": None, "reason": "TRIM_FRACTION_INVALID"}
    values: list[float] = []
    for item in pnl_observations:
        try:
            value = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    if len(values) < min_observations:
        return {"status": "UNMEASURABLE", "score": None, "reason": "INSUFFICIENT_OBSERVATIONS"}
    values.sort()
    trim_count = int(len(values) * trim)
    retained = values[trim_count: len(values) - trim_count] or values
    return {
        "status": "PROVEN",
        "score": float(median(retained)),
        "observations": len(values),
        "retained_observations": len(retained),
        "aggregation": "MEDIAN_TRIMMED",
        "paper_read_only": True,
    }


def pre_entry_score(
    observations: list[dict[str, Any]], *, entry_ts_ms: Any
) -> dict[str, Any]:
    """Score only evidence available at/before entry; post-entry PnL is excluded."""

    try:
        cutoff = int(entry_ts_ms)
    except (TypeError, ValueError):
        return {"status": "UNMEASURABLE", "reason": "ENTRY_TIMESTAMP_INVALID", "values": []}
    if cutoff < 0:
        return {"status": "UNMEASURABLE", "reason": "ENTRY_TIMESTAMP_INVALID", "values": []}
    values: list[float] = []
    for row in observations:
        if not isinstance(row, dict) or row.get("timestamp_ms") is None:
            continue
        try:
            timestamp = int(row["timestamp_ms"])
            value = float(row["pnl_usdc"])
        except (TypeError, ValueError):
            continue
        if timestamp <= cutoff and math.isfinite(value):
            values.append(value)
    return {"status": "PROVEN", "values": values, "excluded_post_entry": True, "entry_ts_ms": cutoff}


def aggregate_partial_fills(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate only native-identified partial fills while preserving quantity."""

    grouped: dict[str, dict[str, float]] = {}
    for fill in fills:
        native_id = next((fill.get(key) for key in ("oid", "order_id", "orderId", "tid", "tradeId") if fill.get(key) is not None), None)
        if native_id is None:
            return {"status": "UNMEASURABLE", "reason": "NATIVE_FILL_ID_MISSING", "groups": {}}
        try:
            quantity = abs(float(fill.get("sz", fill.get("size"))))
            price = float(fill.get("px", fill.get("price")))
        except (TypeError, ValueError):
            return {"status": "UNMEASURABLE", "reason": "PARTIAL_FILL_NUMERIC_INVALID", "groups": {}}
        if not math.isfinite(quantity) or quantity <= 0 or not math.isfinite(price) or price <= 0:
            return {"status": "UNMEASURABLE", "reason": "PARTIAL_FILL_NUMERIC_INVALID", "groups": {}}
        key = str(native_id)
        state = grouped.setdefault(key, {"quantity": 0.0, "notional": 0.0, "parts": 0.0})
        state["quantity"] += quantity
        state["notional"] += quantity * price
        state["parts"] += 1.0
    for state in grouped.values():
        state["vwap"] = state["notional"] / state["quantity"]
    return {"status": "PROVEN", "groups": grouped, "paper_read_only": True}


def reconcile_fill_position(*, previous_size: Any, fills_delta: Any, observed_size: Any, tolerance: float = 1e-9) -> dict[str, Any]:
    """Require exact finite quantities before declaring fills and position coherent."""

    try:
        previous = float(previous_size)
        delta = float(fills_delta)
        observed = float(observed_size)
        tol = float(tolerance)
    except (TypeError, ValueError):
        return {"status": "UNMEASURABLE", "reconciled": False, "reason": "POSITION_NUMERIC_INVALID"}
    if any(not math.isfinite(value) for value in (previous, delta, observed, tol)) or tol < 0:
        return {"status": "UNMEASURABLE", "reconciled": False, "reason": "POSITION_NUMERIC_INVALID"}
    reconciled = abs(previous + delta - observed) <= tol
    return {"status": "PROVEN", "reconciled": reconciled, "reason": "POSITION_MATCH" if reconciled else "POSITION_MISMATCH", "paper_read_only": True}


def wallet_activity_gate(*, last_seen_ms: Any, now_ms: Any, max_age_ms: Any) -> dict[str, Any]:
    try:
        last_seen = int(last_seen_ms)
        now = int(now_ms)
        max_age = int(max_age_ms)
    except (TypeError, ValueError):
        return {"status": "UNMEASURABLE", "active": False, "reason": "ACTIVITY_TIMESTAMP_INVALID"}
    active = last_seen >= 0 and now >= last_seen and max_age >= 0 and now - last_seen <= max_age
    return {"status": "PROVEN", "active": active, "reason": "ACTIVE" if active else "INACTIVE", "paper_read_only": True}


def rankable_trade_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude deposits/withdrawals/transfers from trading-leader ranking inputs."""

    excluded = {"deposit", "withdrawal", "transfer", "funding_transfer", "balance_update"}
    allowed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("event_kind", row.get("type", "")) or "").strip().casefold()
        if kind in excluded:
            continue
        if kind and kind not in {"fill", "trade", "user_fill", "public_fill"}:
            continue
        if next((row.get(key) for key in ("tid", "tradeId", "trade_id", "id") if row.get(key) is not None), None) is None:
            continue
        allowed.append(row)
    return allowed


def close_paper_gate(*, has_paper_position: Any, native_trade_id: Any) -> dict[str, Any]:
    allowed = has_paper_position is True and bool(str(native_trade_id or "").strip())
    return {"status": "PROVEN", "paper_eligible": allowed, "reason": "OK" if allowed else "PAPER_POSITION_OR_ID_MISSING"}


def cycle_event_admission(*, event_cycle: Any, current_cycle: Any, phase_epoch: Any = None, current_phase_epoch: Any = None) -> dict[str, Any]:
    if event_cycle is None or current_cycle is None:
        return {"status": "UNMEASURABLE", "admitted": False, "reason": "CYCLE_ID_MISSING"}
    if event_cycle != current_cycle:
        return {"status": "PROVEN", "admitted": False, "reason": "STALE_CYCLE"}
    if phase_epoch is not None and current_phase_epoch is not None and phase_epoch != current_phase_epoch:
        return {"status": "PROVEN", "admitted": False, "reason": "STALE_PHASE_EPOCH"}
    return {"status": "PROVEN", "admitted": True, "reason": "CURRENT_CYCLE"}


__all__ = [
    "TradeLifecycle", "aggregate_partial_fills", "classify_trade_lifecycle",
    "close_paper_gate", "cycle_event_admission", "pre_entry_score",
    "reconcile_fill_position", "robust_leader_score", "wallet_activity_gate",
    "rankable_trade_observations",
]
