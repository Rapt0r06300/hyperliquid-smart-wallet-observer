from typer.testing import CliRunner

from hl_observer.cli import app


def test_autoscan_command_exists():
    result = CliRunner().invoke(app, ["autoscan", "--help"])

    assert result.exit_code == 0
    assert "startup scan" in result.output or "autoscan" in result.output


def test_autoscan_attempts_sources_even_when_empty():
    result = CliRunner().invoke(app, ["autoscan", "--dry-run", "--report"])

    assert result.exit_code == 0
    assert "leaderboard" in result.output
    assert "explorer" in result.output
    assert "sources essayees:" in result.output


def test_autoscan_does_not_fake_results():
    result = CliRunner().invoke(app, ["autoscan", "--dry-run", "--report"])

    assert result.exit_code == 0
    assert "Aucun wallet n'a ete invente" in result.output

