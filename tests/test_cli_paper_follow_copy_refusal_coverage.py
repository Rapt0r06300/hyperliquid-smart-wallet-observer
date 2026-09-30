from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer

import hl_observer.cli as cli


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def commit(self) -> None:
        self.commits += 1


def test_paper_follow_dry_run_skips_order_creation_and_commit(monkeypatch) -> None:
    settings = SimpleNamespace()
    session = _Session()
    output: list[str] = []

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_session_factory", lambda current: lambda: session)
    monkeypatch.setattr(
        cli,
        "create_paper_follow_orders",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run must not create even simulated follow orders")
        ),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda value="": output.append(str(value)))

    cli.paper_follow_command(max_signals=7, dry_run=True, report=True)

    assert session.commits == 0
    assert output == [
        "paper follow report",
        "simulated orders created: 0",
        "dry-run: True",
    ]


def test_paper_follow_paper_mode_creates_only_simulated_orders(monkeypatch) -> None:
    settings = SimpleNamespace()
    session = _Session()
    calls: list[int] = []
    output: list[str] = []

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_session_factory", lambda current: lambda: session)

    def _create(current, *, max_signals: int) -> int:
        assert current is session
        calls.append(max_signals)
        return 3

    monkeypatch.setattr(cli, "create_paper_follow_orders", _create)
    monkeypatch.setattr(cli.typer, "echo", lambda value="": output.append(str(value)))

    cli.paper_follow_command(max_signals=7, dry_run=False, report=False)

    assert calls == [7]
    assert session.commits == 1
    assert output == [
        "paper follow report",
        "simulated orders created: 3",
        "dry-run: False",
    ]


def test_copy_run_refuses_non_dry_run_before_database_or_network(monkeypatch) -> None:
    settings = SimpleNamespace()
    output: list[str] = []

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_session_factory",
        lambda current: (_ for _ in ()).throw(
            AssertionError("copy-run refusal must happen before database access")
        ),
    )
    monkeypatch.setattr(cli.typer, "echo", lambda value="": output.append(str(value)))

    with pytest.raises(typer.Exit) as exc_info:
        cli.copy_run_command(dry_run=False)

    assert exc_info.value.exit_code == 1
    assert output == [
        "copy-run refused: Batch 1 is dry-run only; no orders and no testnet execution."
    ]
