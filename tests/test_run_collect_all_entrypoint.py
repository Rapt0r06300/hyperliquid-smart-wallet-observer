from __future__ import annotations

import runpy
import sys
from types import SimpleNamespace

import pytest

from hl_observer.collection import collect_all
from hl_observer.config import loader as config_loader


class _Report:
    ok = True

    @staticmethod
    def summary() -> str:
        return "collect-all entrypoint isolated"


def test_module_entrypoint_exits_zero_without_real_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise the production ``python -m`` entrypoint with all I/O isolated."""
    monkeypatch.setattr(
        config_loader,
        "load_settings",
        lambda: SimpleNamespace(
            database_url="sqlite:///unused.db",
            wallet_scanner=SimpleNamespace(
                scan_max_wallets_per_run=1,
                scan_batch_size=1,
            ),
        ),
    )
    monkeypatch.setattr(collect_all, "run_steps", lambda _steps: _Report())
    monkeypatch.setattr(sys, "argv", ["run_collect_all"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module(
            "hl_observer.collection.run_collect_all",
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert "collect-all entrypoint isolated" in capsys.readouterr().out
