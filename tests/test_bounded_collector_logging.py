from __future__ import annotations

from pathlib import Path

from tools import run_bounded_collector


def test_bounded_collector_log_rotates_without_exceeding_configured_limit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime" / "logs" / "economic-demo.log"
    with run_bounded_collector._BoundedLog(
        path, max_bytes=16, backup_count=2,
    ) as output:
        output.write("first-line-123\n")
        output.write("second-line-12\n")
        output.write("third-line-1234\n")

    paths = [path, path.with_name(path.name + ".1"), path.with_name(path.name + ".2")]
    assert all(item.is_file() and item.stat().st_size <= 16 for item in paths)
    assert "first-line-123" in path.with_name(path.name + ".2").read_text(encoding="utf-8")
    assert "third-line-1234" in path.read_text(encoding="utf-8")


def test_bounded_collector_persists_child_stdout_and_stderr(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "worker.py"
    script.write_text(
        "print('visible-worker-stdout', flush=True)\n"
        "import sys\n"
        "print('visible-worker-stderr', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )
    checks = 0

    def valid_until_worker_exits(*_args, **_kwargs):
        nonlocal checks
        checks += 1
        if checks < 3:
            return True, "", {"lease_id": "logging-test", "expires_at_ms": 9_999_999_999_999}
        return False, "TEST_LEASE_ENDED", None

    monkeypatch.setattr(run_bounded_collector, "validate_lease", valid_until_worker_exits)

    result = run_bounded_collector.run(
        root=tmp_path,
        name="logging-test",
        script=script,
        interval_s=5.0,
        lease_file=tmp_path / "lease.json",
        lease_token="logging-test-token",
        script_args=[],
    )

    log = (tmp_path / "runtime" / "logs" / "economic-logging-test.log").read_text(
        encoding="utf-8",
    )
    assert result == 0
    assert "visible-worker-stdout" in log
    assert "visible-worker-stderr" in log
