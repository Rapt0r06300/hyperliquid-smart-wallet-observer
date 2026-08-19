from __future__ import annotations

import importlib

import pytest


SAFE_MODULES = (
    "hl_observer.backtest.monte_carlo",
    "hl_observer.backtest.replay_engine",
    "hl_observer.backtesting.hyperopt_local",
    "hl_observer.backtesting.lookahead_analysis",
    "hl_observer.clusters.cluster_signal_score",
    "hl_observer.clusters.wallet_clusterer",
    "hl_observer.connectors.connector_base",
    "hl_observer.connectors.market_data_connector",
    "hl_observer.connectors.read_only_market_connector",
    "hl_observer.copy_wallet.multi_trader_runtime",
    "hl_observer.dashboard.risk_flags_panel",
    "hl_observer.explorer.explorer_dom_extractor",
    "hl_observer.explorer.explorer_rate_budget",
    "hl_observer.following.leaderboard_follow_shortlist",
    "hl_observer.following.position_follower",
    "hl_observer.gateway.local_source_gateway",
    "hl_observer.hyperliquid.ws_client",
    "hl_observer.monitoring.monitor_output",
    "hl_observer.paper.latency_model",
    "hl_observer.paper_trading.liquidity_route_simulator",
    "hl_observer.reports.daily_report",
    "hl_observer.reports.paper_report",
    "hl_observer.runtime.graceful_shutdown",
    "hl_observer.runtime.research_path",
    "hl_observer.runtime.safe_mode",
    "hl_observer.signals.signal_builder",
    "hl_observer.testnet.testnet_reconciliation",
    "hl_observer.universe.blacklist",
    "hl_observer.universe.dynamic_whitelist",
    "hl_observer.validation.bootstrap",
    "hl_observer.validation.testnet_tournament",
    "hl_observer.wallets.degradation",
    "hl_observer.wallets.leaderboard_dom_extractor",
    "hl_observer.wallets.leaderboard_importer",
    "hl_observer.wallets.profiler",
    "hl_observer.wallets.scan_limits",
    "hl_observer.wallets.scan_progress",
    "hl_observer.wallets.scan_scheduler",
    "hl_observer.wallets.toxicity",
)


@pytest.mark.parametrize("module_name", SAFE_MODULES)
def test_small_module_import_contract(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__name__ == module_name
