from __future__ import annotations

from pathlib import Path
import json
import re
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db, create_session_factory, create_sqlite_engine
from hl_observer.storage.models import (
    PositionDeltaModel, TopWallet, MarketSnapshot,
    PaperOrderModel, PaperFill, PaperFollowOrder
)
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms
from hl_observer.ui.safe_actions import ALLOWED_ACTIONS

@pytest.fixture
def settings(tmp_path: Path):
    s = load_settings()
    s.database_url = f"sqlite:///{tmp_path / 'non_regression.sqlite3'}"
    init_db(s.database_url)
    return s

@pytest.fixture
def db_session(settings):
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        yield session

@pytest.fixture
def ui_state():
    state = UiState()
    state.simulation_started_at_ms = now_ms() - 10000
    state.simulation_starting_equity_usdt = 1000.0
    return state

@pytest.fixture
def client(settings, ui_state):
    app = create_ui_app(settings, ui_state)
    return TestClient(app)

# --- Simulation and Position Tests ---

def test_simulation_pnl_persistence(client: TestClient, db_session: Session, ui_state: UiState):
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "1" * 40

    db_session.add(TopWallet(
        wallet_address=wallet, rank=1, source="test", score=90.0, status="selected",
        selected_at_ms=base_ms
    ))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0, delta_notional_usdc=2000.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms,
        delta_hash="h1"
    ))
    db_session.commit()

    # Multiple calls return consistent state
    resp1 = client.get("/api/simulation/overview").json()
    pnl1 = resp1["equity"]["realized_pnl_usdc"]

    resp2 = client.get("/api/simulation/overview").json()
    pnl2 = resp2["equity"]["realized_pnl_usdc"]

    assert pnl1 == pnl2
    assert resp1["counts"]["reproduced_entries"] == 1

def test_simulation_pnl_persistence_after_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from hl_observer.ui.persistent_state import persist_simulation_state, load_or_create_ui_state

    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'restart.sqlite3'}"
    init_db(settings.database_url)

    state1 = UiState()
    state1.simulation_started_at_ms = 1000
    state1.simulation_starting_equity_usdt = 5000.0
    state1.simulation_ledger_events = [{"observed_at_ms": 2000, "estimated_net_pnl_usdc": 150.0, "status": "LOCAL_REPLAY"}]

    monkeypatch.setattr("hl_observer.ui.persistent_state.simulation_state_path", lambda s: tmp_path / "ui_state.json")
    persist_simulation_state(settings, state1)

    state2 = load_or_create_ui_state(settings)
    assert state2.simulation_starting_equity_usdt == 5000.0
    assert len(state2.simulation_ledger_events) == 1
    assert state2.simulation_ledger_events[0]["estimated_net_pnl_usdc"] == 150.0

def test_red_position_remains_open(client: TestClient, db_session: Session, ui_state: UiState):
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "2" * 40

    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="BTC", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=50000.0, delta_notional_usdc=50000.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="h2"
    ))
    db_session.commit()

    client.get("/api/simulation/overview")

    # Mark price drop
    db_session.add(MarketSnapshot(raw_json={"BTC": "40000.0"}, exchange_ts=base_ms + 5000))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 1
    assert overview["equity"]["unrealized_pnl_usdc"] < 0
    assert overview["magic_profile"]["red_pnl_exit_policy"] == "never_exit_only_because_unrealized_pnl_is_negative"

def test_leader_close_terminates_virtual_position(client: TestClient, db_session: Session, ui_state: UiState):
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "3" * 40

    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="SOL", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=10.0, new_size=10.0, delta_size=10.0, price=100.0, delta_notional_usdc=1000.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="h3-open"
    ))
    db_session.commit()
    client.get("/api/simulation/overview")

    # Close
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="SOL", action="CLOSE", delta_type="close_long",
        previous_size=10.0, current_size=0.0, new_size=0.0, delta_size=10.0, price=110.0, delta_notional_usdc=1100.0,
        confidence_score=1.0, detected_at_ms=base_ms + 5000, exchange_ts=base_ms + 5000, delta_hash="h3-close"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 0
    assert overview["counts"]["reproduced_exits"] == 1

