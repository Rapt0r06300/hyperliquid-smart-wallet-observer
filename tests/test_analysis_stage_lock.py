from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools import advance_analysis_stage, set_phase


def test_phase_transition_cannot_be_overwritten_by_concurrent_stage_advance(
    tmp_path: Path, monkeypatch
) -> None:
    phase_path = tmp_path / "phase.json"
    receipt_dir = tmp_path / "receipts"
    campaign_root = tmp_path / "campaigns"
    campaign_root.mkdir()
    gate_registry = tmp_path / "gates.json"
    gate_registry.write_text(
        json.dumps(
            {
                "paper_only": True,
                "read_only": True,
                "real_execution": False,
                "stages": {"QUALITY": {}},
            }
        ),
        encoding="utf-8",
    )
    phase_path.write_text(
        json.dumps(
            {
                "phase": "ANALYZE",
                "epoch": 2,
                "analysis_stage": "DRAIN",
                "source_collection_epoch": 1,
                "collection_cutoff_at_utc": "2026-10-27T00:00:00Z",
                "requested_at_utc": "2026-10-27T00:00:00Z",
                "requested_by": "fixture",
                "request_id": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    advance_entered_replace = threading.Event()
    phase_request_started = threading.Event()
    phase_request_entered_replace = threading.Event()
    release_advance = threading.Event()
    replace_count = 0
    replace_guard = threading.Lock()
    real_replace = advance_analysis_stage.os.replace

    def controlled_replace(source, destination):
        nonlocal replace_count
        if Path(destination) == phase_path:
            with replace_guard:
                replace_count += 1
                current_replace = replace_count
            if current_replace == 1:
                advance_entered_replace.set()
                if not release_advance.wait(timeout=5):
                    raise TimeoutError("test did not release the analysis-stage writer")
            elif current_replace == 2:
                phase_request_entered_replace.set()
        return real_replace(source, destination)

    monkeypatch.setattr(advance_analysis_stage.os, "replace", controlled_replace)

    def advance_stage():
        return advance_analysis_stage.main(
            [
                "--stage",
                "QUALITY",
                "--request-id",
                "1" * 64,
                "--expected-epoch",
                "2",
                "--path",
                str(phase_path),
                "--campaign-root",
                str(campaign_root),
                "--receipt-dir",
                str(receipt_dir),
                "--gate-registry",
                str(gate_registry),
            ]
        )

    def pause_collection():
        phase_request_started.set()
        return set_phase.main(
            [
                "--phase",
                "IDLE",
                "--request-id",
                "2" * 64,
                "--expected-phase",
                "ANALYZE",
                "--expected-epoch",
                "2",
                "--path",
                str(phase_path),
                "--receipt-dir",
                str(receipt_dir),
            ]
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        advancing = pool.submit(advance_stage)
        assert advance_entered_replace.wait(timeout=2)
        pausing = pool.submit(pause_collection)
        assert phase_request_started.wait(timeout=2)
        competing_write_reached = phase_request_entered_replace.wait(timeout=0.25)
        release_advance.set()
        advancing.result(timeout=3)
        assert pausing.result(timeout=3) == 0

    assert not competing_write_reached
    final_state = json.loads(phase_path.read_text(encoding="utf-8"))
    assert final_state["phase"] == "IDLE"
    assert final_state["epoch"] == 3
    assert final_state["analysis_stage"] is None
    assert final_state["request_id"] == "2" * 64
