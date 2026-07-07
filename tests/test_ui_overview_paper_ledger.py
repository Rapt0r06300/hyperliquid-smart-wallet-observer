from __future__ import annotations

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def test_simulation_overview_exposes_paper_ledger_and_links_equity_spikes(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    settings.logs_dir = tmp_path / "logs"
    init_db(settings.database_url)

    state = UiState()
    base_ms = 1_800_000_000_000
    state.simulation_started_at_ms = base_ms
    state.simulation_realized_pnl_usdc = 1.2
    state.simulation_equity_history = [
        {
            "timestamp_ms": base_ms,
            "current_pnl_usdc": 0.0,
            "current_equity_usdt": 1000.0,
            "realized_pnl_usdc": 0.0,
            "unrealized_pnl_usdc": 0.0,
            "source": "SESSION_START",
        },
        {
            "timestamp_ms": base_ms + 500,
            "current_pnl_usdc": 1.2,
            "current_equity_usdt": 1001.2,
            "realized_pnl_usdc": 1.2,
            "unrealized_pnl_usdc": 0.0,
            "source": "PAPER_CLOSE_REPLAYED",
        },
    ]
    state.simulation_ledger_events = [
        {
            "delta_key": "ledger-spike-close",
            "observed_at_ms": base_ms + 500,
            "wallet_address": "0x" + "5" * 40,
            "coin": "HYPE",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "paper_action_type": "CLOSE",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": 1.2,
            "fee_cost_usdc": 0.03,
            "evidence_hash": "ev:test-spike",
        }
    ]

    client = TestClient(create_ui_app(settings, state))
    payload = client.get("/api/simulation/overview?limit=5").json()

    assert payload["paper_ledger"]["source"] == "UI_STATE_LEDGER_PROJECTION"
    assert payload["paper_ledger"]["reconciliation"]["ok"] is True
    assert payload["bot_simulation"]["paper_ledger"]["reconciliation"]["ok"] is True
    spike_links = payload["graph_diagnostics"]["ledger_spike_links"]
    assert spike_links["spike_count"] >= 1
    assert spike_links["recent_spikes"][-1]["explained_by_nearby_ledger_event"] is True
    assert spike_links["recent_spikes"][-1]["nearby_ledger_events"][0]["delta_key"] == "ledger-spike-close"


def test_simulation_overview_keeps_no_trade_as_context_not_pnl_explanation(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    settings.logs_dir = tmp_path / "logs"
    init_db(settings.database_url)

    state = UiState()
    base_ms = 1_800_000_000_000
    state.simulation_started_at_ms = base_ms
    state.simulation_equity_history = [
        {
            "timestamp_ms": base_ms,
            "current_pnl_usdc": 0.0,
            "current_equity_usdt": 1000.0,
            "realized_pnl_usdc": 0.0,
            "unrealized_pnl_usdc": 0.0,
            "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
        },
        {
            "timestamp_ms": base_ms + 500,
            "current_pnl_usdc": -1.2,
            "current_equity_usdt": 998.8,
            "realized_pnl_usdc": 0.0,
            "unrealized_pnl_usdc": -1.2,
            "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
        },
    ]
    state.simulation_ledger_events = [
        {
            "delta_key": "overview-no-trade-context",
            "observed_at_ms": base_ms + 500,
            "wallet_address": "0x" + "6" * 40,
            "coin": "HYPE",
            "bot_replay_action": "NO_TRADE",
            "paper_action_type": "NO_TRADE",
            "status": "REJECT_NO_TRADE",
            "reason": "EDGE_REMAINING_TOO_LOW",
            "evidence_hash": "ev:no-trade-context",
        }
    ]

    client = TestClient(create_ui_app(settings, state))
    payload = client.get("/api/simulation/overview?limit=5").json()

    spike_links = payload["graph_diagnostics"]["ledger_spike_links"]
    spike = spike_links["recent_spikes"][-1]
    assert spike_links["spike_count"] >= 1
    assert spike_links["unexplained_spike_count"] >= 1
    assert spike["explained_by_nearby_ledger_event"] is False
    assert spike["nearby_ledger_events_count"] == 0
    assert spike["nearby_context_events"][0]["delta_key"] == "overview-no-trade-context"


def test_simulation_overview_explains_fast_mark_to_market_spike(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    settings.logs_dir = tmp_path / "logs"
    init_db(settings.database_url)

    state = UiState()
    base_ms = 1_800_000_000_000
    state.simulation_started_at_ms = base_ms
    state.simulation_equity_history = [
        {
            "timestamp_ms": base_ms,
            "current_pnl_usdc": 0.0,
            "current_equity_usdt": 1000.0,
            "realized_pnl_usdc": 0.0,
            "unrealized_pnl_usdc": 0.0,
            "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
            "open_positions": 3,
        },
        {
            "timestamp_ms": base_ms + 500,
            "current_pnl_usdc": 1.1,
            "current_equity_usdt": 1001.1,
            "realized_pnl_usdc": 0.0,
            "unrealized_pnl_usdc": 1.1,
            "source": "FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID",
            "open_positions": 3,
        },
    ]
    state.simulation_ledger_events = []

    client = TestClient(create_ui_app(settings, state))
    payload = client.get("/api/simulation/overview?limit=5").json()

    spike_links = payload["graph_diagnostics"]["ledger_spike_links"]
    spike = spike_links["recent_spikes"][-1]
    assert spike_links["spike_count"] >= 1
    assert spike_links["unexplained_spike_count"] == 0
    assert spike["explained_by_mark_to_market"] is True
    assert spike["explanation"] == "MARK_TO_MARKET_PRICE_MOVE_ON_OPEN_PAPER_POSITIONS"
