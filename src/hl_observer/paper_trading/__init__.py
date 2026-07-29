"""Public paper-trading helpers.

The package intentionally keeps this module lightweight. Some risk guards import
``hl_observer.paper_trading.exec_model`` from hot paths; importing every paper
helper here would also import risk modules back and can create circular imports.
Heavy helpers are therefore exposed lazily through ``__getattr__`` while the
public API stays compatible with ``from hl_observer.paper_trading import ...``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from hl_observer.paper_trading.exec_model import (
    BookLevelFill,
    DepthExecutionResult,
    ExecModelConfig,
    ExecResult,
    estimate_slippage_bps,
    round_trip_cost_bps,
    simulate_depth_execution,
    simulate_execution,
)
from hl_observer.paper_trading.paper_engine import (
    PaperDecisionResult,
    PaperEngine,
    PaperEngineConfig,
    PaperPosition,
    PaperTrade,
)

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "LiquidityConsumptionLedger": (
        "hl_observer.paper_trading.liquidity_consumption",
        "LiquidityConsumptionLedger",
    ),
    "PaperSimConnector": ("hl_observer.paper_trading.paper_connector", "PaperSimConnector"),
    "PaperSimConnectorResult": ("hl_observer.paper_trading.paper_connector", "PaperSimConnectorResult"),
    "PaperSimFill": ("hl_observer.paper_trading.paper_connector", "PaperSimFill"),
    "can_buy_amount_usdt": ("hl_observer.paper_trading.can_buy_amount_simulator", "can_buy_amount_usdt"),
    "can_sell_amount_usdt": ("hl_observer.paper_trading.can_buy_amount_simulator", "can_sell_amount_usdt"),
    "DeltaNeutralPosition": ("hl_observer.paper_trading.delta_neutral_position", "DeltaNeutralPosition"),
    "build_delta_neutral_position": ("hl_observer.paper_trading.delta_neutral_position", "build_delta_neutral_position"),
    "FundingPayment": ("hl_observer.paper_trading.funding_payment_tracker", "FundingPayment"),
    "compute_funding_payment": ("hl_observer.paper_trading.funding_payment_tracker", "compute_funding_payment"),
    "HedgeReconciliation": ("hl_observer.paper_trading.hedge_reconciliation", "HedgeReconciliation"),
    "reconcile_hedge_legs": ("hl_observer.paper_trading.hedge_reconciliation", "reconcile_hedge_legs"),
    "LiquidityRoute": ("hl_observer.paper_trading.liquidity_route_simulator", "LiquidityRoute"),
    "simulate_liquidity_route": ("hl_observer.paper_trading.liquidity_route_simulator", "simulate_liquidity_route"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

__all__ = [
    "ExecModelConfig",
    "ExecResult",
    "BookLevelFill",
    "DepthExecutionResult",
    "DeltaNeutralPosition",
    "FundingPayment",
    "HedgeReconciliation",
    "LiquidityRoute",
    "LiquidityConsumptionLedger",
    "PaperDecisionResult",
    "PaperEngine",
    "PaperEngineConfig",
    "PaperPosition",
    "PaperSimConnector",
    "PaperSimConnectorResult",
    "PaperSimFill",
    "PaperTrade",
    "build_delta_neutral_position",
    "can_buy_amount_usdt",
    "can_sell_amount_usdt",
    "compute_funding_payment",
    "estimate_slippage_bps",
    "reconcile_hedge_legs",
    "round_trip_cost_bps",
    "simulate_depth_execution",
    "simulate_execution",
    "simulate_liquidity_route",
]
