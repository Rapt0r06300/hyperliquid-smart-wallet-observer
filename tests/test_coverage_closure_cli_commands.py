from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

import hl_observer.cli as cli


class _Session:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def scalars(self, statement):
        return SimpleNamespace(all=lambda: list(self.rows))


class _Factory:
    def __init__(self, session) -> None:
        self.session = session

    def __call__(self):
        return self.session


def _settings():
    return SimpleNamespace(
        log_level="INFO",
        database_url="sqlite:///unit.db",
        logs_dir="logs",
        execution=SimpleNamespace(enable_mainnet_execution=False, enable_testnet_execution=False),
    )


def test_doctor_success_and_failure(monkeypatch, capsys) -> None:
    settings = _settings()
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)
    monkeypatch.setattr(cli, "info_url_for_settings", lambda value: "https://unit/info")
    monkeypatch.setattr(cli, "run_safety_audit", lambda root: SimpleNamespace(ok=True))
    monkeypatch.setattr(Path, "exists", lambda self: True)
    cli.doctor()
    out = capsys.readouterr().out
    assert "python_3_11_plus: ok" in out
    assert "safety_audit_ok: ok" in out

    bad = _settings()
    bad.execution.enable_mainnet_execution = True
    monkeypatch.setattr(cli, "load_settings", lambda: bad)
    with pytest.raises(typer.Exit):
        cli.doctor()


def test_init_db_and_safety_audit_aliases(monkeypatch, capsys) -> None:
    settings = _settings()
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    initialized = []
    monkeypatch.setattr(cli, "initialize_database", lambda url: initialized.append(url))
    cli.init_db()
    assert initialized == ["sqlite:///unit.db"]
    assert "database initialized" in capsys.readouterr().out

    audit = SimpleNamespace(ok=True, checks={"paper": True}, findings=["none"])
    monkeypatch.setattr(cli, "run_safety_audit", lambda root: audit)
    cli.safety_audit()
    out = capsys.readouterr().out
    assert "paper: ok" in out and "finding: none" in out

    called = []
    monkeypatch.setattr(cli, "safety_audit", lambda: called.append(True))
    cli.audit_safety()
    assert called == [True]

    monkeypatch.setattr(cli, "run_safety_audit", lambda root: SimpleNamespace(ok=False, checks={"paper": False}, findings=[]))
    monkeypatch.setattr(cli, "safety_audit", cli.__dict__["safety_audit"])


def test_safety_audit_failure_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "run_safety_audit",
        lambda root: SimpleNamespace(ok=False, checks={"paper": False}, findings=["bad"]),
    )
    with pytest.raises(typer.Exit):
        cli.safety_audit()


def test_runtime_reports_and_write_check(monkeypatch, tmp_path, capsys) -> None:
    settings = _settings()
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "scan_runtime_hygiene", lambda value: SimpleNamespace(ok=True))
    monkeypatch.setattr(cli, "format_runtime_hygiene_report", lambda report: "HYGIENE_OK")
    cli.runtime_check()
    assert "HYGIENE_OK" in capsys.readouterr().out

    cli.runtime_clean_report()
    out = capsys.readouterr().out
    assert "HYGIENE_OK" in out
    assert "CREER_ARCHIVE_PROPRE" in out
    assert "no runtime file is deleted" in out

    report = SimpleNamespace(ok=True)
    monkeypatch.setattr(cli, "check_runtime_write_readiness", lambda path, stale_after_seconds: report)
    monkeypatch.setattr(cli, "format_runtime_write_readiness", lambda value: "WRITE_READY")
    cli.runtime_write_check(from_logs=tmp_path, stale_after_seconds=12)
    assert "WRITE_READY" in capsys.readouterr().out


