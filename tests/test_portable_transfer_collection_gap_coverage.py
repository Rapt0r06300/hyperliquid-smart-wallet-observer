from __future__ import annotations

import subprocess
from types import SimpleNamespace

from hl_observer.ops import portable_transfer_proof as proof


class _Process:
    def __init__(self, polls, *, returncode=0, stdin=True, wait_error=None):
        self._polls = iter(polls)
        self.returncode = returncode
        self.stdin = (
            SimpleNamespace(
                write=lambda value: None,
                flush=lambda: None,
                close=lambda: None,
            )
            if stdin
            else None
        )
        self.wait_error = wait_error

    def poll(self):
        return next(self._polls, None)

    def wait(self, timeout):
        if self.wait_error is not None:
            raise self.wait_error
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -15


def test_collection_fails_when_launcher_exits_before_health(tmp_path, monkeypatch) -> None:
    process = _Process([3], returncode=3)
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: process)

    result = proof._collect_and_stop(tmp_path, 0, {})

    assert result["ok"] is False
    assert result["returncode"] == 3
    assert result["reason"] == "launcher_exited_before_health"


def test_collection_fails_closed_on_startup_health_timeout(tmp_path, monkeypatch) -> None:
    process = _Process([None])
    monotonic = iter([0.0, 0.0, 301.0])
    stopped = []
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(proof.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(
        proof,
        "_stop_spawned_launcher",
        lambda root, proc, env: stopped.append(proc),
    )

    result = proof._collect_and_stop(tmp_path, 0, {})

    assert result["ok"] is False
    assert result["reason"] == "ui_health_timeout"
    assert stopped == [process]


def test_collection_detects_launcher_exit_after_health(tmp_path, monkeypatch) -> None:
    process = _Process([None, 17], returncode=17)
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(proof, "_health_ok", lambda url: True)

    result = proof._collect_and_stop(tmp_path, 1, {})

    assert result["ok"] is False
    assert result["returncode"] == 17
    assert result["reason"] == "launcher_exited_during_collection"


def test_collection_fails_closed_when_launcher_stdin_is_unavailable(tmp_path, monkeypatch) -> None:
    process = _Process([None, None], stdin=False)
    stopped = []
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(proof, "_health_ok", lambda url: True)
    monkeypatch.setattr(
        proof,
        "_stop_spawned_launcher",
        lambda root, proc, env: stopped.append(proc),
    )

    result = proof._collect_and_stop(tmp_path, 0, {})

    assert result["ok"] is False
    assert result["reason"] == "collection_exception:launcher_stdin_unavailable"
    assert stopped == [process]


def test_collection_reports_verified_clean_stop_with_fresh_session(tmp_path, monkeypatch) -> None:
    process = _Process([None])
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(proof, "_health_ok", lambda url: True)
    monkeypatch.setattr(
        proof,
        "_latest_complete_session",
        lambda root, not_before: {"ok": True, "run_id": "fresh"},
    )

    result = proof._collect_and_stop(tmp_path, 0.01, {})

    assert result["ok"] is True
    assert result["reason"] == "collection_and_clean_stop_verified"
    assert result["health_samples"] >= 1
    assert result["health_ratio"] == 1.0
    assert result["session"]["run_id"] == "fresh"


def test_collection_fails_closed_when_clean_wait_times_out(tmp_path, monkeypatch) -> None:
    timeout = subprocess.TimeoutExpired("launcher", 300)
    process = _Process([None, None], wait_error=timeout)
    stopped = []
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(proof, "_health_ok", lambda url: True)
    monkeypatch.setattr(
        proof,
        "_stop_spawned_launcher",
        lambda root, proc, env: stopped.append(proc),
    )

    result = proof._collect_and_stop(tmp_path, 0, {})

    assert result["ok"] is False
    assert "collection_exception:" in result["reason"]
    assert stopped == [process]
