"""Economic cost receipts for the queue-aware Lead-Lag replay."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl_observer.economics.assumptions import CostComponentReceipt, ZeroCostReason


def maker_cost_receipts(
    row: Mapping[str, Any], *, reality_model_version: str
) -> dict[str, dict[str, Any]]:
    """Build canonical receipts for one maker-entry/taker-exit paper row."""

    fees = float(row.get("fees_usd") or 0.0)
    spread = float(row.get("spread_cost_usd") or 0.0)
    slippage = float(row.get("slippage_cost_usd") or 0.0)
    latency = float(row.get("latency_cost_usd") or 0.0)
    return {
        "fees": CostComponentReceipt(
            component="fees",
            amount_usd=fees,
            zero_reason=ZeroCostReason.MEASURED_ZERO if fees == 0.0 else None,
            formula_id="lead_lag.maker_entry_taker_exit_fee.v1",
            reality_model_version=reality_model_version,
            provenance_ids=(
                "fee.maker.hyperliquid.bps",
                "fee.taker.hyperliquid.bps",
                "lead_lag.paper_notional_usd",
            ),
        ).as_dict(),
        "spread": CostComponentReceipt(
            component="spread",
            amount_usd=spread,
            zero_reason=ZeroCostReason.MEASURED_ZERO if spread == 0.0 else None,
            formula_id="lead_lag.maker_entry_taker_exit_spread.v1",
            reality_model_version=reality_model_version,
            provenance_ids=("entry_book.bid_ask", "exit_book.bid_ask"),
        ).as_dict(),
        "slippage": CostComponentReceipt(
            component="slippage",
            amount_usd=slippage,
            zero_reason=ZeroCostReason.MEASURED_ZERO if slippage == 0.0 else None,
            formula_id="lead_lag.full_fifo_and_top_capacity.v1",
            reality_model_version=reality_model_version,
            provenance_ids=("initial_qty_ahead", "queue_traded_qty", "exit_top_capacity_usd"),
        ).as_dict(),
        "latency": CostComponentReceipt(
            component="latency",
            amount_usd=latency,
            zero_reason=ZeroCostReason.EMBEDDED_IN_EXECUTABLE_PRICE if latency == 0.0 else None,
            formula_id="lead_lag.frozen_measured_p95_entry.v1",
            reality_model_version=reality_model_version,
            provenance_ids=("latency_evidence_sha256", "entry_book_ts_ms"),
        ).as_dict(),
    }


__all__ = ["maker_cost_receipts"]
