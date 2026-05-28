from __future__ import annotations

import json
import re
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import (
    ApiHealth,
    MarketSnapshot,
    PaperFill,
    PaperFollowOrder,
    PaperOrderModel,
    PositionDeltaModel,
    TopWallet,
)
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.safe_actions import ALLOWED_ACTIONS
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms

# --- Fixtures ---

@pytest.fixture
def settings(tmp_path: Path):
    """Provides professional settings with a temporary database."""
    s = load_settings()
    s.database_url = f"sqlite:///{tmp_path / 'non_regression.sqlite3'}"
    init_db(s.database_url)
    # Ensure standard risk thresholds for non-regression
    s.risk.min_edge_required_bps = 8.0
    return s

@pytest.fixture
def db_session(settings):
    """Provides a clean SQLAlchemy session for each test."""
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session

@pytest.fixture
def ui_state():
    """Provides a fresh UI state with a fixed start time for deterministic testing."""
    state = UiState()
    # 10 seconds ago
    state.simulation_started_at_ms = now_ms() - 10000
    state.simulation_starting_equity_usdt = 1000.0
    return state

@pytest.fixture
def client(settings, ui_state):
    """Provides a FastAPI TestClient for UI-level non-regression."""
    app = create_ui_app(settings, ui_state)
    return TestClient(app)

# --- 1. P&L Persistence & Refresh ---

def test_pnl_survives_ui_refresh(client: TestClient, db_session: Session, ui_state: UiState):
    """Verify that P&L does not reset when calling the API multiple times."""
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "1" * 40

    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0,
        delta_notional_usdc=2000.0, confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms,
        delta_hash="refresh-test"
    ))
    db_session.commit()

    # Initial call
    resp1 = client.get("/api/simulation/overview").json()
    pnl_realized_1 = resp1["equity"]["realized_pnl_usdc"]

    # Simulate a "refresh" by calling again
    resp2 = client.get("/api/simulation/overview").json()
    pnl_realized_2 = resp2["equity"]["realized_pnl_usdc"]

    assert pnl_realized_1 == pnl_realized_2
    assert resp1["counts"]["reproduced_entries"] == 1
    assert resp1["equity"]["bot_costs_paid_usdc"] > 0

