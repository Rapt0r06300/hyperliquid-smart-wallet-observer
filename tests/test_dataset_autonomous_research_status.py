from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from hl_observer.ops import autonomous_research_job as worker
from hl_observer.ops.autonomous_research_status import STATUS_SCHEMA, status_path, write_status


def test_status_est_atomique_lisible_et_reste_paper_only(tmp_path: Path) -> None:
    path = status_path(tmp_path)
    payload = write_status(
        path,
        job_id="job-1",
        suite="economic-full",
        mode="economic",
        state="RUNNING",
        action_fr="Backtest",
        message_fr="Le moteur travaille.",
        job_started_unix=time.time() - 2,
        stage_started_unix=time.time() - 1,
        step_index=3,
        step_total=4,
        next_action_fr="Audit",
        log_path="C:/lab/log.txt",
        last_log_line="progression 42%",
        progress_percent=42,
    )
    assert payload["schema"] == STATUS_SCHEMA
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False
    assert payload["live_collection"] is False
    assert payload["progress_percent"] == 42
    reread = json.loads(path.read_text(encoding="utf-8"))
    assert reread["job_id"] == "job-1"
    assert reread["last_log_line"] == "progression 42%"
    assert not list(path.parent.glob("*.tmp"))


def test_run_logged_met_le_statut_a_jour_meme_si_le_processus_reste_silencieux(tmp_path: Path) -> None:
    status = tmp_path / "status" / "CURRENT_STATUS.json"
    result = worker._run_logged(
        "silent",
        [sys.executable, "-c", "import time; time.sleep(1.25)"],
        cwd=tmp_path,
        log_dir=tmp_path / "logs",
        timeout_seconds=5,
        live_status_path=status,
        live_context={
            "job_id": "job-silent",
            "suite": "economic-full",
            "mode": "economic",
            "job_started_unix": time.time(),
            "workspace": str(tmp_path),
        },
        action_fr="Test silencieux",
        next_action_fr="Fin",
        step_index=2,
        step_total=4,
    )
    assert result["return_code"] == 0
    payload = json.loads(status.read_text(encoding="utf-8"))
    assert payload["state"] == "STEP_DONE"
    assert payload["action_fr"] == "Test silencieux"
    assert payload["step_index"] == 2
    assert payload["step_total"] == 4
    assert payload["paper_only"] is True
