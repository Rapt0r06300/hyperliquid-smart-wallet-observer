from __future__ import annotations

from pathlib import Path
import json
import re

from fastapi.testclient import TestClient
import pytest

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db, create_session_factory, create_sqlite_engine
from hl_observer.storage.models import PositionDeltaModel, TopWallet, MarketSnapshot
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms
from hl_observer.ui.safe_actions import ALLOWED_ACTIONS

def _setup_app(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'non_regression.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    # Reset simulation state for clean test
    state.simulation_started_at_ms = now_ms() - 10000
    state.simulation_starting_equity_usdt = 1000.0

    app = create_ui_app(settings, state)
    client = TestClient(app)
    return settings, state, client

def test_simulation_pnl_persistence(tmp_path: Path):
    settings, state, client = _setup_app(tmp_path)
    base_ms = state.simulation_started_at_ms + 1000

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)

    wallet = "0x" + "1" * 40
    with factory() as session:
        session.add(TopWallet(
            wallet_address=wallet, rank=1, source="test", score=90.0, status="selected",
            selected_at_ms=base_ms
        ))
        session.add(PositionDeltaModel(
            wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
            previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0, delta_notional_usdc=2000.0,
            confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms,
            delta_hash="h1"
        ))
        session.commit()

    # First call triggers simulation
    resp1 = client.get("/api/simulation/overview").json()
    pnl1 = resp1["equity"]["realized_pnl_usdc"]

    # Second call should return same P&L (persistence)
    resp2 = client.get("/api/simulation/overview").json()
    pnl2 = resp2["equity"]["realized_pnl_usdc"]

    assert pnl1 == pnl2
    assert resp1["counts"]["reproduced_entries"] == 1

def test_red_position_remains_open(tmp_path: Path):
    settings, state, client = _setup_app(tmp_path)
    base_ms = state.simulation_started_at_ms + 1000

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)

    wallet = "0x" + "2" * 40
    with factory() as session:
        session.add(TopWallet(
            wallet_address=wallet, rank=1, source="test", score=90.0, status="selected",
            selected_at_ms=base_ms
        ))
        session.add(PositionDeltaModel(
            wallet_address=wallet, coin="BTC", action="OPEN", delta_type="open_long",
            previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=50000.0, delta_notional_usdc=50000.0,
            confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms,
            delta_hash="h2"
        ))
        session.commit()

    # Trigger simulation once
    client.get("/api/simulation/overview")

    # Verify position is open
    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 1

    # Now simulate a mark price drop (negative unrealized P&L)
    with factory() as session:
        session.add(MarketSnapshot(
            raw_json={"BTC": "40000.0"},
            exchange_ts=base_ms + 5000
        ))
        session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 1
    assert overview["equity"]["unrealized_pnl_usdc"] < 0
    # Policy check
    assert overview["magic_profile"]["red_pnl_exit_policy"] == "never_exit_only_because_unrealized_pnl_is_negative"

def test_leader_close_terminates_virtual_position(tmp_path: Path):
    settings, state, client = _setup_app(tmp_path)
    base_ms = state.simulation_started_at_ms + 1000

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)

    wallet = "0x" + "3" * 40
    with factory() as session:
        session.add(TopWallet(
            wallet_address=wallet, rank=1, source="test", score=90.0, status="selected",
            selected_at_ms=base_ms
        ))
        # Open
        session.add(PositionDeltaModel(
            wallet_address=wallet, coin="SOL", action="OPEN", delta_type="open_long",
            previous_size=0.0, current_size=10.0, new_size=10.0, delta_size=10.0, price=100.0, delta_notional_usdc=1000.0,
            confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms,
            delta_hash="h3-open"
        ))
        session.commit()

    client.get("/api/simulation/overview")
    assert client.get("/api/simulation/overview").json()["counts"]["open_virtual_positions"] == 1

    with factory() as session:
        # Close
        session.add(PositionDeltaModel(
            wallet_address=wallet, coin="SOL", action="CLOSE", delta_type="close_long",
            previous_size=10.0, current_size=0.0, new_size=0.0, delta_size=10.0, price=110.0, delta_notional_usdc=1100.0,
            confidence_score=1.0, detected_at_ms=base_ms + 5000, exchange_ts=base_ms + 5000,
            delta_hash="h3-close"
        ))
        session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 0
    assert overview["counts"]["reproduced_exits"] == 1

