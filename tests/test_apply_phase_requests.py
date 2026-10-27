from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import apply_phase_requests, set_phase

ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "b" * 64


def _case(
    root: Path,
    phase: str,
    *,
    with_receipt: bool,
    schema: str = "alina.phase_request.v1",
) -> tuple[Path, Path, Path]:
    request_dir = root / "requests"
    receipt_dir = root / "receipts"
    request_dir.mkdir()
    receipt_dir.mkdir()
    request = {
        "schema": schema,
        "request_id": REQUEST_ID,
        "phase": phase,
        "requested_at_utc": "2026-10-04T12:20:37Z",
        "requested_by": "legacy-request",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    if schema == "alina.phase_request.v2":
        request["expected_phase"] = "COLLECT"
        request["expected_epoch"] = 8
    request_path = request_dir / f"{REQUEST_ID}.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    phase_path = root / "phase.json"
    phase_path.write_text(
        json.dumps(
            {
                "schema_version": "alina.phase.v2",
                "phase": "COLLECT",
                "epoch": 8,
                "requested_at_utc": "2026-10-06T13:29:59Z",
                "collection_started_at_utc": "2026-10-06T13:29:59Z",
                "collection_cutoff_at_utc": None,
                "source_collection_epoch": None,
                "analysis_stage": None,
                "requested_by": "current-cycle",
                "request_id": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    if with_receipt:
        receipt = {
            "schema": "alina.phase_transition_receipt.v1",
            "request_id": REQUEST_ID,
            "previous_phase": "COLLECT",
            "previous_epoch": 6,
            "new_phase": phase,
            "new_epoch": 7,
            "state_digest": "c" * 64,
            "transitioned_at_utc": "2026-10-04T12:21:46Z",
            "paper_only": True,
            "read_only": True,
            "real_execution": False,
        }
        (receipt_dir / f"{REQUEST_ID}.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
    return request_dir, receipt_dir, phase_path


def _run_applier(
    monkeypatch,
    *,
    request_dir: Path,
    receipt_dir: Path,
    phase_path: Path,
    run,
) -> None:
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(sys, "argv", [
        "apply_phase_requests.py",
        "--request-dir", str(request_dir),
        "--receipt-dir", str(receipt_dir),
        "--phase-path", str(phase_path),
    ])
    monkeypatch.setattr(apply_phase_requests.subprocess, "run", run)


def test_legacy_unreceipted_request_cannot_replay_against_a_new_collection_epoch(
    tmp_path: Path, monkeypatch
) -> None:
    request_dir, receipt_dir, phase_path = _case(
        tmp_path, "ANALYZE", with_receipt=False
    )
    original_phase = phase_path.read_bytes()
    command_calls: list[list[str]] = []

    def emulate_subprocess(command: list[str], *, check: bool = False):
        command_calls.append(command)
        if command[1].endswith("set_phase.py"):
            original_argv = sys.argv
            sys.argv = [command[1], *command[2:]]
            try:
                set_phase.main()
            finally:
                sys.argv = original_argv
        return subprocess.CompletedProcess(command, 0)

    _run_applier(
        monkeypatch,
        request_dir=request_dir,
        receipt_dir=receipt_dir,
        phase_path=phase_path,
        run=emulate_subprocess,
    )
    with pytest.raises(SystemExit, match="historical|receipt"):
        apply_phase_requests.main()

    assert command_calls == []
    assert phase_path.read_bytes() == original_phase


def test_malformed_receipt_does_not_mark_legacy_request_applied(
    tmp_path: Path, monkeypatch
) -> None:
    request_dir, receipt_dir, phase_path = _case(
        tmp_path, "IDLE", with_receipt=True
    )
    (receipt_dir / f"{REQUEST_ID}.json").write_text("{}", encoding="utf-8")

    def unexpected_call(*_args, **_kwargs):
        pytest.fail("malformed phase receipt must be rejected before subprocess")

    _run_applier(
        monkeypatch,
        request_dir=request_dir,
        receipt_dir=receipt_dir,
        phase_path=phase_path,
        run=unexpected_call,
    )
    with pytest.raises(SystemExit, match="receipt"):
        apply_phase_requests.main()


def test_historical_analyze_receipt_does_not_seal_a_later_collection_cycle(
    tmp_path: Path, monkeypatch
) -> None:
    request_dir, receipt_dir, phase_path = _case(
        tmp_path, "ANALYZE", with_receipt=True
    )
    command_calls: list[list[str]] = []

    def record_only(command: list[str], *, check: bool = False):
        command_calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    _run_applier(
        monkeypatch,
        request_dir=request_dir,
        receipt_dir=receipt_dir,
        phase_path=phase_path,
        run=record_only,
    )
    result = apply_phase_requests.main()

    assert result == 0
    assert command_calls == []


def test_v2_phase_request_applies_only_at_its_expected_phase_epoch(
    tmp_path: Path, monkeypatch
) -> None:
    request_dir, receipt_dir, phase_path = _case(
        tmp_path, "ANALYZE", with_receipt=False, schema="alina.phase_request.v2"
    )
    command_calls: list[list[str]] = []

    def emulate_subprocess(command: list[str], *, check: bool = False):
        command_calls.append(command)
        if command[1].endswith("set_phase.py"):
            original_argv = sys.argv
            sys.argv = [command[1], *command[2:]]
            try:
                set_phase.main()
            finally:
                sys.argv = original_argv
        return subprocess.CompletedProcess(command, 0)

    _run_applier(
        monkeypatch,
        request_dir=request_dir,
        receipt_dir=receipt_dir,
        phase_path=phase_path,
        run=emulate_subprocess,
    )
    result = apply_phase_requests.main()

    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    receipt = json.loads((receipt_dir / f"{REQUEST_ID}.json").read_text(encoding="utf-8"))
    assert result == 0
    assert phase["phase"] == "ANALYZE"
    assert phase["epoch"] == 9
    assert receipt["previous_phase"] == "COLLECT"
    assert receipt["previous_epoch"] == 8
    assert receipt["new_epoch"] == 9
    assert len(command_calls) == 2
