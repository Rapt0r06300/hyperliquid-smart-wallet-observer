from __future__ import annotations

from hyper_smart_observer.backtesting.replay_engine import ReplayEngine
from hyper_smart_observer.backtesting.runtime_parity import (
    assert_runtime_parity,
    build_runtime_parity_contract,
)
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps
from hyper_smart_observer.hyperliquid_client import models as common_data_model
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.risk_engine.gates import evaluate_paper_intent


def test_backtest_runtime_parity_same_models():
    contract = assert_runtime_parity()

    assert ReplayEngine.common_data_model is common_data_model
    assert ReplayEngine.edge_calculator is compute_edge_remaining_bps
    assert ReplayEngine.risk_gate is evaluate_paper_intent
    assert ReplayEngine.paper_engine_cls is PaperTradingSimulator
    assert contract.read_only is True
    assert contract.paper_only is True


def test_backtest_runtime_parity_contract_names_are_stable():
    contract = build_runtime_parity_contract()

    assert contract.common_data_model_module == "hyper_smart_observer.hyperliquid_client.models"
    assert contract.edge_calculator.endswith("compute_edge_remaining_bps")
    assert contract.risk_gate.endswith("evaluate_paper_intent")
    assert contract.paper_engine.endswith("PaperTradingSimulator")
    assert contract.replay_engine.endswith("ReplayEngine")

