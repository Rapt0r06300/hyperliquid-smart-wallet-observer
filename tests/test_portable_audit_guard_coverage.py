from __future__ import annotations

from pathlib import Path
from typing import Any

from hl_observer.ops import portable_audit_guard as guard


def test_inside_treats_unrepresentable_path_as_nonpersistent(monkeypatch, tmp_path: Path) -> None:
    def fail_decode(_path: Any) -> str:
        raise TypeError("synthetic fsdecode failure")

    monkeypatch.setattr(guard.os, "fsdecode", fail_decode)
    assert guard._inside(object(), tmp_path.resolve()) is True


def test_inside_allows_windows_null_devices(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(guard.os, "name", "nt")

    assert guard._inside("NUL", tmp_path.resolve()) is True
    assert guard._inside(r"\\.\NUL", tmp_path.resolve()) is True


def test_record_makes_log_failure_visible_without_escaping(caplog) -> None:
    class BrokenLog:
        def open(self, *_args: Any, **_kwargs: Any) -> Any:
            raise OSError("synthetic audit-log failure")

    import logging

    caplog.set_level(logging.DEBUG, logger=guard.__name__)
    guard._record(BrokenLog(), "open", ("secret",))  # type: ignore[arg-type]

    assert "exception ignoree volontairement ici" in caplog.text
