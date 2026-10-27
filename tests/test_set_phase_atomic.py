from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tools import set_phase


def test_atomic_phase_write_preserves_old_file_and_cleans_temp_on_replace_failure(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "phase.json"
    target.write_text('{"phase":"COLLECT"}\n', encoding="utf-8")

    def fail_replace(_source: str, _destination: Path) -> None:
        raise PermissionError("simulated replace failure")

    monkeypatch.setattr(set_phase.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="simulated replace failure"):
        set_phase.atomic_write(target, '{"phase":"IDLE"}\n')

    assert target.read_text(encoding="utf-8") == '{"phase":"COLLECT"}\n'
    assert list(tmp_path.iterdir()) == [target]


def test_competing_phase_requests_cannot_both_commit_same_epoch(tmp_path, monkeypatch):
    phase_path = tmp_path / "phase.json"
    receipt_dir = tmp_path / "receipts"
    first_request = "1" * 64
    second_request = "2" * 64
    phase_path.write_text(
        json.dumps(
            {
                "phase": "IDLE",
                "epoch": 1,
                "requested_at_utc": "2026-10-27T00:00:00Z",
                "collection_started_at_utc": None,
                "collection_cutoff_at_utc": None,
                "source_collection_epoch": None,
                "analysis_stage": None,
                "requested_by": "fixture",
                "request_id": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    first_write_entered = threading.Event()
    second_write_entered = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    write_count = 0
    write_guard = threading.Lock()
    real_atomic_write = set_phase.atomic_write

    def controlled_atomic_write(path: Path, payload: str) -> None:
        nonlocal write_count
        if path == phase_path:
            with write_guard:
                write_count += 1
                current_write = write_count
            if current_write == 1:
                first_write_entered.set()
                if not release_first.wait(timeout=5):
                    raise TimeoutError("test did not release the first phase writer")
            else:
                second_write_entered.set()
        real_atomic_write(path, payload)

    monkeypatch.setattr(set_phase, "atomic_write", controlled_atomic_write)

    def invoke(request_id: str, *, mark_started: bool = False):
        if mark_started:
            second_started.set()
        argv = [
            "--phase",
            "COLLECT",
            "--request-id",
            request_id,
            "--expected-phase",
            "IDLE",
            "--expected-epoch",
            "1",
            "--path",
            str(phase_path),
            "--receipt-dir",
            str(receipt_dir),
        ]
        try:
            return "ok", set_phase.main(argv)
        except SystemExit as exc:
            return "rejected", str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, first_request)
        assert first_write_entered.wait(timeout=2)
        second = pool.submit(invoke, second_request, mark_started=True)
        assert second_started.wait(timeout=2)
        competing_write_reached = second_write_entered.wait(timeout=0.25)
        release_first.set()
        first_result = first.result(timeout=3)
        second_result = second.result(timeout=3)

    assert not competing_write_reached
    assert first_result == ("ok", 0)
    assert second_result[0] == "rejected"
    assert "phase state changed from expected phase/epoch" in second_result[1]
    final_state = json.loads(phase_path.read_text(encoding="utf-8"))
    assert final_state["request_id"] == first_request
    assert final_state["epoch"] == 2
