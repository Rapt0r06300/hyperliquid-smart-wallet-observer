from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.storage.models import PositionDeltaModel, TopWallet
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.persistent_state import load_or_create_ui_state, persist_simulation_state, simulation_state_path
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


def test_ui_simulation_state_persists_outside_logs(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.simulation_started_at_ms = 123456789
    state.simulation_starting_equity_usdt = 1000.0

    state_path = persist_simulation_state(settings, state)
    restored = load_or_create_ui_state(settings)

    assert restored.simulation_started_at_ms == 123456789
    assert restored.simulation_starting_equity_usdt == 1000.0
    assert state_path.name == "ui_simulation_state.json"
    assert "runtime" in state_path.parts
    assert "logs" not in {part.lower() for part in state_path.parts}


def test_ui_app_restores_simulation_state_when_no_state_is_injected(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.simulation_started_at_ms = 987654321
    persist_simulation_state(settings, state)

    client = TestClient(create_ui_app(settings))
    payload = client.get("/api/simulation/overview").json()

    assert payload["simulation_started_at_ms"] == 987654321
    assert payload["simulation_state_persistent"] is True
    assert payload["simulation_state_path"] == str(simulation_state_path(settings))


def test_ui_simulation_state_reads_powershell_utf8_bom_file(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state_path = simulation_state_path(settings)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        '{"version":1,"simulation_started_at_ms":555,"simulation_starting_equity_usdt":1000}',
        encoding="utf-8-sig",
    )

    restored = load_or_create_ui_state(settings)

    assert restored.simulation_started_at_ms == 555


def test_ui_simulation_ledger_survives_refresh_window_changes(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(
            TopWallet(
                wallet_address="0x" + "7" * 40,
                rank=1,
                source="leaderboard",
                score=95.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "7" * 40,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=base_ms,
                delta_hash="persistent-open",
            )
        )
        session.commit()

    first = client.get("/api/simulation/overview?limit=1").json()
    second = client.get("/api/simulation/overview?limit=1").json()

    assert first["simulation_ledger_events_count"] == second["simulation_ledger_events_count"]
    assert first["simulation_processed_deltas_count"] == second["simulation_processed_deltas_count"]
    assert second["counts"]["reproduced_entries"] == 1
    assert second["counts"]["open_virtual_positions"] == 1
    assert second["equity_candles"]
    assert second["equity_candles"][-1]["source"] == "MARK_TO_MARKET"