def test_position_flip_is_unknown(client: TestClient, db_session: Session, ui_state: UiState):
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "a" * 40
    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="BTC", action="FLIP", delta_type="flip_long_to_short",
        previous_size=1.0, current_size=-1.0, new_size=-1.0, delta_size=2.0, price=50000.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="flip-1"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    assert any("UNKNOWN_DELTA" in reason["reason"] for reason in overview["no_trade_reasons"])

def test_red_position_survives_volatility(client: TestClient, db_session: Session, ui_state: UiState):
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "b" * 40
    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="v-1"
    ))
    db_session.commit()

    client.get("/api/simulation/overview")

    prices = ["1900.0", "1500.0", "2100.0", "1200.0"]
    for i, px in enumerate(prices):
        db_session.add(MarketSnapshot(raw_json={"ETH": px}, exchange_ts=base_ms + 10000 + i))
        db_session.commit()
        overview = client.get("/api/simulation/overview").json()
        assert overview["counts"]["open_virtual_positions"] == 1

def test_simulation_multi_wallet_independence(client: TestClient, db_session: Session, ui_state: UiState):
    base_ms = ui_state.simulation_started_at_ms + 1000
    w1 = "0x" + "1" * 40
    w2 = "0x" + "2" * 40

    for w in [w1, w2]:
        db_session.add(TopWallet(wallet_address=w, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
        db_session.add(PositionDeltaModel(
            wallet_address=w, coin="ETH", action="OPEN", delta_type="open_long",
            previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0,
            confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash=f"h-{w}"
        ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 2

    # Close only w1
    db_session.add(PositionDeltaModel(
        wallet_address=w1, coin="ETH", action="CLOSE", delta_type="close_long",
        previous_size=1.0, current_size=0.0, new_size=0.0, delta_size=1.0, price=2100.0,
        confidence_score=1.0, detected_at_ms=base_ms + 5000, exchange_ts=base_ms + 5000, delta_hash="h-close-w1"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["open_virtual_positions"] == 1
    # w2 should still be open
    assert overview["bot_simulation"]["virtual_positions_state"][f"{w2.lower()}|ETH|LONG"]

def test_simulation_ignore_stale_but_after_cutoff(client: TestClient, db_session: Session, ui_state: UiState):
    # Cutoff was 10s ago.
    # Max signal age is 10 mins.
    # Current time relative to base_ms: now()
    now = now_ms()
    wallet = "0x" + "c" * 40
    # Signal is after cutoff (frais), but > 10 mins old relative to CURRENT time
    stale_ms = now - (11 * 60 * 1000)

    # Ensure cutoff is even earlier so it counts as "frais" but "stale"
    ui_state.simulation_started_at_ms = stale_ms - 1000

    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=stale_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="BTC", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=50000.0,
        confidence_score=1.0, detected_at_ms=stale_ms, exchange_ts=stale_ms, delta_hash="h-stale-frais"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    assert any("STALE_SIGNAL" in reason["reason"] for reason in overview["no_trade_reasons"])

def test_simulation_no_db_side_effects(client: TestClient, db_session: Session, ui_state: UiState):
    # Simulation should be read-only for trade tables
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "d" * 40
    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="SOL", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=100.0,
        confidence_score=1.0, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="h-side-effect"
    ))
    db_session.commit()

    client.get("/api/simulation/overview")

    # Check that no entries were written to PaperOrderModel
    assert db_session.query(PaperOrderModel).count() == 0
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperFollowOrder).count() == 0

# --- Signal and Rejection Tests ---

def test_stale_signal_rejection(client: TestClient, db_session: Session, ui_state: UiState):
    stale_ts = ui_state.simulation_started_at_ms - 5000
    wallet = "0x" + "4" * 40
    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=stale_ts))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0, delta_notional_usdc=2000.0,
        confidence_score=1.0, detected_at_ms=stale_ts, exchange_ts=stale_ts, delta_hash="h4"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    assert any("OLD_DELTA_IGNORED" in reason["reason"] for reason in overview["no_trade_reasons"])

def test_absent_edge_rejection(client: TestClient, db_session: Session, ui_state: UiState):
    base_ms = ui_state.simulation_started_at_ms + 1000
    wallet = "0x" + "5" * 40
    db_session.add(TopWallet(wallet_address=wallet, rank=1, source="test", score=90.0, status="selected", selected_at_ms=base_ms))
    db_session.add(PositionDeltaModel(
        wallet_address=wallet, coin="ETH", action="OPEN", delta_type="open_long",
        previous_size=0.0, current_size=1.0, new_size=1.0, delta_size=1.0, price=2000.0, delta_notional_usdc=2000.0,
        confidence_score=0.01, detected_at_ms=base_ms, exchange_ts=base_ms, delta_hash="h5"
    ))
    db_session.commit()

    overview = client.get("/api/simulation/overview").json()
    assert overview["counts"]["reproduced_entries"] == 0
    assert any("EDGE_REMAINING_TOO_LOW" in reason["reason"] for reason in overview["no_trade_reasons"])

def test_wilson_lower_bound_luck_penalty():
    from hl_observer.wallets.skill_vs_luck import wilson_lower_bound
    small = wilson_lower_bound(9, 10)
    large = wilson_lower_bound(90, 100)
    assert large > small
    assert 0.0 < small < 0.9
    assert 0.8 < large < 1.0

def test_one_big_win_rejection():
    from hl_observer.wallets.skill_vs_luck import one_big_win_dependency
    assert one_big_win_dependency(0.50) is True
    assert one_big_win_dependency(0.10) is False

# --- Security, Hygiene and Environment Tests ---

def test_dashboard_has_no_dangerous_buttons(client: TestClient):
    html = client.get("/").text
    actions = re.findall(r'data-action="([^"]+)"', html)
    assert actions
    for action in actions:
        assert action in ALLOWED_ACTIONS
        assert "execute" not in action.lower()
        assert "withdraw" not in action.lower()
        assert "mainnet" not in action.lower()

def test_runtime_hygiene_no_db_in_logs(tmp_path: Path, settings):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    from hl_observer.runtime.hygiene import scan_runtime_hygiene

    db_file = logs_dir / "test.sqlite3"
    db_file.write_bytes(b"fake db")
    report = scan_runtime_hygiene(settings, root=tmp_path)
    assert report.databases_in_logs_count == 1

    db_file.unlink()
    report = scan_runtime_hygiene(settings, root=tmp_path)
    assert report.databases_in_logs_count == 0

def test_archive_hygiene_rules():
    from hyper_smart_observer.runtime.archive import is_archive_safe_path
    assert not is_archive_safe_path(Path("logs/runtime.sqlite3"))
    assert not is_archive_safe_path(Path(".env"))
    assert is_archive_safe_path(Path("src/hl_observer/ui/routes.py"))

def test_archive_full_cycle(tmp_path: Path):
    from hyper_smart_observer.runtime.archive import create_clean_archive
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "ok.py").write_text("ok")
    (root / "logs").mkdir()
    (root / "logs" / "secret.sqlite3").write_text("secret")
    (root / ".env").write_text("KEY=123")

    out_dir = tmp_path / "dist"
    out_dir.mkdir()

    result = create_clean_archive(root, out_dir, name="test_v10.zip")
    assert result.archive_path.exists()

    with ZipFile(result.archive_path) as z:
        names = z.namelist()
        assert "src/ok.py" in names
        assert not any("logs/" in n for n in names)
        assert ".env" not in names

def test_no_forbidden_literals_exhaustive():
    # Rule 2 and 5: No mainnet /exchange and no mainnet exchange URLs
    forbidden_list = [
        "/" + "exchange",
        "exchange" + ".hyperliquid.xyz"
    ]

    # Exhaustive scan of all source and tool files
    extensions = ["*.py", "*.js", "*.html", "*.sh", "*.ps1", "*.cmd"]
    for root in ["src", "hyper_smart_observer", "tools"]:
        for ext in extensions:
            source_files = Path(root).rglob(ext)
            for path in source_files:
                content = path.read_text(encoding="utf-8", errors="ignore")
                for forbidden in forbidden_list:
                    assert forbidden not in content, f"Forbidden literal '{forbidden}' found in {path}"
