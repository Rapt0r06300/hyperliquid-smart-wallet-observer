from __future__ import annotations

import json
import signal
import subprocess
from pathlib import Path

import pytest

from hl_observer.ops import autonomous_research_guard as guard


def test_request_identity_reads_fields_and_falls_back_on_invalid_json(tmp_path: Path) -> None:
    request = tmp_path / "fallback-name.json"
    request.write_text(
        json.dumps({"job_id": "job-42", "suite": "economic-full", "mode": "economic"}),
        encoding="utf-8",
    )
    assert guard._request_identity(request) == ("job-42", "economic-full", "economic")

    request.write_text("{", encoding="utf-8")
    assert guard._request_identity(request) == ("fallback-name", None, None)
    request.unlink()
    assert guard._request_identity(request) == ("fallback-name", None, None)


def test_timeout_report_is_explicitly_paper_only(tmp_path: Path) -> None:
    request = tmp_path / "job.json"
    request.write_text(json.dumps({"job_id": "timeboxed"}), encoding="utf-8")
    result_dir = tmp_path / "result"
    guard._write_timeout_report(result_dir, request=request, max_seconds=60, elapsed=61.25)
    payload = json.loads((result_dir / "JOB_GUARD_TIMEOUT.json").read_text(encoding="utf-8"))
    markdown = (result_dir / "JOB_GUARD_TIMEOUT.md").read_text(encoding="utf-8")
    assert payload["job_id"] == "timeboxed"
    assert payload["elapsed_seconds"] == 61.25
    assert payload["process_tree_stopped"] is True
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False
    assert "TIMEBOX_REACHED" in markdown
    assert "Exécution réelle : **NON**" in markdown


def test_terminate_process_tree_noops_for_finished_process(monkeypatch) -> None:
    calls: list[object] = []

    class Process:
        pid = 123

        def poll(self):
            return 0

    monkeypatch.setattr(guard.os, "killpg", lambda *args: calls.append(args))
    guard._terminate_process_tree(Process())
    assert calls == []


