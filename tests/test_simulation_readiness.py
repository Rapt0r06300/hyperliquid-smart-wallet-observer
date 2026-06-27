from __future__ import annotations

import json

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.config.loader import load_settings
from hl_observer.simulation.readiness import (
    STATUS_ACTIVE,
    STATUS_OBSERVING,
    STATUS_WAITING_DELTAS,
    STATUS_WAITING_FRESH_LEADERS,
    STATUS_WAITING_LEADERS,
    build_simulation_readiness_report,
    format_simulation_readiness,
)
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import PositionDeltaModel, TopWallet
from hl_observer.utils.time import now_ms


def _settings_for_tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "data" / "simulation_readiness.sqlite3"
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    settings = load_settings()
    init_db(settings.database_url)
    return settings


def _factory(settings):
    return create_session_factory(create_sqlite_engine(settings.database_url))


def _add_selected_leader(settings, *, selected_at_ms: int | None = None) -> None:
    selected_at_ms = selected_at_ms or now_ms()
    with _factory(settings)() as session:
        session.add(
            TopWallet(
                wallet_address="0x" + "1" * 40,
                rank=1,
                source="test",
                score=91.0,
                selected_at_ms=selected_at_ms,
                status="selected",
                notes="simulation readiness test leader",
            )
        )
        session.commit()


def _add_fresh_entry_delta(settings, *, detected_at_ms: int | None = None) -> None:
    detected_at_ms = detected_at_ms or now_ms()
    with _factory(settings)() as session:
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "1" * 40,
                coin="HYPE",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=100.0,
                action="OPEN_LONG",
                exchange_ts=detected_at_ms,
                side="long",
                price=10.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence="high",
                confidence_score=0.95,
                detected_at_ms=detected_at_ms,
                source="test",
                is_paper_eligible=True,
                raw_json={"source": "test"},
            )
        )
        session.commit()


def test_simulation_readiness_waits_for_selected_leaders(tmp_path, monkeypatch):
    settings = _settings_for_tmp_db(tmp_path, monkeypatch)
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()

    report = build_simulation_readiness_report(settings, log_dir=log_dir)
    text = format_simulation_readiness(report)

    assert report.status == STATUS_WAITING_LEADERS
    assert report.db_readable is True
    assert report.db_writable is True
    assert "orders_created=0" in text
    assert "real_orders_created=0" in text
    assert "simulation_positions_are_virtual=true" in text
    assert "execution=forbidden" in text
    assert "leaders_selected=0" in text


def test_simulation_readiness_waits_for_fresh_deltas_after_leader_selection(tmp_path, monkeypatch):
    settings = _settings_for_tmp_db(tmp_path, monkeypatch)
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _add_selected_leader(settings)

    report = build_simulation_readiness_report(settings, log_dir=log_dir)

    assert report.status == STATUS_WAITING_DELTAS
    assert report.leaders_selected == 1
    assert report.recent_deltas == 0
    assert report.fresh_entry_deltas == 0


def test_simulation_readiness_detects_stale_selected_leaders(tmp_path, monkeypatch):
    settings = _settings_for_tmp_db(tmp_path, monkeypatch)
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _add_selected_leader(settings, selected_at_ms=now_ms() - 10 * 60_000)

    report = build_simulation_readiness_report(settings, log_dir=log_dir)
    text = format_simulation_readiness(report)

    assert report.status == STATUS_WAITING_FRESH_LEADERS
    assert report.leaders_selected == 1
    assert report.fresh_leaders_selected == 0
    assert "fresh_leaders_selected=0" in text


def test_simulation_readiness_reports_observing_when_entry_delta_has_no_virtual_fill(tmp_path, monkeypatch):
    settings = _settings_for_tmp_db(tmp_path, monkeypatch)
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_latest.jsonl").write_text(
        json.dumps(
            {
                "status": "REFUSED",
                "bot_decision": "NO_TRADE",
                "reason": "EDGE_REMAINING_TOO_LOW",
                "execution": "forbidden",
                "research_only": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _add_selected_leader(settings)
    _add_fresh_entry_delta(settings)

    report = build_simulation_readiness_report(settings, log_dir=log_dir)
    text = format_simulation_readiness(report)

    assert report.status == STATUS_OBSERVING
    assert report.recent_deltas == 1
    assert report.fresh_entry_deltas == 1
    assert report.virtual_entries_logged == 0
    assert report.virtual_refusals_logged == 1
    assert "EDGE_REMAINING_TOO_LOW" in text
    assert "positions virtuelles" in text.lower() or "entrees virtuelles" in text.lower()


def test_simulation_readiness_reports_active_when_virtual_entries_are_logged(tmp_path, monkeypatch):
    settings = _settings_for_tmp_db(tmp_path, monkeypatch)
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_decisions_latest.jsonl").write_text(
        json.dumps(
            {
                "status": "ACCEPTED",
                "bot_decision": "VIRTUAL_POSITION_OPENED",
                "coin": "HYPE",
                "estimated_net_pnl_usdc": 0,
                "execution": "forbidden",
                "research_only": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _add_selected_leader(settings)
    _add_fresh_entry_delta(settings)

    report = build_simulation_readiness_report(settings, log_dir=log_dir)

    assert report.status == STATUS_ACTIVE
    assert report.virtual_entries_logged == 1
    assert report.orders_created == 0
    assert report.real_orders_created == 0


def test_simulation_readiness_cli_explains_virtual_positions_and_real_order_guard(tmp_path, monkeypatch):
    settings = _settings_for_tmp_db(tmp_path, monkeypatch)
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _add_selected_leader(settings)

    result = CliRunner().invoke(
        app,
        [
            "simulation-readiness",
            "--from-logs",
            str(log_dir),
            "--fresh-window-seconds",
            "20",
        ],
    )

    assert result.exit_code == 0
    assert f"database_url={settings.database_url}" in result.output
    assert "simulation_readiness=paper_read_only" in result.output
    assert "status=WAITING_FOR_FRESH_DELTAS" in result.output
    assert "virtual_entries_logged=0" in result.output
    assert "virtual_position_actions_logged=0" in result.output
    assert "orders_created=0" in result.output
    assert "real_orders_created=0" in result.output
    assert "simulation_positions_are_virtual=true" in result.output
    assert "execution=forbidden" in result.output