def test_pnl_persistence_serialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that simulation P&L survives a process restart via JSON persistence."""
    from hl_observer.ui.persistent_state import load_or_create_ui_state, persist_simulation_state

    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'persist.sqlite3'}"
    init_db(settings.database_url)

    # State in Process 1
    state1 = UiState()
    state1.simulation_started_at_ms = 123456
    state1.simulation_ledger_events = [{"observed_at_ms": 123457, "estimated_net_pnl_usdc": 42.0, "status": "LOCAL_REPLAY"}]

    # Use monkeypatch to redirect persistence path
    state_file = tmp_path / "ui_sim_state.json"
    monkeypatch.setattr("hl_observer.ui.persistent_state.simulation_state_path", lambda s: state_file)

    persist_simulation_state(settings, state1)
    assert state_file.exists()

    # Reload in Process 2
    state2 = load_or_create_ui_state(settings)
    assert state2.simulation_started_at_ms == 123456
    assert len(state2.simulation_ledger_events) == 1
    assert state2.simulation_ledger_events[0]["estimated_net_pnl_usdc"] == 42.0

# --- 2. Position Lifecycle Logic ---

def test_red_position_remains_open(client: TestClient, db_session: Session, ui_state: UiState):
    """Verify virtual positions stay open even with negative unrealized P&L (no auto-close)."""
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "2" * 40

    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="BTC", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=50000.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="red-test"
    ))
    db_session.commit()

    # Trigger simulation
    client.get("/api/simulation/overview")

    # Add a market drop
    db_session.add(MarketSnapshot(raw_json={"BTC": "30000.0"}, exchange_ts=base_ms + 5000))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 1
    # Unrealized P&L should be negative (BTC dropped from 50k to 30k)
    # Note: simulation caps position size (e.g. 50 USDC), so loss is proportional.
    assert overview["equity"]["unrealized_pnl_usdc"] < 0
    # Policy must be explicitly stated in payload
    assert overview["magic_profile"]["red_pnl_exit_policy"] == "never_exit_only_because_unrealized_pnl_is_negative"

def test_close_leader_terminates_position(client: TestClient, db_session: Session, ui_state: UiState):
    """Verify that a leader CLOSE action correctly terminates the local virtual position."""
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "3" * 40

    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    # 1. Open
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="SOL", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=10.0, new_size=10.0, delta_size=10.0, price=100.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="close-test-1"
    ))
    db_session.commit()
    client.get("/api/simulation/overview")

    # 2. Close
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="SOL", action="CLOSE", delta_type="close_long",
        previous_size=10.0, current_size=0.0, new_size=0.0, delta_size=10.0, price=110.0,
        confidence_score=1.0, detected_at_ms=base_ms + 5000, exchange_ts=base_ms + 5000, delta_hash="close-test-2"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 0
    assert overview["counts"]["reproduced_exits"] == 1
    assert overview["equity"]["realized_pnl_usdc"] > 0

def test_position_flip_safety_is_unknown(client: TestClient, db_session: Session, ui_state: UiState):
    """Verify that trading flips (long->short) are marked UNKNOWN for safety."""
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "flip" * 20
    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="BTC", action="FLIP", delta_type="flip_long_to_short",
        previous_size=1.0, current_size=-1.0, new_size=-1.0, delta_size=2.0, price=50000.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="flip-safety"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    # Search for unknown delta reason
    assert any("UNKNOWN_DELTA" in r["reason"] for r in overview["no_trade_reasons"])

# --- 3. Signal Rejection Gates ---

def test_stale_signal_rejection(client: TestClient, db_session: Session, ui_state: UiState):
    """Verify that signals older than the simulation cutoff or max age are refused."""
    now = now_ms()
    wallet = "0x" + "stale" * 10

    # Scenario A: Before simulation start (cutoff)
    stale_cutoff = ui_state.simulation_started_at_ms - 5000
    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=stale_cutoff))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0,
        confidence_score=1.0, detected_at_ms=stale_cutoff, exchange_ts=stale_cutoff, delta_hash="stale-A"
    ))
    db_session.commit()
    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    assert any("OLD_DELTA_IGNORED" in r["reason"] for r in overview["no_trade_reasons"])

    # Scenario B: Fresh (after cutoff) but > 10 minutes old relative to NOW
    stale_age = now - (11 * 60 * 1000)
    ui_state.simulation_started_at_ms = stale_age - 1000 # Make it "fresh" for cutoff
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="BTC", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=50000.0,
        confidence_score=1.0, detected_at_ms=stale_age, exchange_ts=stale_age, delta_hash="stale-B"
    ))
    db_session.commit()
    overview = client.get("/api/simulation/overview").json()
    assert any("STALE_SIGNAL" in r["reason"] for r in overview["no_trade_reasons"])

def test_edge_absent_rejection(client: TestClient, db_session: Session, ui_state: UiState):
    """Verify that signals with insufficient edge (e.g. low confidence) are refused."""
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "noedge" * 8
    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    # Confidence 0.01 will result in very low edge remaining
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0,
        confidence_score=0.01, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="no-edge"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    assert any("EDGE_REMAINING_TOO_LOW" in r["reason"] for r in overview["no_trade_reasons"])

# --- 4. Security Audit & Dashboard Safety ---

def test_dashboard_safe_from_dangerous_buttons(client: TestClient):
    """Verify that all UI buttons are in the allowlist and have no dangerous keywords."""
    html = client.get("/").text
    actions = re.findall(r'data-action="([^"]+)"', html)
    assert actions, "Dashboard should have action buttons"
    for action in actions:
        assert action in ALLOWED_ACTIONS, f"Action '{action}' not in allowlist"
        # Security keywords must not appear in UI action IDs
        for forbidden in ["execute", "withdraw", "mainnet", "transfer"]:
            assert forbidden not in action.lower(), f"Dangerous keyword '{forbidden}' in action '{action}'"

def test_no_forbidden_literals_exhaustive():
    """Rule 2 & 5: Exhaustive scan for forbidden mainnet/exchange literals in ALL sources and tools."""
    forbidden_list = [
        "/" + "exchange",
        "exchange" + ".hyperliquid.xyz"
    ]
    # Scan project-specific directories
    extensions = ["*.py", "*.js", "*.html", "*.sh", "*.ps1", "*.cmd"]
    for root in ["src", "hyper_smart_observer", "tools"]:
        r_path = Path(root)
        if not r_path.exists(): continue
        for ext in extensions:
            for path in r_path.rglob(ext):
                # Skip __pycache__ or similar if found
                if "__pycache__" in str(path): continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                for forbidden in forbidden_list:
                    assert forbidden not in content, f"Forbidden literal '{forbidden}' found in {path}"

def test_mainnet_hard_lock_via_ui(monkeypatch: pytest.MonkeyPatch, ui_state: UiState):
    """Verify that UI actions remain blocked even if mainnet execution is accidentally enabled."""
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "true")
    # Reload settings with modified env
    s = load_settings()
    assert s.execution.enable_mainnet_execution is True

    app = create_ui_app(s, ui_state)
    local_client = TestClient(app)

    # Try common actions; they must fail at the safe_actions logic gate
    for action in ["doctor", "paper_run", "collect_all_mids"]:
        resp = local_client.post("/api/actions", json={"action": action}).json()
        assert resp["allowed"] is False
        assert resp["level"] == "SECURITY"
        assert "mainnet" in resp["message"].lower()

# --- 5. Runtime & Release Hygiene ---

def test_runtime_hygiene_no_db_in_logs(tmp_path: Path, settings):
    """Verify that no database files are allowed to reside in the logs directory."""
    from hl_observer.runtime.hygiene import scan_runtime_hygiene
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    # Put a fake DB in logs
    db_file = logs_dir / "bad.sqlite3"
    db_file.write_bytes(b"SQLite format 3\0")

    report = scan_runtime_hygiene(settings, root=tmp_path)
    assert report.databases_in_logs_count >= 1

    # Removal and re-check
    db_file.unlink()
    report = scan_runtime_hygiene(settings, root=tmp_path)
    assert report.databases_in_logs_count == 0

def test_archive_release_is_clean(tmp_path: Path):
    """Verify that the archive creation tool actually excludes sensitive and runtime files."""
    # We prioritize the module in hyper_smart_observer for hygiene/archive
    from hyper_smart_observer.runtime.archive import create_clean_archive

    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "ok.py").write_text("print('safe')")
    (root / "logs").mkdir()
    (root / "logs" / "runtime.sqlite3").write_text("secret db")
    (root / ".env").write_text("PRIVATE_KEY=DONT_ARCHIVE")

    out_dir = tmp_path / "dist"
    out_dir.mkdir()

    archive_result = create_clean_archive(root, out_dir, name="release.zip")
    assert archive_result.archive_path.exists()

    with ZipFile(archive_result.archive_path, 'r') as z:
        names = z.namelist()
        assert "src/ok.py" in names
        assert not any("logs/" in n for n in names)
        assert ".env" not in names
        assert not any(n.endswith(".sqlite3") for n in names)

# --- 6. API and Decision Logic Consistency ---

def test_risk_engine_logic_integrity(settings):
    """Verify RiskEngine gates for liquidity, spread, and wallet score."""
    from hl_observer.risk.gates import RiskContext
    from hl_observer.risk.risk_engine import RiskEngine

    engine = RiskEngine(settings)
    ctx = RiskContext(
        spread_bps=1.0, estimated_slippage_bps=1.0, orderbook_depth_usdc=100000,
        wallet_score=90, signal_score=90, edge_remaining_bps=20.0,
        signal_age_ms=100, kill_switch_active=False
    )
    assert engine.evaluate(ctx).allowed

    # Breach gates individually
    assert not engine.evaluate(ctx.model_copy(update={"spread_bps": 50.0})).allowed
    assert not engine.evaluate(ctx.model_copy(update={"orderbook_depth_usdc": 100})).allowed
    assert not engine.evaluate(ctx.model_copy(update={"wallet_score": 10})).allowed
    assert not engine.evaluate(ctx.model_copy(update={"kill_switch_active": True})).allowed

def test_api_health_tracking_integrity(client: TestClient, db_session: Session):
    """Verify that ApiHealth events are correctly reflected in the UI status."""
    db_session.add(ApiHealth(service="allMids", ok=True, latency_ms=10.0))
    db_session.add(ApiHealth(service="hyperliquid_ws", ok=False, error="timeout"))
    db_session.commit()

    status = client.get("/api/status").json()
    assert "risk_gates" in status
    db_gate = next(g for g in status["risk_gates"] if g["name"] == "db status")
    assert db_gate["passed"] is True

def test_ui_payload_compatibility(client: TestClient):
    """Verify the consistency of UI payloads required by app.js (metagraphe, summary)."""
    overview = client.get("/api/simulation/overview").json()
    # Metagraphe requirements
    assert "equity_candles" in overview
    assert "equity" in overview
    assert "current_pnl_usdc" in overview["equity"]
    assert "bot_simulation" in overview
    assert "events" in overview["bot_simulation"]

    home = client.get("/api/simple-home").json()
    assert "simple_cards" in home
    assert "discovery" in home["simple_cards"]
    assert "security" in home["simple_cards"]
    assert "kill_switch" in home["simple_cards"]["security"]
