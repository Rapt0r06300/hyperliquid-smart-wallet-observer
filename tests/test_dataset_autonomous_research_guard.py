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


def test_guard_ecrit_un_rapport_et_un_statut_cockpit_apres_timebox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = tmp_path / "job.json"
    request.write_text(
        json.dumps({"job_id": "job-timebox", "suite": "economic-full", "mode": "economic"}),
        encoding="utf-8",
    )
    result_dir = tmp_path / "result"
    lab_root = tmp_path / "lab"

    class FakeStdout:
        def readline(self):
            return ""

        def __iter__(self):
            return iter(())

    class FakeProcess:
        def __init__(self):
            self.stdout = FakeStdout()
            self.returncode = None
            self.stopped = False
            self.pid = 12345

        def poll(self):
            return None if not self.stopped else 124

    fake = FakeProcess()
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *args, **kwargs: fake)

    stopped: list[int] = []

    def fake_stop(process, **kwargs):
        process.stopped = True
        process.returncode = 124
        stopped.append(process.pid)

    monkeypatch.setattr(guard, "_terminate_process_tree", fake_stop)
    ticks = iter([0.0, 61.0, 61.0])
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(ticks, 61.0))

    rc = guard.run_guarded(
        ["python", "worker"],
        max_seconds=60,
        result_dir=result_dir,
        request=request,
        lab_root=lab_root,
    )
    assert rc == 124
    assert stopped == [12345]

    payload = json.loads((result_dir / "JOB_GUARD_TIMEOUT.json").read_text(encoding="utf-8"))
    assert payload["status"] == "TIMEBOX_REACHED"
    assert payload["resume_expected"] is True
    assert payload["process_tree_stopped"] is True
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False

    live = json.loads((lab_root / "status" / "CURRENT_STATUS.json").read_text(encoding="utf-8"))
    assert live["state"] == "TIMEBOX_REACHED"
    assert live["job_id"] == "job-timebox"
    assert live["suite"] == "economic-full"
    assert live["mode"] == "economic"
    assert live["extra"]["resume_expected"] is True
    assert live["extra"]["process_tree_stopped"] is True
    assert live["paper_only"] is True
    assert live["real_execution"] is False


def test_groupe_de_processus_est_isole_selon_le_systeme() -> None:
    windows = guard._popen_process_group_kwargs("nt")
    expected = int(
        getattr(
            guard.subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            guard.WINDOWS_CREATE_NEW_PROCESS_GROUP,
        )
    )
    assert windows["creationflags"] == expected
    assert guard._popen_process_group_kwargs("posix") == {"start_new_session": True}
