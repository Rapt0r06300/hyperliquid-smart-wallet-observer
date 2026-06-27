from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_test_logs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests from appending diagnostics to the real runtime logs.

    Simulation endpoints export JSON/JSONL/Markdown diagnostics on each call.
    The project logs under ``logs/logs a envoyer`` are the user's real evidence
    bundle, so every pytest case gets a throwaway log directory unless it
    explicitly overrides ``settings.logs_dir`` itself.
    """

    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
