import json
from pathlib import Path

from hl_observer.runtime.fusion_heartbeat_input import (
    build_fusion_runtime_input_from_session,
    format_fusion_heartbeat_report,
    write_fusion_runtime_input_to_engine_status,
)
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketSnapshot, PositionDeltaModel, TopWallet


def _session_factory(tmp_path: Path):
    db_url = f"sqlite:///{(tmp_path / 'fusion_heartbeat.sqlite3').as_posix()}"
    init_db(db_url)
    return create_session_factory(create_sqlite_engine(db_url))


def test_fusion_heartbeat_input_refuses_without_recent_deltas(tmp_path: Path):
    factory = _session_factory(tmp_path)
    with factory() as session:
        report = build_fusion_runtime_input_from_session(session, current_ms=10_000)

    assert report.status == "NO_FRESH_DELTAS"
    assert report.fusion_runtime_input is None
    assert report.external_action is False
    assert "real_execution=false" in format_fusion_heartbeat_report(report)


def test_fusion_heartbeat_input_builds_from_recent_deltas_and_real_mids(tmp_path: Path):
    factory = _session_factory(tmp_path)
    now = 1_000_000
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    with factory() as session:
        session.add_all(
            [
                TopWallet(wallet_address=wallet_a, rank=1, source="public_trades_ws", score=95.0, selected_at_ms=now, status="selected"),
                TopWallet(wallet_address=wallet_b, rank=2, source="public_trades_ws", score=80.0, selected_at_ms=now, status="selected"),
                PositionDeltaModel(
                    wallet_address=wallet_a,
                    coin="HYPE",
                    previous_side=None,
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=2.0,
                    new_size=2.0,
                    delta_size=2.0,
                    delta_notional_usdc=140.0,
                    action="OPEN_LONG",
                    exchange_ts=now - 200,
                    side="LONG",
                    detected_at_ms=now - 100,
                    source="user_fills_ws",
                    confidence_score=95.0,
                    raw_json={
                        "edge_remaining_bps": 18.0,
                        "liquidity_score": 0.72,
                        "copy_degradation_bps": 9.0,
                        "source_profile": "distilled_whale_consensus",
                    },
                ),
                PositionDeltaModel(
                    wallet_address=wallet_b,
                    coin="HYPE",
                    previous_side=None,
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=1.0,
                    new_size=1.0,
                    delta_size=1.0,
                    delta_notional_usdc=70.0,
                    action="OPEN_LONG",
                    exchange_ts=now - 190,
                    side="LONG",
                    detected_at_ms=now - 90,
                    source="user_fills_ws",
                    confidence_score=80.0,
                    raw_json={
                        "net_edge_bps": 16.0,
                        "market_liquidity_score": 0.68,
                        "copy_cost_bps": 10.0,
                        "strategy_id": "distilled_whale_consensus",
                    },
                ),
                MarketSnapshot(source="allMids", exchange_ts=now - 50, raw_json={"HYPE": "70.25"}),
            ]
        )
        session.commit()
        report = build_fusion_runtime_input_from_session(
            session,
            current_ms=now,
            fresh_window_ms=5_000,
            starting_equity_usdt=1000.0,
            current_equity_usdt=987.5,
            peak_equity_usdt=1004.0,
            open_exposure_usdt=125.0,
        )

    assert report.status == "READY"
    assert report.votes_count == 2
    assert report.price_events_count == 1
    assert report.coins == ("HYPE",)
    payload = report.fusion_runtime_input
    assert payload is not None
    assert payload["read_only"] is True
    assert payload["external_action"] is False
    assert payload["leader_votes"][0]["coin"] == "HYPE"
    assert len(payload["distilled_signal_candidates"]) == 2
    by_wallet = {item["wallet"].lower(): item for item in payload["distilled_signal_candidates"]}
    assert by_wallet[wallet_a.lower()]["edge_remaining_bps"] == 18.0
    assert by_wallet[wallet_a.lower()]["liquidity_score"] == 0.72
    assert by_wallet[wallet_a.lower()]["copy_degradation_bps"] == 9.0
    assert by_wallet[wallet_b.lower()]["source_profile"] == "distilled_whale_consensus"
    assert payload["price_events"][0]["derived_bidask"] is True
    assert payload["price_events"][0]["mid_source"] == "Hyperliquid allMids local snapshot"
    assert payload["current_equity"] == 987.5
    assert payload["peak_equity"] == 1004.0
    assert payload["open_exposure_usdt"] == 125.0


def test_write_fusion_heartbeat_input_preserves_safety_flags_and_merges_metrics(tmp_path: Path):
    factory = _session_factory(tmp_path)
    now = 2_000_000
    wallet = "0x" + "c" * 40
    heartbeat = tmp_path / "hypersmart_engine_status.json"
    (tmp_path / "ui_simulation_state.json").write_text(
        json.dumps(
            {
                "simulation_starting_equity_usdt": 1000.0,
                "simulation_realized_pnl_usdc": -2.0,
                "simulation_equity_history": [
                    {"current_equity_usdt": 1000.0, "open_exposure_usdt": 0.0},
                    {"current_equity_usdt": 992.25, "open_exposure_usdt": 35.0},
                    {"current_equity_usdt": 997.5, "open_exposure_usdt": 20.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    heartbeat.write_text(
        json.dumps(
            {
                "updated_at_ms": now,
                "phase": "live_user_fills_scan",
                "read_only": True,
                "simulation_only": True,
                "external_action": False,
                "metrics": {"wallet_candidates_total": "12"},
            }
        ),
        encoding="utf-8",
    )
    with factory() as session:
        session.add(TopWallet(wallet_address=wallet, rank=1, source="leaderboard", score=90.0, selected_at_ms=now, status="selected"))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="BTC",
                previous_side=None,
                new_side="SHORT",
                previous_size=0.0,
                current_size=-0.01,
                new_size=-0.01,
                delta_size=-0.01,
                delta_notional_usdc=650.0,
                action="OPEN_SHORT",
                exchange_ts=now - 200,
                side="SHORT",
                detected_at_ms=now - 100,
                source="user_fills_ws",
                confidence_score=90.0,
                raw_json={},
            )
        )
        session.add(MarketSnapshot(source="allMids", exchange_ts=now - 50, raw_json={"prices": {"BTC": "65000"}}))
        session.commit()
        report = write_fusion_runtime_input_to_engine_status(
            session=session,
            engine_status_path=heartbeat,
            fresh_window_ms=5_000,
            max_votes=10,
            current_ms=now,
        )

    assert report.status == "READY"
    written = json.loads(heartbeat.read_text(encoding="utf-8-sig"))
    assert written["read_only"] is True
    assert written["simulation_only"] is True
    assert written["external_action"] is False
    assert written["fusion_runtime_input_status"] == "READY"
    assert written["fusion_runtime_input"]["leader_votes"][0]["side"] == "SHORT"
    assert written["fusion_runtime_input"]["distilled_signal_candidates"] == []
    assert written["fusion_runtime_input"]["current_equity"] == 997.5
    assert written["fusion_runtime_input"]["peak_equity"] == 1000.0
    assert written["fusion_runtime_input"]["open_exposure_usdt"] == 20.0
    assert written["metrics"]["fusion_runtime_votes"] == "1"
    assert written["metrics"]["fusion_runtime_distilled_candidates"] == "0"
    assert written["metrics"]["fusion_runtime_state_source"] == "ui_simulation_state"
