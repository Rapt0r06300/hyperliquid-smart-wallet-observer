from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import hl_observer.runtime.persistent_poll_runner as runner


def test_env_metric_roundtrip_and_invalid(monkeypatch) -> None:
    monkeypatch.setenv("X_INT", "12")
    assert runner._env_int("X_INT", 3) == 12
    monkeypatch.setenv("X_INT", "bad")
    assert runner._env_int("X_INT", 3) == 3
    line = runner.structured_metric_line(
        "equity",
        1001.5,
        session_id="s1",
        timestamp_ms=123,
    )
    parsed = runner.parse_structured_metric_line(line)
    assert parsed == {
        "name": "equity",
        "value": 1001.5,
        "session_id": "s1",
        "timestamp_ms": 123,
    }
    for text in (
        "plain",
        runner.STRUCTURED_METRIC_PREFIX + "bad",
        runner.STRUCTURED_METRIC_PREFIX + "[]",
        runner.STRUCTURED_METRIC_PREFIX + '{"name":"","timestamp_ms":1,"session_id":"s","value":1}',
        runner.STRUCTURED_METRIC_PREFIX + '{"name":"x","timestamp_ms":0,"session_id":"s","value":1}',
        runner.STRUCTURED_METRIC_PREFIX + '{"name":"x","timestamp_ms":"bad","session_id":"s","value":1}',
    ):
        assert runner.parse_structured_metric_line(text) is None


def test_runner_config_paths_and_stop_override(tmp_path, monkeypatch) -> None:
    cfg = runner.RunnerConfig(root=tmp_path)
    assert cfg.logs_dir == tmp_path / "logs"
    assert cfg.logs_to_send_dir.name == "logs à envoyer"
    assert cfg.runtime_data_dir == tmp_path / "runtime" / "data"
    assert cfg.live_log_path.name == "hypersmart_simulation_live.log"
    assert cfg.engine_status_path.name == "hypersmart_engine_status.json"
    assert cfg.stop_file == cfg.runtime_data_dir / "hypersmart_runtime.stop"
    override = tmp_path / "custom.stop"
    monkeypatch.setenv("HYPERSMART_RUNTIME_STOP_FILE", str(override))
    assert cfg.stop_file == override


def test_runner_log_stop_and_status_write(tmp_path, monkeypatch, capsys) -> None:
    cfg = runner.RunnerConfig(root=tmp_path, max_runs=2, max_leaders=5, leaders_per_poll=2)
    subject = runner.PersistentPollRunner(
        cfg,
        invoke=lambda argv: (0, ""),
        sleep_fn=lambda seconds: None,
        now_ms_fn=lambda: 123456,
    )
    subject._session_id = "session-1"
    subject.log("hello")
    assert "hello" in cfg.live_log_path.read_text(encoding="utf-8")
    assert "hello" in capsys.readouterr().out
    assert subject.stop_requested() is False
    cfg.stop_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.stop_file.write_text("stop", encoding="utf-8")
    assert subject.stop_requested() is True

    monkeypatch.setenv("HYPERSMART_SLTP_ENABLED", "1")
    subject.current_poll = 1
    subject.write_engine_status("running", "message")
    payload = json.loads(cfg.engine_status_path.read_text(encoding="utf-8"))
    assert payload["updated_at_ms"] == 123456
    assert payload["session_id"] == "session-1"
    assert payload["phase"] == "running"
    assert payload["read_only"] is True
    assert payload["simulation_only"] is True
    assert payload["external_action"] is False
    assert payload["metrics"]["sltp_enabled"] == "1"


def test_record_output_accepts_current_session_and_suppresses_http_ok(tmp_path, monkeypatch) -> None:
    cfg = runner.RunnerConfig(root=tmp_path)
    subject = runner.PersistentPollRunner(cfg, invoke=lambda argv: (0, ""), now_ms_fn=lambda: 100)
    subject._session_id = "s1"
    logged = []
    monkeypatch.setattr(subject, "log", logged.append)
    current = runner.structured_metric_line("x", 7, session_id="s1", timestamp_ms=10)
    foreign = runner.structured_metric_line("y", 8, session_id="other", timestamp_ms=11)
    output = "\n".join([
        current,
        foreign,
        '{"logger": "httpx", "message":"HTTP/1.1 200 OK"}',
        "ordinary line",
    ])
    subject._record_output("producer", output)
    assert subject.metrics["x"] == "7"
    assert "y" not in subject.metrics
    assert subject.metric_meta["x"]["producer"] == "producer"
    assert "ordinary line" in logged
    assert any("suppressed 1" in line for line in logged)


def test_step_duration_and_run_step_success_recoverable_programmer(tmp_path, monkeypatch) -> None:
    times = iter([100, 130, 130, 200, 220, 220, 300, 310, 310])
    cfg = runner.RunnerConfig(root=tmp_path)
    subject = runner.PersistentPollRunner(
        cfg,
        invoke=lambda argv: (0, runner.structured_metric_line("m", 1, session_id="", timestamp_ms=1)),
        now_ms_fn=lambda: next(times),
    )
    monkeypatch.setattr(subject, "write_engine_status", lambda phase, message: None)
    monkeypatch.setattr(subject, "log", lambda message: None)
    row = subject.run_step(phase="p", message="m", label="step-one", argv=["cmd"])
    assert row.failed is False and row.exit_code == 0
    assert subject.metrics["m"] == "1"
    assert subject.metrics["step_ms_step_one"] == "30"

    def recoverable(argv):
        raise OSError("offline")

    subject._invoke = recoverable
    row = subject.run_step(phase="p", message="m", label="step-two", argv=["cmd"])
    assert row.failed is True and row.exit_code == 1
    assert subject.metrics["step_failed_step_two"] == "1"

    subject._invoke = lambda argv: (_ for _ in ()).throw(AssertionError("bug"))
    with pytest.raises(runner.ProgrammerRunnerError, match="step-three"):
        subject.run_step(phase="p", message="m", label="step-three", argv=["cmd"])


def test_spawn_and_join_ws_scan_success_and_failure(tmp_path, monkeypatch) -> None:
    cfg = runner.RunnerConfig(root=tmp_path)
    cfg.runtime_data_dir.mkdir(parents=True)

    class Process:
        def __init__(self):
            self.waited = []
            self.killed = False
        def wait(self, timeout):
            self.waited.append(timeout)
            return 0
        def kill(self):
            self.killed = True

    process = Process()
    subject = runner.PersistentPollRunner(
        cfg,
        popen=lambda argv, output: process,
        now_ms_fn=lambda: 100,
    )
    monkeypatch.setattr(subject, "log", lambda message: None)
    captured = []
    monkeypatch.setattr(subject, "_record_output", lambda label, output: captured.append((label, output)))
    monkeypatch.setattr(subject, "_add_step_duration", lambda label, start: captured.append(("duration", label)))
    handle = subject._spawn_ws_scan("ws", ["scan"])
    assert handle is not None and handle["label"] == "ws"
    handle["file"].write("hello\n")
    subject._join_ws_scan(handle, timeout_s=2)
    assert process.waited == [2]
    assert ("ws", "hello\n") in captured
    assert not handle["file"].name or not runner.Path(handle["file"].name).exists()

    subject._popen = lambda argv, output: (_ for _ in ()).throw(OSError("boom"))
    assert subject._spawn_ws_scan("bad", ["scan"]) is None
