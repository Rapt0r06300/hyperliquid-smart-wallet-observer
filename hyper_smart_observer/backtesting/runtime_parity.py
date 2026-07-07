from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.backtesting.replay_engine import ReplayEngine
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps
from hyper_smart_observer.hyperliquid_client import models as common_data_model
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.risk_engine.gates import evaluate_paper_intent


@dataclass(frozen=True)
class RuntimeParityContract:
    common_data_model_module: str
    edge_calculator: str
    risk_gate: str
    paper_engine: str
    replay_engine: str
    read_only: bool = True
    paper_only: bool = True


def build_runtime_parity_contract() -> RuntimeParityContract:
    return RuntimeParityContract(
        common_data_model_module=common_data_model.__name__,
        edge_calculator=f"{compute_edge_remaining_bps.__module__}.{compute_edge_remaining_bps.__name__}",
        risk_gate=f"{evaluate_paper_intent.__module__}.{evaluate_paper_intent.__name__}",
        paper_engine=f"{PaperTradingSimulator.__module__}.{PaperTradingSimulator.__name__}",
        replay_engine=f"{ReplayEngine.__module__}.{ReplayEngine.__name__}",
    )


def assert_runtime_parity() -> RuntimeParityContract:
    """Verify replay uses the same local model/risk/edge/paper contracts."""

    if ReplayEngine.common_data_model is not common_data_model:
        raise AssertionError("ReplayEngine common data model diverges from runtime CDM")
    if ReplayEngine.edge_calculator is not compute_edge_remaining_bps:
        raise AssertionError("ReplayEngine edge calculator diverges from runtime edge calculator")
    if ReplayEngine.risk_gate is not evaluate_paper_intent:
        raise AssertionError("ReplayEngine risk gate diverges from runtime risk gate")
    if ReplayEngine.paper_engine_cls is not PaperTradingSimulator:
        raise AssertionError("ReplayEngine paper engine diverges from runtime paper engine")
    return build_runtime_parity_contract()
