from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _replace_py_function(text: str, name: str, replacement: str) -> str:
    match = re.search(rf"(?m)^def {re.escape(name)}\(.*", text)
    if not match:
        raise RuntimeError(f"function not found: {name}")
    nxt = re.search(r"(?m)^def [A-Za-z_]\w*\(", text[match.end() :])
    if not nxt:
        raise RuntimeError(f"next function not found after {name}")
    end = match.end() + nxt.start()
    return text[: match.start()] + replacement.rstrip() + "\n\n" + text[end:]


def fix_portable_imports() -> None:
    path = ROOT / "src" / "hl_observer" / "ops" / "portable_clone.py"
    text = path.read_text(encoding="utf-8")
    marker = "    _is_within,\n    inventory,\n"
    if "    _resolved,\n" not in text:
        if marker not in text:
            raise RuntimeError("portable inventory import marker missing")
        text = text.replace(marker, "    _is_within,\n    _resolved,\n    inventory,\n", 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def migrate_writer_owned_tests() -> None:
    path = ROOT / "tests" / "test_ui_simulation_status_fast.py"
    text = path.read_text(encoding="utf-8")

    text = _replace_py_function(
        text,
        "test_status_persists_accepted_fusion_paper_order_into_simulation_state",
        r'''def test_economic_writer_persists_fusion_once_and_status_get_never_reapplies(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    event_ms = int(time.time() * 1000)
    _seed_recorded_execution_book(monkeypatch, coin="HYPE", mid=70.05, observed_at_ms=event_ms)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=event_ms, raw_json={"HYPE": "70.50"}))
        session.commit()

    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(json.dumps({
        "updated_at_ms": event_ms,
        "phase": "live_fusion_runtime",
        "read_only": True,
        "simulation_only": True,
        "external_action": False,
        "fusion_runtime_input": {
            "session_id": "ui-live-fusion-persist-test",
            "leader_votes": [
                {"wallet": "0x" + "1" * 40, "coin": "HYPE", "side": "LONG", "score": 2.0, "observed_at_ms": event_ms},
                {"wallet": "0x" + "2" * 40, "coin": "HYPE", "side": "LONG", "score": 1.7, "observed_at_ms": event_ms},
            ],
            "price_events": [
                {"source": "hyperliquid_allMids", "coin": "HYPE", "bid": 70.0, "ask": 70.1, "event_time_ms": event_ms}
            ],
            "funding_rows": [],
            "triangular_edges": [],
            "peak_equity": 1000.0,
            "current_equity": 1000.0,
            "copy_ratio": 0.05,
        },
    }), encoding="utf-8")
    state = UiState()
    app = create_ui_app(settings, state=state)
    writer = app.state.economic_writer

    assert writer.last_fusion_report["applied_count"] == 1
    assert state.simulation_reproduced_entries_total == 1
    assert len(state.simulation_virtual_positions) == 1
    before_ledger = json.dumps(state.simulation_ledger_events, sort_keys=True, default=str)
    before_positions = json.dumps(state.simulation_virtual_positions, sort_keys=True, default=str)

    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.get("/api/simulation/status").json()
        second = client.get("/api/simulation/status").json()

    assert first["status_projection_pure"] is True
    assert second["status_projection_pure"] is True
    assert json.dumps(state.simulation_ledger_events, sort_keys=True, default=str) == before_ledger
    assert json.dumps(state.simulation_virtual_positions, sort_keys=True, default=str) == before_positions

    duplicate = writer.tick(current_ms=event_ms + 1)
    assert duplicate["fusion"]["applied_count"] == 0
    assert len(state.simulation_virtual_positions) == 1''',
    )

    text = _replace_py_function(
        text,
        "test_status_can_close_existing_paper_position_when_fusion_consensus_flips",
        r'''def test_economic_writer_closes_existing_paper_position_when_fusion_consensus_flips(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'session.sqlite3').as_posix()}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
    settings = _settings()
    from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
    from hl_observer.storage.models import MarketSnapshot

    init_db(settings.database_url)
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    event_ms = int(time.time() * 1000)
    _seed_recorded_execution_book(monkeypatch, coin="HYPE", mid=72.05, observed_at_ms=event_ms)
    _seed_copy_whitelist(monkeypatch, tmp_path, ["0x" + "1" * 40, "0x" + "2" * 40])
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=event_ms, raw_json={"HYPE": "72.00"}))
        session.commit()

    heartbeat_path = simulation_state_path(settings).parent / "hypersmart_engine_status.json"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(json.dumps({
        "updated_at_ms": event_ms,
        "phase": "live_fusion_runtime",
        "read_only": True,
        "simulation_only": True,
        "external_action": False,
        "fusion_runtime_input": {
            "session_id": "ui-live-fusion-open-test",
            "leader_votes": [
                {"wallet": "0x" + "1" * 40, "coin": "HYPE", "side": "LONG", "score": 2.0, "observed_at_ms": event_ms},
                {"wallet": "0x" + "2" * 40, "coin": "HYPE", "side": "LONG", "score": 1.7, "observed_at_ms": event_ms},
            ],
            "price_events": [{"source": "hyperliquid_allMids", "coin": "HYPE", "bid": 72.0, "ask": 72.1, "event_time_ms": event_ms}],
            "funding_rows": [], "triangular_edges": [],
        },
    }), encoding="utf-8")
    state = UiState()
    app = create_ui_app(settings, state=state)
    writer = app.state.economic_writer
    assert state.simulation_reproduced_entries_total == 1
    assert len(state.simulation_virtual_positions) == 1

    _seed_recorded_execution_book(monkeypatch, coin="HYPE", mid=73.05, observed_at_ms=event_ms + 1)
    heartbeat_path.write_text(json.dumps({
        "updated_at_ms": event_ms + 1,
        "phase": "live_fusion_runtime",
        "read_only": True,
        "simulation_only": True,
        "external_action": False,
        "fusion_runtime_input": {
            "session_id": "ui-live-fusion-close-test",
            "leader_votes": [
                {"wallet": "0x" + "3" * 40, "coin": "HYPE", "side": "SHORT", "score": 2.1, "observed_at_ms": event_ms + 1},
                {"wallet": "0x" + "4" * 40, "coin": "HYPE", "side": "SHORT", "score": 1.8, "observed_at_ms": event_ms + 1},
            ],
            "price_events": [{"source": "hyperliquid_allMids", "coin": "HYPE", "bid": 73.0, "ask": 73.1, "event_time_ms": event_ms + 1}],
            "funding_rows": [], "triangular_edges": [],
        },
    }), encoding="utf-8")

    report = writer.tick(current_ms=event_ms + 1)
    assert report["fusion"]["applied_count"] == 1
    assert state.simulation_reproduced_exits_total == 1
    assert any(row.get("bot_replay_action") == "FUSION_DIRECT_PAPER_CLOSE" for row in state.simulation_ledger_events)
    assert state.simulation_realized_pnl_usdc > 0

    before = json.dumps(state.simulation_ledger_events, sort_keys=True, default=str)
    with TestClient(app, raise_server_exceptions=False) as client:
        payload = client.get("/api/simulation/status").json()
    assert payload["status_projection_pure"] is True
    assert json.dumps(state.simulation_ledger_events, sort_keys=True, default=str) == before''',
    )

    text = _replace_py_function(
        text,
        "test_status_exports_live_pnl_ledger_to_logs_to_send",
        r'''def test_status_get_never_exports_diagnostics_or_writes_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("HYPERSMART_DISABLE_ECONOMIC_WRITER", "1")
    settings = _settings()
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_ledger_events = [{
        "delta_key": "close-live-export",
        "coin": "HYPE",
        "leader_side": "LONG",
        "paper_action_type": "CLOSE",
        "bot_replay_action": "PAPER_CLOSE_REPLAYED",
        "status": "LOCAL_REPLAY",
        "observed_at_ms": now_ms() - 1_000,
        "estimated_net_pnl_usdc": 0.42,
    }]
    app = create_ui_app(settings, state=state)
    before = list((tmp_path / "logs").rglob("*")) if (tmp_path / "logs").exists() else []

    with TestClient(app, raise_server_exceptions=False) as client:
        payload = client.get("/api/simulation/status").json()

    after = list((tmp_path / "logs").rglob("*")) if (tmp_path / "logs").exists() else []
    assert payload["status_projection_pure"] is True
    assert "diagnostic_logs" not in payload
    assert after == before
    assert payload["closed_trades"] == 1''',
    )

    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    fix_portable_imports()
    migrate_writer_owned_tests()
    print("FINALIZER_REGRESSIONS_FIXED")


if __name__ == "__main__":
    main()
