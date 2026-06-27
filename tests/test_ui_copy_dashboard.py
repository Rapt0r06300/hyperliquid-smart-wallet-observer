from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import Fill, FollowDecision, PositionDeltaModel, TopWallet
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


def _client_and_db(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'copy_ui.sqlite3'}"
    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    state = UiState()
    state.simulation_started_at_ms = 0
    return TestClient(create_ui_app(settings, state)), factory


def _seed_copy_rows(factory):
    with factory() as session:
        session.add(
            TopWallet(
                wallet_address="0x" + "3" * 40,
                rank=1,
                source="leaderboard",
                score=91.0,
                selected_at_ms=1_000,
                status="selected",
                notes="accepted_for_paper_copy_research",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "3" * 40,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=2.0,
                new_size=2.0,
                delta_size=2.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=1_000,
                side="long",
                price=2_500.0,
                fill_size=2.0,
                delta_type="open_long",
                confidence_score=0.9,
                detected_at_ms=1_000,
                delta_hash="open-eth",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "3" * 40,
                coin="ETH",
                previous_side="long",
                new_side="long",
                previous_size=2.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=-1.0,
                delta_notional_usdc=2_500.0,
                action="REDUCE",
                exchange_ts=2_000,
                side="long",
                price=2_500.0,
                fill_size=1.0,
                delta_type="reduce_long",
                confidence_score=0.9,
                detected_at_ms=2_000,
                delta_hash="reduce-eth",
            )
        )
        session.add(
            FollowDecision(
                signal_id="copy:test",
                decision="REJECT_EDGE_TOO_SMALL",
                allowed=False,
                reasons_json=["edge_remaining_bps below minimum"],
                risk_level="OBSERVE_ONLY",
                computed_at_ms=3_000,
            )
        )
        session.commit()


def test_ui_copy_status_endpoint_is_read_only(tmp_path):
    client, factory = _client_and_db(tmp_path)
    _seed_copy_rows(factory)

    payload = client.get("/api/copy/status").json()

    assert payload["mode"] == "PAPER_MOCK_USDC"
    assert payload["dry_run_only"] is True
    assert payload["no_real_orders"] is True
    assert payload["no_testnet_executor"] is True
    assert payload["edge_remaining_bps_required"] is True
    assert payload["target_leaders"] == 50
    assert payload["leaders_count"] == 1


def test_ui_copy_leader_activity_shows_delta_classes(tmp_path):
    client, factory = _client_and_db(tmp_path)
    _seed_copy_rows(factory)

    rows = client.get("/api/copy/leader-activity").json()
    actions = {row["action"] for row in rows}

    assert {"OPEN_LONG", "REDUCE"} <= actions
    assert any(row["copyable"] for row in rows if row["action"] == "OPEN_LONG")
    assert not any(row["copyable"] for row in rows if row["action"] == "REDUCE")


def test_ui_copy_leader_activity_bounds_leader_query_for_sqlite(tmp_path):
    client, factory = _client_and_db(tmp_path)
    with factory() as session:
        for index in range(1_200):
            session.add(
                TopWallet(
                    wallet_address=f"0x{index + 1:040x}",
                    rank=index + 1,
                    source="public_trades_ws",
                    score=float(2_000 - index),
                    selected_at_ms=1_000 + index,
                    status="selected",
                    notes="stress sqlite variable bound",
                )
            )
        session.add(
            PositionDeltaModel(
                wallet_address=f"0x{1:040x}",
                coin="BTC",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=1_000.0,
                action="OPEN",
                exchange_ts=1_000,
                side="long",
                price=50_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.9,
                detected_at_ms=1_000,
                delta_hash="top-leader-delta",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=f"0x{1_199:040x}",
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=1_000.0,
                action="OPEN",
                exchange_ts=2_000,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.9,
                detected_at_ms=2_000,
                delta_hash="non-shortlisted-delta",
            )
        )
        session.commit()

    rows = client.get("/api/copy/leader-activity?limit=50").json()

    assert any(row["wallet_address"] == f"0x{1:040x}" for row in rows)
    assert not any(row["wallet_address"] == f"0x{1_199:040x}" for row in rows)


def test_ui_copy_no_trade_report_explains_refusals(tmp_path):
    client, factory = _client_and_db(tmp_path)
    _seed_copy_rows(factory)

    payload = client.get("/api/copy/no-trade-report").json()
    reasons = {row["reason"] for row in payload["reasons"]}

    assert payload["dry_run_only"] is True
    assert payload["edge_remaining_bps_required"] is True
    assert "edge_remaining_bps below minimum" in reasons
    assert "leader_reduce_close_not_entry" in reasons


