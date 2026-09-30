from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from hl_observer.ops import autonomous_research_job as canonical_job


def test_module_entrypoint_propagates_canonical_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the production ``python -m`` entrypoint without any real execution."""
    monkeypatch.setattr(
        canonical_job,
        "_load_request",
        lambda _path: {"mode": "archive", "suite": "sqlite-all-safe"},
    )
    monkeypatch.setattr(canonical_job, "execute_job", lambda *args, **kwargs: 9)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "autonomous_research_job_router",
            "--request",
            str(tmp_path / "request.json"),
            "--project-root",
            str(tmp_path / "project"),
            "--lab-root",
            str(tmp_path / "lab"),
            "--result-dir",
            str(tmp_path / "result"),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module(
            "hl_observer.ops.autonomous_research_job_router",
            run_name="__main__",
        )

    assert exc_info.value.code == 9
