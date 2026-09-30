from __future__ import annotations

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.data_sources.warehouse_coverage import (
    build_warehouse_coverage_report,
    format_warehouse_coverage_report,
)
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import (
    FollowDecision,
    FollowSignal,
    MarketSnapshot,
    PaperFollowOrder,
    PositionDeltaModel,
    RawEvent,
    TopWallet,
    WalletCandidateModel,
)


def _factory(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'warehouse.sqlite3'}"
    init_db(db_url)
    return create_session_factory(create_sqlite_engine(db_url)), db_url


def test_warehouse_coverage_reports_bottlenecks_on_empty_db(tmp_path) -> None:
    factory, _ = _factory(tmp_path)
    with factory() as session:
        report = build_warehouse_coverage_report(session, now_ms=10_000, fresh_window_ms=5_000)

    text = format_warehouse_coverage_report(report)

    assert report.readiness == "SIMULATION_INPUT_INCOMPLETE"
    assert "NO_WALLET_CANDIDATES" in report.bottlenecks
    assert "NO_FRESH_POSITION_DELTAS" in report.bottlenecks
    assert "profit_guarantee=false" in text
    assert "execution=forbidden" in text


def test_warehouse_coverage_accepts_fresh_complete_paper_inputs(tmp_path) -> None:
    factory, _ = _factory(tmp_path)
    now = 20_000
    wallet = "0x" + "a" * 40
    with factory() as session:
        session.add(
            WalletCandidateModel(
                run_id=1,
                address=wallet,
                coin="HYPE",
                source_name="public_trades_ws",
                source_type="websocket_read_only",
                label="fresh_public_trade_wallet",
                first_seen_ms=now - 1_000,
                last_seen_ms=now - 500,
                raw_payload_json={"research_only": True},
                confidence_score=95.0,
                selected_for_backfill=True,
            )
        )
        session.add(TopWallet(wallet_address=wallet, rank=1, source="public_trades_ws", score=99.0, selected_at_ms=now - 200, status="selected"))
        session.add(
            RawEvent(
                source="hyperliquid_ws_public_trades",
                endpoint="wss://api.hyperliquid.xyz/ws",
                request_type="trades",
                wallet_address=None,
                coin="HYPE",
                request_payload_json={},
                response_payload_json=[{"coin": "HYPE", "px": "25", "time": now - 100}],
                response_hash="hash",
                fetched_at_ms=now - 100,
                success=True,
                error_message=None,
                event_type="public_trades_ws",
                wallet=None,
                exchange_ts=now - 100,
                local_received_ts=now - 90,
                payload_json={"trades": []},
                payload_hash="hash",
            )
        )
        session.add(MarketSnapshot(source="publicTradesWS", exchange_ts=now - 100, raw_json={"prices": {"HYPE": 25.0}}))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="HYPE",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=50_000.0,
                action="OPEN_LONG",
                side="long",
                price=25.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=now - 50,
                raw_json={"source": "test"},
            )
        )
        session.add(FollowSignal(id="sig-1", wallet_address=wallet, coin="HYPE", side="long", opening_type="open_long", created_at_ms=now - 40, signal_age_ms=40, raw_json={}))
        session.add(FollowDecision(signal_id="sig-1", decision="ACCEPT_PAPER", allowed=True, reasons_json=[], computed_at_ms=now - 30))
        session.add(PaperFollowOrder(id="paper-1", signal_id="sig-1", wallet_address=wallet, coin="HYPE", side="long", notional_usdc=25.0, status="SIMULATED", created_at_ms=now - 20))
        session.commit()
        report = build_warehouse_coverage_report(session, now_ms=now, fresh_window_ms=5_000)

    assert report.readiness == "SIMULATION_INPUT_READY"
    assert report.bottlenecks == ()
    assert report.fresh_entry_deltas == 1
    assert report.paper_follow_orders_total == 1


def test_warehouse_report_cli_uses_temp_runtime(tmp_path, monkeypatch) -> None:
    _, db_url = _factory(tmp_path)
    monkeypatch.setenv("HL_DATABASE_URL", db_url)
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))

    result = CliRunner().invoke(app, ["warehouse-report", "--fresh-window-seconds", "20"])

    assert result.exit_code == 0
    assert "warehouse_coverage=simulation_only" in result.output
    assert "read_only=true" in result.output
    assert "real_orders_created=0" in result.output