def test_ui_home_contains_copy_dry_run_sections(tmp_path):
    client, _factory = _client_and_db(tmp_path)

    html = client.get("/").text

    assert 'href="#simulationPanel"' in html
    assert "Simulation du bot - gain/perte" in html
    assert "Solde fictif actuel" in html
    assert "Gain/perte en cours" in html
    assert "Gain/perte encaisse" in html
    assert "Capital utilise" in html
    assert "Journal decisions" in html
    assert "Latent" not in html
    assert "/static/app.js?v=simulation-ui-" in html
    assert "Consensus positions" in html
    assert 'id="simulationDecisionTape"' in html
    assert 'id="simulationMetaGraph"' in html
    assert "Relancer la recherche" not in html
    assert "Copy dry-run / mock USDC" in html
    assert "No-trade report" in html
    assert "aucun ordre" in html.lower()


def test_ui_simulation_overview_explains_empty_state(tmp_path):
    client, _factory = _client_and_db(tmp_path)

    payload = client.get("/api/simulation/overview").json()

    assert payload["mode"] == "LOCAL_RESEARCH_SIMULATION_ONLY"
    assert payload["paper_mock_usdc_only"] is True
    assert payload["no_real_orders"] is True
    assert payload["readiness"] == "IMPORT_OR_DISCOVERY_REQUIRED"
    assert payload["counts"]["leaders"] == 0
    assert payload["counts"]["target_leaders"] == 50
    assert payload["scanner"]["active"] is True
    assert payload["scanner"]["target_wallets"] == 50
    assert payload["autopilot"]["active_while_command_center_runs"] is True
    assert payload["autopilot"]["execution"] == "forbidden"
    assert payload["equity_candles"] == []
    assert payload["decision_log_pnl"]["read_only"] is True
    assert payload["pnl_consistency"]["scope_note"]
    assert any(row["reason"] == "NO_LEADER_WALLET_IMPORTED" for row in payload["no_trade_reasons"])