def test_prepare_simulation_logs_with_and_without_purge(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_settings", lambda: _settings())
    monkeypatch.setattr(cli, "prepare_fresh_simulation_logs", lambda root, dry_run: SimpleNamespace(root=root, dry=dry_run))
    monkeypatch.setattr(cli, "format_prepared_session_logs", lambda report: "PREPARED")
    monkeypatch.setattr(cli, "purge_stale_top_level_logs", lambda root, dry_run: SimpleNamespace(root=root, dry=dry_run))
    monkeypatch.setattr(cli, "format_purged_logs", lambda report: "PURGED")

    cli.prepare_simulation_logs(dry_run=True, purge_top_level=True)
    out = capsys.readouterr().out
    assert "PREPARED" in out and "PURGED" in out

    cli.prepare_simulation_logs(dry_run=False, purge_top_level=False)
    out = capsys.readouterr().out
    assert "PREPARED" in out and "PURGED" not in out


def test_live_user_fills_stream_no_leaders(monkeypatch, capsys) -> None:
    settings = _settings()
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_session_factory", lambda value: _Factory(_Session([])))
    cli.live_user_fills_stream(duration_seconds=0, max_leaders=3, network_read=False, max_reconnects=-1)
    assert "no_leaders_available" in capsys.readouterr().out


def test_live_user_fills_stream_success_and_quality_gate_error(monkeypatch, capsys) -> None:
    settings = _settings()
    rows = [SimpleNamespace(wallet_address="0x" + "1" * 40)]
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_session_factory", lambda value: _Factory(_Session(rows)))
    errors = []

    def quality_gate(session, current_rows, *, limit):
        errors.append("quality")
        raise RuntimeError("quality unavailable")

    monkeypatch.setattr(cli, "_apply_leader_quality_gate", quality_gate)
    monkeypatch.setattr(cli, "_noter_echec", lambda value: errors.append(value))

    async def stream(*args, **kwargs):
        assert kwargs["network_read"] is False
        assert kwargs["max_reconnects"] == 2
        return SimpleNamespace(
            connects=1,
            reconnects=0,
            fresh_fills_stored=2,
            deltas_stored=1,
            last_fill_age_ms=5,
            stopped_reason="unit",
        )

    monkeypatch.setattr(cli, "stream_user_fills_ws", stream)
    cli.live_user_fills_stream(duration_seconds=0, max_leaders=1, network_read=False, max_reconnects=2)
    out = capsys.readouterr().out
    assert "wallets=1" in out
    assert "fresh_fills_stored=2" in out
    assert "read-only persistent" in out
    assert any(str(value).startswith("hl_observer/cli.py") for value in errors)


def test_simulation_readiness_and_archive_commands(monkeypatch, tmp_path, capsys) -> None:
    settings = _settings()
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_simulation_readiness_report", lambda *args, **kwargs: SimpleNamespace(ok=True))
    monkeypatch.setattr(cli, "format_simulation_readiness", lambda report: "READY")
    cli.simulation_readiness(from_logs=tmp_path, fresh_window_seconds=7)
    assert "READY" in capsys.readouterr().out

    audit_path = tmp_path / "audit.md"
    monkeypatch.setattr(cli, "write_archive_audit_report", lambda root: audit_path)
    cli.archive_audit()
    assert str(audit_path) in capsys.readouterr().out

    monkeypatch.chdir(tmp_path)
    result = SimpleNamespace(archive_path=tmp_path / "clean.zip", files_copied=3, entries=4)
    monkeypatch.setattr(cli, "create_clean_archive", lambda root: result)
    monkeypatch.setattr(cli, "write_archive_audit_report", lambda root: audit_path)
    cli.create_clean_archive_command()
    out = capsys.readouterr().out
    assert "clean archive created" in out
    assert "files copied: 3" in out
    assert "zip entries: 4" in out


def test_scanner_priority_report_is_bounded_and_read_only(monkeypatch, tmp_path, capsys) -> None:
    settings = _settings()
    row = SimpleNamespace(
        wallet_address="0x" + "2" * 40,
        source="unit",
        score=80.0,
        selected_at_ms=900,
    )
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_session_factory", lambda value: _Factory(_Session()))
    monkeypatch.setattr(cli, "_selected_top_wallet_rows", lambda session, limit, offset: [row])
    monkeypatch.setattr(cli, "now_ms", lambda: 1000)
    monkeypatch.setattr(cli, "score_wallet_priority", lambda value: SimpleNamespace(wallet_address=value.wallet_address, priority_score=91.0, source=value.source))
    selection = SimpleNamespace(
        selected_wallets=[SimpleNamespace(wallet_address=row.wallet_address, priority_score=91.0, source="unit")],
        skipped=[SimpleNamespace(wallet_address="0x" + "3" * 40)],
    )
    monkeypatch.setattr(cli, "select_wallets_for_warm_scan", lambda candidates, budget: selection)
    monkeypatch.setattr(cli, "evaluate_warm_scan_budget", lambda budget, requested_wallets: SimpleNamespace(reason="OK", estimated_weight=1))
    monkeypatch.setattr(cli, "write_missed_opportunity_reports", lambda skipped, output_dir, stem: {"markdown": tmp_path / "missed.md"})

    cli.scanner_priority_report(network_read=False, max_leaders=1, output_dir=tmp_path)
    out = capsys.readouterr().out
    assert "research_only" in out
    assert "network_read=disabled" in out
    assert "SELECT" in out
    assert "missed_opportunity_report" in out
