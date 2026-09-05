from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer

import hl_observer.cli as cli


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_hot_watch_refuses_non_dry_run_before_settings_or_network(monkeypatch) -> None:
    output: list[str] = []
    monkeypatch.setattr(cli.typer, "echo", lambda value="": output.append(str(value)))
    monkeypatch.setattr(
        cli,
        "_settings",
        lambda: (_ for _ in ()).throw(AssertionError("settings must not load after safety refusal")),
    )

    with pytest.raises(typer.Exit) as exc_info:
        cli.hot_watch(network_read=True, duration_seconds=60, dry_run=False)

    assert exc_info.value.exit_code == 2
    assert output == ["Safety refused: hot-watch remains dry-run/read-only in this build."]


def test_hot_watch_dry_run_builds_local_read_only_rotation_plan(monkeypatch) -> None:
    settings = SimpleNamespace()
    rows = [
        SimpleNamespace(wallet_address="0xaaa", score=91.5, selected_at_ms=900),
        SimpleNamespace(wallet_address="0xbbb", score=82.0, selected_at_ms=800),
    ]
    slots = [
        SimpleNamespace(slot_id=1, wallet_address="0xaaa", priority=91.5, expires_at_ms=8000),
    ]
    output: list[str] = []
    rotate_calls: list[tuple[object, int, int, int]] = []

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_session_factory", lambda current: lambda: _Session())
    monkeypatch.setattr(cli, "_selected_top_wallet_rows", lambda session, *, limit: rows)
    monkeypatch.setattr(cli, "now_ms", lambda: 1000)

    def _rotate(candidates, *, now_ms, max_slots, slot_ttl_ms):
        rotate_calls.append((candidates, now_ms, max_slots, slot_ttl_ms))
        return slots

    monkeypatch.setattr(cli, "rotate_hot_watch", _rotate)
    monkeypatch.setattr(cli.typer, "echo", lambda value="": output.append(str(value)))

    cli.hot_watch(network_read=True, duration_seconds=7, dry_run=True)

    assert rotate_calls == [
        ([('0xaaa', 91.5, 900), ('0xbbb', 82.0, 800)], 1000, 10, 7000)
    ]
    assert output == [
        "hot_watch_plan=read_only_dry_run",
        "network_read=enabled",
        "duration_seconds=7",
        "slots=1 max_unique_users=10",
        "SLOT 1 0xaaa priority=91.50 expires_at_ms=8000",
    ]