def test_terminate_process_tree_posix_stops_on_sigterm(monkeypatch) -> None:
    calls: list[tuple[int, signal.Signals]] = []

    class Process:
        pid = 321

        def poll(self):
            return None

        def wait(self, timeout=None):
            assert timeout == 3.0
            return 0

    monkeypatch.setattr(guard.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    guard._terminate_process_tree(Process(), grace_seconds=3.0)
    assert calls == [(321, signal.SIGTERM)]


def test_terminate_process_tree_posix_escalates_to_sigkill(monkeypatch) -> None:
    calls: list[tuple[int, signal.Signals]] = []
    waits: list[object] = []

    class Process:
        pid = 654

        def poll(self):
            return None

        def wait(self, timeout=None):
            waits.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired("worker", timeout)
            return 0

    monkeypatch.setattr(guard.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    guard._terminate_process_tree(Process(), grace_seconds=0.01)
    assert calls == [(654, signal.SIGTERM), (654, signal.SIGKILL)]
    assert waits == [0.01, None]


def test_terminate_process_tree_tolerates_disappearing_group(monkeypatch) -> None:
    class Process:
        pid = 777

        def poll(self):
            return None

    def gone(*args):
        raise ProcessLookupError

    monkeypatch.setattr(guard.os, "killpg", gone)
    guard._terminate_process_tree(Process())


def test_stdout_pump_handles_no_stream_and_iterable_stream(capsys) -> None:
    class EmptyProcess:
        pid = 1
        stdout = None

    thread = guard._start_stdout_pump(EmptyProcess())
    thread.join(timeout=1)
    assert not thread.is_alive()

    class StreamProcess:
        pid = 2
        stdout = ["a\n", "b\n"]

    thread = guard._start_stdout_pump(StreamProcess())
    thread.join(timeout=1)
    assert capsys.readouterr().out == "a\nb\n"


def test_finalize_success_covers_complete_and_prepare_only(monkeypatch, tmp_path: Path, capsys) -> None:
    kwargs = {
        "request": tmp_path / "request.json",
        "project_root": tmp_path / "project",
        "lab_root": tmp_path / "lab",
        "result_dir": tmp_path / "result",
    }
    monkeypatch.setattr(
        guard,
        "finalize_autonomous_completion",
        lambda **values: {
            "analysis_complete": True,
            "suite": "economic-full",
            "completion_registry_path": "registry.json",
        },
    )
    assert guard._finalize_success(**kwargs) == 0
    assert "ALINA_COMPLETION_OK" in capsys.readouterr().out

    monkeypatch.setattr(
        guard,
        "finalize_autonomous_completion",
        lambda **values: {"analysis_complete": False},
    )
    assert guard._finalize_success(**kwargs) == 0
    assert "ALINA_PREPARE_ONLY_OK" in capsys.readouterr().out


def test_finalize_success_maps_completion_errors_fail_closed(monkeypatch, tmp_path: Path) -> None:
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    kwargs = {
        "request": tmp_path / "request.json",
        "project_root": tmp_path / "project",
        "lab_root": tmp_path / "lab",
        "result_dir": result_dir,
    }

    def fail(**values):
        raise guard.AutonomousCompletionError("forced")

    monkeypatch.setattr(guard, "finalize_autonomous_completion", fail)
    (result_dir / "JOB_RESULT.json").write_text(
        json.dumps({"exit_code": guard.REGISTRY_EXIT_CODE}), encoding="utf-8"
    )
    assert guard._finalize_success(**kwargs) == guard.REGISTRY_EXIT_CODE

    (result_dir / "JOB_RESULT.json").write_text(
        json.dumps({"exit_code": 999}), encoding="utf-8"
    )
    assert guard._finalize_success(**kwargs) == guard.COMPLETION_EXIT_CODE

    (result_dir / "JOB_RESULT.json").write_text("{", encoding="utf-8")
    assert guard._finalize_success(**kwargs) == guard.COMPLETION_EXIT_CODE


def test_run_guarded_returns_worker_code_and_low_level_success(monkeypatch, tmp_path: Path) -> None:
    class Process:
        stdout = None
        pid = 10

        def __init__(self, code: int):
            self.returncode = code

        def poll(self):
            return self.returncode

    processes = iter([Process(7), Process(0)])
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *args, **kwargs: next(processes))
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(ticks))
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")

    assert guard.run_guarded(
        ["worker"], max_seconds=60, result_dir=tmp_path / "r1", request=request
    ) == 7
    assert guard.run_guarded(
        ["worker"], max_seconds=60, result_dir=tmp_path / "r2", request=request
    ) == 0


def test_run_guarded_success_calls_completion_when_roots_are_present(monkeypatch, tmp_path: Path) -> None:
    class Process:
        stdout = None
        pid = 11
        returncode = 0

        def poll(self):
            return 0

    monkeypatch.setattr(guard.subprocess, "Popen", lambda *args, **kwargs: Process())
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(guard, "_finalize_success", lambda **kwargs: 24)
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    assert guard.run_guarded(
        ["worker"],
        max_seconds=60,
        result_dir=tmp_path / "result",
        request=request,
        lab_root=tmp_path / "lab",
        project_root=tmp_path / "project",
    ) == 24


def test_main_builds_force_command_and_rejects_too_short_timebox(monkeypatch, tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    base = [
        "--request", str(request),
        "--project-root", str(tmp_path),
        "--lab-root", str(tmp_path / "lab"),
        "--result-dir", str(tmp_path / "result"),
    ]
    assert guard.main([*base, "--max-seconds", "59"]) == 2

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return 17

    monkeypatch.setattr(guard, "run_guarded", fake_run)
    assert guard.main([*base, "--max-seconds", "60", "--force"]) == 17
    command = captured["command"]
    assert isinstance(command, list)
    assert command[-1] == "--force"
    assert captured["max_seconds"] == 60