def test_stale_signal_rejection(tmp_path: Path):
    settings, state, client = _setup_app(tmp_path)
    # Simulation started 10s ago.
    # Max signal age is 10 mins (600,000 ms) in build_bot_simulation
    # But deltas before simulation_started_at_ms are ignored for P&L

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)

    wallet = "0x" + "4" * 40
    stale_ts = state.simulation_started_at_ms - 5000

    with factory() as session:
        session.add(TopWallet(
            wallet_address=wallet, rank=1, source="test", score=90.0, status="selected",
            selected_at_ms=stale_ts
        ))
        session.add(PositionDeltaModel(
            wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
            previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0, delta_notional_usdc=2000.0,
            confidence_score=1.0, detected_at_ms=stale_ts, exchange_ts=stale_ts,
            delta_hash="h4"
        ))
        session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    # The reason for rejection might be OLD_DELTA_IGNORED_FRESH_ONLY
    assert any("OLD_DELTA_IGNORED" in reason["reason"] for reason in overview["no_trade_reasons"])

def test_absent_edge_rejection(tmp_path: Path):
    settings, state, client = _setup_app(tmp_path)
    base_ms = state.simulation_started_at_ms + 1000

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)

    wallet = "0x" + "5" * 40
    with factory() as session:
        session.add(TopWallet(
            wallet_address=wallet, rank=1, source="test", score=90.0, status="selected",
            selected_at_ms=base_ms
        ))
        # Delta with very low confidence score resulting in low edge
        session.add(PositionDeltaModel(
            wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
            previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0, delta_notional_usdc=2000.0,
            confidence_score=0.01, detected_at_ms=base_ms, exchange_ts=base_ms,
            delta_hash="h5"
        ))
        session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    # REJECTED because edge_remaining < 8.0 bps
    assert any("EDGE_REMAINING_TOO_LOW" in reason["reason"] for reason in overview["no_trade_reasons"])

def test_dashboard_has_no_dangerous_buttons(tmp_path: Path):
    settings, state, client = _setup_app(tmp_path)
    html = client.get("/").text
    actions = re.findall(r'data-action="([^"]+)"', html)

    assert actions
    for action in actions:
        assert action in ALLOWED_ACTIONS
        # Double check no "execute" or "withdraw" or "mainnet" in action name
        assert "execute" not in action.lower()
        assert "withdraw" not in action.lower()
        assert "mainnet" not in action.lower()

def test_runtime_hygiene_no_db_in_logs(tmp_path: Path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Existing hygiene check module
    from hl_observer.runtime.hygiene import scan_runtime_hygiene
    settings = load_settings()

    # If we put a db in logs, it should be detected
    db_file = logs_dir / "test.sqlite3"
    db_file.write_bytes(b"fake db")

    report = scan_runtime_hygiene(settings, root=tmp_path)
    assert report.databases_in_logs_count == 1

    # Clean up and verify
    db_file.unlink()
    report = scan_runtime_hygiene(settings, root=tmp_path)
    assert report.databases_in_logs_count == 0

def test_archive_hygiene_rules():
    from hyper_smart_observer.runtime.archive import is_archive_safe_path

    assert not is_archive_safe_path(Path("logs/runtime.sqlite3"))
    assert not is_archive_safe_path(Path(".env"))
    assert is_archive_safe_path(Path("src/hl_observer/ui/routes.py"))

def test_no_forbidden_exchange_literals():
    forbidden = "/" + "exchange"
    # Scan src and hyper_smart_observer
    for root in ["src", "hyper_smart_observer"]:
        source_files = Path(root).rglob("*.py")
        for path in source_files:
            content = path.read_text(encoding="utf-8", errors="ignore")
            assert forbidden not in content, f"Forbidden literal found in {path}"
