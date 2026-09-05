from __future__ import annotations

import runpy


def test_module_entrypoint_invokes_cli_app(monkeypatch) -> None:
    calls: list[bool] = []

    monkeypatch.setattr("hl_observer.cli.app", lambda: calls.append(True))

    runpy.run_module("hl_observer.__main__", run_name="__main__")

    assert calls == [True]
