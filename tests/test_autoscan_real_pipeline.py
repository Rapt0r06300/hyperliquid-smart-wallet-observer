from typer.testing import CliRunner

from hl_observer.cli import app


def _isolate_runtime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{(tmp_path / 'autoscan.sqlite3').as_posix()}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))


def test_autoscan_command_exists():
    result = CliRunner().invoke(app, ["autoscan", "--help"])

    assert result.exit_code == 0
    assert "startup scan" in result.output or "autoscan" in result.output


def test_autoscan_attempts_sources_even_when_empty(tmp_path, monkeypatch):
    _isolate_runtime(tmp_path, monkeypatch)
    result = CliRunner().invoke(app, ["autoscan", "--dry-run", "--report"])

    assert result.exit_code == 0
    assert "leaderboard" in result.output
    assert "explorer" in result.output
    assert "sources essayees:" in result.output


def test_autoscan_does_not_fake_results(tmp_path, monkeypatch):
    _isolate_runtime(tmp_path, monkeypatch)
    result = CliRunner().invoke(app, ["autoscan", "--dry-run", "--report"])

    assert result.exit_code == 0
    assert "Aucun wallet n'a ete invente" in result.output
