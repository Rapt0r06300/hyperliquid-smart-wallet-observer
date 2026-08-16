from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.ops import autonomous_research_guard as guard


def test_guard_refuse_une_timebox_superieure_a_18_heures(tmp_path: Path) -> None:
    request = tmp_path / "job.json"
    request.write_text(json.dumps({"job_id": "job-1"}), encoding="utf-8")
    rc = guard.main(
        [
            "--request",
            str(request),
            "--project-root",
            str(tmp_path),
            "--lab-root",
            str(tmp_path / "lab"),
            "--result-dir",
            str(tmp_path / "result"),
            "--max-seconds",
            str(guard.MAX_ALLOWED_SECONDS + 1),
        ]
    )
    assert rc == 2


def test_guard_ecrit_un_rapport_reprise_si_le_processus_depasse_la_timebox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = tmp_path / "job.json"
    request.write_text(json.dumps({"job_id": "job-timebox"}), encoding="utf-8")
    result_dir = tmp_path / "result"

    class FakeStdout:
        def readline(self):
            return ""

        def __iter__(self):
            return iter(())

    class FakeProcess:
        def __init__(self):
            self.stdout = FakeStdout()
            self.returncode = None
            self.terminated = False

        def poll(self):
            return None if not self.terminated else 124

        def terminate(self):
            self.terminated = True
            self.returncode = 124

        def wait(self, timeout=None):
            self.returncode = 124
            return 124

        def kill(self):
            self.terminated = True
            self.returncode = 124

    fake = FakeProcess()
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *args, **kwargs: fake)
    ticks = iter([0.0, 61.0, 61.0])
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(ticks, 61.0))

    rc = guard.run_guarded(
        ["python", "worker"],
        max_seconds=60,
        result_dir=result_dir,
        request=request,
    )
    assert rc == 124
    payload = json.loads((result_dir / "JOB_GUARD_TIMEOUT.json").read_text(encoding="utf-8"))
    assert payload["status"] == "TIMEBOX_REACHED"
    assert payload["resume_expected"] is True
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False