def test_ui_simulation_overview_detects_multi_wallet_consensus(tmp_path):
    client, factory = _client_and_db(tmp_path)
    base_ms = now_ms() + 1_000
    with factory() as session:
        session.add(
            TopWallet(
                wallet_address="0x" + "1" * 40,
                rank=1,
                source="leaderboard",
                score=94.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(
            TopWallet(
                wallet_address="0x" + "1" * 40,
                rank=1,
                source="leaderboard_duplicate",
                score=94.0,
                selected_at_ms=1_001,
                status="selected",
                notes="duplicate_should_be_deduped",
            )
        )
        session.add(
            TopWallet(
                wallet_address="0x" + "2" * 40,
                rank=2,
                source="leaderboard",
                score=88.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "1" * 40,
                coin="BTC",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=1000.0,
                action="OPEN",
                exchange_ts=base_ms,
                side="long",
                price=65000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.9,
                detected_at_ms=base_ms,
                delta_hash="sim-open-btc-1",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "2" * 40,
                coin="BTC",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=2.0,
                new_size=2.0,
                delta_size=2.0,
                delta_notional_usdc=2000.0,
                action="OPEN",
                exchange_ts=base_ms + 1_000,
                side="long",
                price=65010.0,
                fill_size=2.0,
                delta_type="open_long",
                confidence_score=0.9,
                detected_at_ms=base_ms + 1_000,
                delta_hash="sim-open-btc-2",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "1" * 40,
                coin="BTC",
                previous_side="long",
                new_side=None,
                previous_size=1.0,
                current_size=0.0,
                new_size=0.0,
                delta_size=-1.0,
                delta_notional_usdc=1000.0,
                action="CLOSE",
                exchange_ts=base_ms + 2_000,
                side="long",
                price=65100.0,
                fill_size=1.0,
                delta_type="close_long",
                confidence_score=0.9,
                detected_at_ms=base_ms + 2_000,
                delta_hash="sim-close-btc-1",
            )
        )
        session.add(
            Fill(
                wallet_address="0x" + "1" * 40,
                coin="BTC",
                exchange_ts=base_ms + 500,
                side="long",
                price=65050.0,
                size=1.0,
                fill_hash="fill-positive",
                oid="oid-positive",
                tid="tid-positive",
                direction="Close Long",
                start_position=1.0,
                closed_pnl=14.0,
                fee=0.2,
                raw_json={"fixture": "positive"},
            )
        )
        session.add(
            Fill(
                wallet_address="0x" + "2" * 40,
                coin="BTC",
                exchange_ts=base_ms + 1_500,
                side="long",
                price=65020.0,
                size=1.0,
                fill_hash="fill-negative",
                oid="oid-negative",
                tid="tid-negative",
                direction="Close Long",
                start_position=1.0,
                closed_pnl=-4.0,
                fee=0.2,
                raw_json={"fixture": "negative"},
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview").json()

    assert payload["readiness"] == "RESEARCH_SIMULATION_READY"
    assert payload["counts"]["leaders"] == 2
    assert len(payload["leaders"]) == 2
    assert payload["counts"]["entry_deltas"] == 2
    assert payload["counts"]["consensus_positions"] == 1
    assert payload["scanner"]["fresh_consensus_window_seconds"] == 4
    assert payload["signal_pipeline"]["fresh_consensus_groups_4s"] == 1
    assert payload["signal_pipeline"]["local_entries_accepted"] == 1
    assert payload["fresh_data_coverage"]["fresh_window_seconds"] >= 20
    assert payload["fresh_data_coverage"]["fresh_position_deltas"] >= 3
    assert payload["fresh_data_coverage"]["fresh_entry_deltas"] >= 2
    assert payload["counts"]["closed_pnl_points"] == 2
    assert payload["counts"]["reproduced_entries"] == 1
    assert payload["counts"]["reproduced_exits"] == 1
    assert payload["counts"]["bot_decision_events"] == 2
    assert payload["equity"]["source"] == "fresh bot virtual portfolio simulation from deltas detected after simulation start"
    assert payload["pnl_consistency"]["ok"] is True
    assert payload["pnl_consistency"]["recomputed_equity_usdt"] == payload["equity"]["current_equity_usdt"]
    assert payload["loss_diagnostics"]["execution"] == "forbidden"
    assert payload["loss_diagnostics"]["profit_guarantee"] is False
    assert len(payload["equity_candles"]) >= 3
    assert payload["equity_candles"][-1]["source"] == "MARK_TO_MARKET"
    assert {row["color"] for row in payload["equity_candles"]} <= {"green", "red"}
    assert "red" in {row["color"] for row in payload["equity_candles"]}
    assert payload["bot_simulation"]["estimated_net_pnl_usdc"] != 0
    assert payload["bot_simulation"]["realized_net_pnl_usdc"] != 0
    assert "open_positions" in payload["bot_simulation"]
    assert payload["bot_simulation"]["magic_profile"]["execution"] == "forbidden"
    assert payload["bot_simulation"]["magic_profile"]["min_edge_required_bps"] == 15.0
    assert payload["bot_simulation"]["magic_profile"]["max_signal_age_seconds"] == 15
    assert payload["bot_simulation"]["magic_profile"]["holding_policy"].startswith("hold_until_matching_leader_reduce_or_close")
    assert payload["bot_simulation"]["magic_profile"]["red_pnl_exit_policy"] == "never_exit_only_because_unrealized_pnl_is_negative"
    assert all(row["edge_remaining_bps"] is not None for row in payload["bot_simulation"]["events"])
    assert any(row["bot_replay_action"] == "PAPER_CONSENSUS_ENTRY_REPLAYED" for row in payload["bot_simulation"]["events"])
    assert not any(row["bot_replay_action"] == "CONSENSUS_DUPLICATE_IGNORED" for row in payload["bot_simulation"]["events"])
    assert any(row["bot_replay_action"] == "PAPER_CONSENSUS_CLOSE_REPLAYED" for row in payload["bot_simulation"]["events"])
    assert payload["consensus"][0]["coin"] == "BTC"
    assert payload["consensus"][0]["direction"] == "LONG"
    assert payload["consensus"][0]["wallet_count"] == 2
    assert payload["no_profit_guarantee"] is True


def test_ui_simulation_ignores_old_db_deltas_before_start_timestamp(tmp_path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'copy_ui_zero.sqlite3'}"
    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    state = UiState()
    state.simulation_started_at_ms = 10_000
    client = TestClient(create_ui_app(settings, state))
    with factory() as session:
        session.add(
            TopWallet(
                wallet_address="0x" + "4" * 40,
                rank=1,
                source="leaderboard",
                score=91.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "4" * 40,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=2000.0,
                action="OPEN",
                exchange_ts=1_000,
                side="long",
                price=2000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.9,
                detected_at_ms=1_000,
                delta_hash="old-delta-before-simulation-start",
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview").json()

    assert payload["starting_equity_usdt"] == 1000.0
    assert payload["virtual_quote_asset"] == "USDT"
    assert payload["counts"]["deltas"] == 0
    assert payload["counts"]["live_simulation_deltas"] == 0
    assert payload["counts"]["old_deltas_ignored_fresh_only"] == 0
    assert payload["counts"]["bot_decision_events"] == 0
    assert payload["readiness"] == "BACKFILL_OR_COPY_LOOP_REQUIRED"
