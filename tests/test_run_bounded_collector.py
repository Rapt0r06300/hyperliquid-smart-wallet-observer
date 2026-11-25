from __future__ import annotations

import os
from pathlib import Path

from tools.run_bounded_collector import _data_heartbeat_summary, _next_restart_backoff


def test_restart_backoff_is_zero_after_success() -> None:
    assert _next_restart_backoff(16.0, 0) == 0.0


def test_restart_backoff_grows_after_failure_and_is_capped() -> None:
    assert _next_restart_backoff(0.0, 1) == 1.0
    assert _next_restart_backoff(1.0, 1) == 2.0
    assert _next_restart_backoff(60.0, 1) == 60.0


def test_restart_backoff_never_uses_negative_limits() -> None:
    assert _next_restart_backoff(0.0, 1, initial_s=-2.0, maximum_s=0.0) == 0.0


def test_wrapper_summary_reports_data_heartbeat_without_touching_worker(tmp_path: Path) -> None:
    now_s = 1_800_000_000.0
    heartbeat = tmp_path / "runtime/data/bbo_heartbeat.json"
    heartbeat.parent.mkdir(parents=True)
    heartbeat.write_text("not parsed by the wrapper", encoding="utf-8")
    os.utime(heartbeat, (now_s - 600, now_s - 600))

    stale = _data_heartbeat_summary(tmp_path, "bbo-collector", now_s=now_s)
    assert "data_heartbeat=STALE" in stale
    assert "age_s=600.0" in stale
    assert "threshold_s=120.0" in stale

    os.utime(heartbeat, (now_s - 5, now_s - 5))
    fresh = _data_heartbeat_summary(tmp_path, "bbo-collector", now_s=now_s)
    assert "data_heartbeat=FRESH" in fresh


def test_wrapper_marks_unconfigured_heartbeat_without_guessing() -> None:
    assert _data_heartbeat_summary(Path("."), "unknown-collector") == (
        "data_heartbeat=NOT_MONITORED"
    )
