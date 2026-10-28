from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools import apply_operator_controls

ROOT = Path(__file__).resolve().parents[1]


def _write_retry_request(root: Path) -> tuple[str, Path, Path]:
    tools_dir = root / "tools"
    tools_dir.mkdir()
    shutil.copyfile(ROOT / "tools" / "resumable_campaign.py", tools_dir / "resumable_campaign.py")
    request_id = "e" * 64
    intent = {
        "schema_version": "alina.operator_intent.v2",
        "intent": "retry",
        "request_id": request_id,
        "requested_by": "test",
        "requested_at_utc": "2026-10-26T12:00:00Z",
        "main_code_sha": "a" * 40,
        "phase": "ANALYZE",
        "phase_epoch": 4,
        "analysis_stage": "REPLAY",
        "source_collection_epoch": 3,
        "collection_cutoff_at_utc": "2026-10-26T00:00:00Z",
        "config": {"campaign_id": "retry-target", "strategy_family": "all"},
        "strategy_family": "all",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    digest = hashlib.sha256(
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    status = {
        "schema_version": "alina.operator_status.v2",
        "request_id": request_id,
        "intent": "retry",
        "intent_digest": digest,
        "state": "DISPATCHED",
        "terminal": False,
        "workflow_run_id": "test-run",
        "main_code_sha": "a" * 40,
        "phase": "ANALYZE",
        "phase_epoch": 4,
        "analysis_stage": "REPLAY",
        "source_collection_epoch": 3,
        "collection_cutoff_at_utc": "2026-10-26T00:00:00Z",
        "strategy_family": "all",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    intent_path = root / "control" / "operator-intents" / f"{request_id}.json"
    status_path = root / "control" / "operator-status" / f"{request_id}.json"
    intent_path.parent.mkdir(parents=True)
    status_path.parent.mkdir(parents=True)
    intent_path.write_text(json.dumps(intent, sort_keys=True), encoding="utf-8")
    status_path.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    campaign = {
        "campaign_id": "retry-target",
        "kind": "replay",
        "code_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "code_sha": "b" * 40,
        "dataset_repo": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "dataset_generation": "V2_FRESH",
        "config_sha256": "c" * 64,
        "work_plan_sha256": "d" * 64,
        "expires_at": "2026-12-31T00:00:00Z",
        "schema_version": "alina.resumable_campaign.v2",
        "status": "STUCK",
        "status_reason": "bounded_retry_exhausted",
        "created_at": "2026-10-26T10:00:00Z",
        "updated_at": "2026-10-26T11:00:00Z",
        "creation_phase": "ANALYZE",
        "phase_epoch": 4,
        "source_collection_epoch": 3,
        "collection_cutoff_at_utc": "2026-10-26T00:00:00Z",
        "dataset_selection_id": "f" * 64,
        "analysis_stage": "REPLAY",
        "cursor": {"strategy_family": "copy_vault"},
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    campaign_path = root / "catalog" / "campaigns" / "retry-target.json"
    campaign_path.parent.mkdir(parents=True)
    campaign_path.write_text(json.dumps(campaign, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    phase_path = root / "control" / "alina-phase.json"
    phase_path.write_text(
        json.dumps(
            {
                "schema_version": "alina.phase.v2",
                "phase": "ANALYZE",
                "epoch": 4,
                "request_id": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    return request_id, status_path, campaign_path


def _poll(root: Path, monkeypatch) -> None:
    monkeypatch.chdir(root)
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join((str(ROOT / "src"), str(ROOT), os.environ.get("PYTHONPATH", ""))),
    )
    venv_scripts = ROOT / ".venv" / "Scripts"
    monkeypatch.setenv("PATH", str(venv_scripts) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "apply_operator_controls.py",
            "--alina-root",
            str(root),
            "--phase-path",
            str(root / "control" / "alina-phase.json"),
        ],
    )
    apply_operator_controls.main()


def _write_phase_request(
    root: Path,
    action: str,
    current_phase: str,
    *,
    config: dict | None = None,
) -> tuple[str, Path, Path]:
    request_id = "f" * 64
    intent = {
        "schema_version": "alina.operator_intent.v2",
        "intent": action,
        "request_id": request_id,
        "requested_by": "test",
        "requested_at_utc": "2026-10-26T12:00:00Z",
        "main_code_sha": "a" * 40,
        "phase": current_phase,
        "phase_epoch": 4,
        "analysis_stage": None,
        "source_collection_epoch": None,
        "collection_cutoff_at_utc": None,
        "config": config or {},
        "strategy_family": "all",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    digest = hashlib.sha256(
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    status = {
        "schema_version": "alina.operator_status.v2",
        "request_id": request_id,
        "intent": action,
        "intent_digest": digest,
        "state": "DISPATCHED",
        "terminal": False,
        "phase": current_phase,
        "phase_epoch": 4,
        "analysis_stage": None,
        "source_collection_epoch": None,
        "collection_cutoff_at_utc": None,
        "strategy_family": "all",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    intent_path = root / "control" / "operator-intents" / f"{request_id}.json"
    status_path = root / "control" / "operator-status" / f"{request_id}.json"
    intent_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    intent_path.write_text(json.dumps(intent, sort_keys=True), encoding="utf-8")
    status_path.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    phase_path = root / "control" / "alina-phase.json"
    current_state = {
        "schema_version": "alina.phase.v2",
        "phase": current_phase,
        "epoch": 4,
        "requested_at_utc": "2026-10-26T11:00:00Z",
        "collection_started_at_utc": (
            "2026-10-26T10:00:00Z" if current_phase == "COLLECT" else None
        ),
        "collection_cutoff_at_utc": None,
        "source_collection_epoch": None,
        "analysis_stage": None,
        "requested_by": "fixture",
        "request_id": "0" * 64,
    }
    phase_path.write_text(json.dumps(current_state), encoding="utf-8")
    return request_id, status_path, phase_path


def test_retry_control_acknowledgement_survives_repeated_polling(tmp_path: Path, monkeypatch) -> None:
    request_id, status_path, campaign_path = _write_retry_request(tmp_path)

    _poll(tmp_path, monkeypatch)
    after_first = json.loads(campaign_path.read_text(encoding="utf-8"))
    _poll(tmp_path, monkeypatch)
    after_second = json.loads(campaign_path.read_text(encoding="utf-8"))

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert after_first["status"] == "RUNNING"
    assert after_second["history"] == after_first["history"]
    assert len(after_second["history"]) == 1
    assert after_second["history"][0]["reason"] == request_id
    assert status["state"] == "COMPLETE"
    assert status["terminal"] is True
    assert status["control_receipt"]["request_id"] == request_id
    validated = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_operator_status.py"),
            "--intent",
            str(tmp_path / "control" / "operator-intents" / f"{request_id}.json"),
            "--status",
            str(status_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validated.returncode == 0, validated.stderr


def test_retry_recovers_after_manifest_transition_before_status_ack(
    tmp_path: Path, monkeypatch
) -> None:
    request_id, status_path, campaign_path = _write_retry_request(tmp_path)
    original_status = status_path.read_bytes()

    _poll(tmp_path, monkeypatch)
    once = json.loads(campaign_path.read_text(encoding="utf-8"))
    status_path.write_bytes(original_status)
    _poll(tmp_path, monkeypatch)

    twice = json.loads(campaign_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert twice["history"] == once["history"]
    assert twice["history"][0]["reason"] == request_id
    assert status["state"] == "COMPLETE"
    assert status["control_receipt"]["evidence_digest"]


def test_pause_control_is_acknowledged_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    request_id, status_path, phase_path = _write_phase_request(tmp_path, "pause", "COLLECT")

    _poll(tmp_path, monkeypatch)
    first = json.loads(phase_path.read_text(encoding="utf-8"))
    first_receipt = (tmp_path / "control" / "phase-receipts" / f"{request_id}.json").read_bytes()
    _poll(tmp_path, monkeypatch)

    second = json.loads(phase_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert first["phase"] == second["phase"] == "IDLE"
    assert first["request_id"] == second["request_id"] == request_id
    assert second["epoch"] == 5
    assert (tmp_path / "control" / "phase-receipts" / f"{request_id}.json").read_bytes() == first_receipt
    assert status["state"] == "COMPLETE"
    assert status["control_receipt"]["target_identity"] == "IDLE"
    assert status["control_receipt"]["campaign_lease_effect"] == "PRESERVE_ACTIVE_LEASES"

    validation = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_operator_status.py"),
            "--intent",
            str(tmp_path / "control" / "operator-intents" / f"{request_id}.json"),
            "--status",
            str(status_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validation.returncode == 0, validation.stderr


def test_resume_control_from_idle_is_acknowledged_once(tmp_path: Path, monkeypatch) -> None:
    request_id, status_path, phase_path = _write_phase_request(tmp_path, "resume", "IDLE")

    _poll(tmp_path, monkeypatch)
    first = json.loads(phase_path.read_text(encoding="utf-8"))
    receipt_bytes = (tmp_path / "control" / "phase-receipts" / f"{request_id}.json").read_bytes()
    _poll(tmp_path, monkeypatch)

    second = json.loads(phase_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert first["phase"] == second["phase"] == "COLLECT"
    assert first["request_id"] == second["request_id"] == request_id
    assert second["epoch"] == 5
    assert (tmp_path / "control" / "phase-receipts" / f"{request_id}.json").read_bytes() == receipt_bytes
    assert status["state"] == "COMPLETE"
    assert status["control_receipt"]["target_identity"] == "COLLECT"
    assert status["control_receipt"]["campaign_lease_effect"] == "PRESERVE_ACTIVE_LEASES"


@pytest.mark.parametrize(
    ("source_phase", "target_phase"),
    (("COLLECT", "COLLECT"), ("IDLE", "IDLE"), ("IDLE", "ANALYZE")),
)
def test_resume_rejects_noncanonical_phase_transition_before_mutation(
    tmp_path: Path,
    monkeypatch,
    source_phase: str,
    target_phase: str,
) -> None:
    _, status_path, phase_path = _write_phase_request(
        tmp_path,
        "resume",
        source_phase,
        config={"phase": target_phase},
    )
    before = phase_path.read_bytes()

    with pytest.raises(SystemExit, match="resume requires IDLE to COLLECT"):
        _poll(tmp_path, monkeypatch)

    assert phase_path.read_bytes() == before
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "DISPATCHED"


@pytest.mark.parametrize("action", ("pause", "resume"))
def test_phase_control_preserves_active_campaign_lease_bytes(
    tmp_path: Path, monkeypatch, action: str
) -> None:
    source_phase = "COLLECT" if action == "pause" else "IDLE"
    _, _, phase_path = _write_phase_request(tmp_path, action, source_phase)
    manifest_path = tmp_path / "catalog" / "campaigns" / "active.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "campaign_id": "active",
                "status": "RUNNING",
                "creation_phase": "COLLECT",
                "phase_epoch": 4,
                "lease": {
                    "owner": "github-run-1",
                    "lease_token_sha256": "a" * 64,
                    "expires_at": "2026-10-26T13:00:00Z",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    before = manifest_path.read_bytes()

    _poll(tmp_path, monkeypatch)

    assert manifest_path.read_bytes() == before


def test_completed_pause_requires_preserve_lease_effect_in_all_receipt_gates(
    tmp_path: Path, monkeypatch
) -> None:
    request_id, status_path, _ = _write_phase_request(tmp_path, "pause", "COLLECT")
    _poll(tmp_path, monkeypatch)
    intent_path = tmp_path / "control" / "operator-intents" / f"{request_id}.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))

    from tools.build_closure_report import _valid_completed_control_receipt

    assert _valid_completed_control_receipt(status, intent_path) is True

    status["control_receipt"].pop("campaign_lease_effect")
    status["control_receipt_sha256"] = hashlib.sha256(
        json.dumps(status["control_receipt"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    status_path.write_text(json.dumps(status), encoding="utf-8")

    validation = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_operator_status.py"),
            "--intent",
            str(intent_path),
            "--status",
            str(status_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validation.returncode != 0
    assert "OPERATOR_CONTROL_RECEIPT_INVALID" in validation.stderr
    with pytest.raises(SystemExit, match="durable receipt"):
        apply_operator_controls._load_status(
            json.loads(intent_path.read_text(encoding="utf-8"))
        )
    assert _valid_completed_control_receipt(status, intent_path) is False


def test_newer_control_terminalizes_older_pending_without_replaying_it(
    tmp_path: Path, monkeypatch
) -> None:
    older_request_id, older_status_path, phase_path = _write_phase_request(
        tmp_path, "pause", "COLLECT"
    )
    older_intent_path = (
        tmp_path / "control" / "operator-intents" / f"{older_request_id}.json"
    )
    older_intent = json.loads(older_intent_path.read_text(encoding="utf-8"))
    older_intent["requested_at_utc"] = "2026-10-26T11:00:00Z"
    older_digest = hashlib.sha256(
        json.dumps(older_intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    older_intent_path.write_text(json.dumps(older_intent), encoding="utf-8")
    older_status = json.loads(older_status_path.read_text(encoding="utf-8"))
    older_status.update(intent_digest=older_digest, updated_at_utc=older_intent["requested_at_utc"])
    older_status_path.write_text(json.dumps(older_status), encoding="utf-8")

    newer_request_id = "e" * 64
    newer_intent = {
        **older_intent,
        "request_id": newer_request_id,
        "requested_at_utc": "2026-10-26T13:00:00Z",
    }
    newer_digest = hashlib.sha256(
        json.dumps(newer_intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    newer_intent_path = (
        tmp_path / "control" / "operator-intents" / f"{newer_request_id}.json"
    )
    newer_status_path = (
        tmp_path / "control" / "operator-status" / f"{newer_request_id}.json"
    )
    newer_intent_path.write_text(json.dumps(newer_intent), encoding="utf-8")
    newer_status = {
        **older_status,
        "request_id": newer_request_id,
        "intent_digest": newer_digest,
        "updated_at_utc": newer_intent["requested_at_utc"],
    }
    newer_status_path.write_text(json.dumps(newer_status), encoding="utf-8")

    _poll(tmp_path, monkeypatch)

    older_after = json.loads(older_status_path.read_text(encoding="utf-8"))
    newer_after = json.loads(newer_status_path.read_text(encoding="utf-8"))
    phase_after = json.loads(phase_path.read_text(encoding="utf-8"))
    assert older_after["state"] == "BLOCKED"
    assert older_after["terminal"] is True
    assert older_after["status_reason"] == "SUPERSEDED_BY_NEWER_CONTROL_INTENT"
    assert older_after["superseded_by_request_id"] == newer_request_id
    assert newer_after["state"] == "COMPLETE"
    assert phase_after["phase"] == "IDLE"
    assert phase_after["request_id"] == newer_request_id
    assert not (tmp_path / "control" / "phase-receipts" / f"{older_request_id}.json").exists()
    validation = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_operator_status.py"),
            "--intent",
            str(older_intent_path),
            "--status",
            str(older_status_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validation.returncode == 0, validation.stderr


def test_phase_control_recovers_committed_state_when_receipt_was_not_written(
    tmp_path: Path, monkeypatch
) -> None:
    request_id, status_path, phase_path = _write_phase_request(
        tmp_path, "pause", "COLLECT"
    )
    committed_state = {
        "schema_version": "alina.phase.v2",
        "phase": "IDLE",
        "epoch": 5,
        "requested_at_utc": "2026-10-26T12:00:01Z",
        "collection_started_at_utc": None,
        "collection_cutoff_at_utc": None,
        "source_collection_epoch": None,
        "analysis_stage": None,
        "requested_by": "test",
        "request_id": request_id,
    }
    phase_path.write_text(json.dumps(committed_state), encoding="utf-8")

    _poll(tmp_path, monkeypatch)

    receipt_path = tmp_path / "control" / "phase-receipts" / f"{request_id}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert receipt["previous_phase"] == "COLLECT"
    assert receipt["previous_epoch"] == 4
    assert receipt["new_phase"] == "IDLE"
    assert receipt["new_epoch"] == 5
    assert receipt["state_digest"] == hashlib.sha256(
        json.dumps(committed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert status["state"] == "COMPLETE"


def test_phase_control_does_not_overwrite_a_concurrent_epoch_change(
    tmp_path: Path, monkeypatch
) -> None:
    import pytest

    request_id, status_path, phase_path = _write_phase_request(
        tmp_path, "pause", "COLLECT"
    )
    concurrent_state = {
        "schema_version": "alina.phase.v2",
        "phase": "COLLECT",
        "epoch": 5,
        "request_id": "a" * 64,
    }
    original_run = apply_operator_controls._run

    def race_before_phase_write(command: list[str], *, env: dict[str, str]):
        phase_path.write_text(json.dumps(concurrent_state), encoding="utf-8")
        return original_run(command, env=env)

    monkeypatch.setattr(apply_operator_controls, "_run", race_before_phase_write)
    with pytest.raises(SystemExit, match="phase control failed|epoch"):
        _poll(tmp_path, monkeypatch)

    assert json.loads(phase_path.read_text(encoding="utf-8")) == concurrent_state
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "DISPATCHED"


def test_completed_control_status_requires_a_valid_receipt(tmp_path: Path) -> None:
    request_id, status_path, _ = _write_retry_request(tmp_path)
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["state"] = "COMPLETE"
    status["terminal"] = True
    status_path.write_text(json.dumps(status), encoding="utf-8")
    intent_path = tmp_path / "control" / "operator-intents" / f"{request_id}.json"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_operator_status.py"),
            "--intent",
            str(intent_path),
            "--status",
            str(status_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "OPERATOR_CONTROL_RECEIPT_INVALID" in result.stderr


def test_superseded_control_status_requires_a_distinct_replacement_request(
    tmp_path: Path,
) -> None:
    request_id, status_path, _ = _write_retry_request(tmp_path)
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update(
        state="BLOCKED",
        terminal=True,
        status_reason="SUPERSEDED_BY_NEWER_CONTROL_INTENT",
    )
    status_path.write_text(json.dumps(status), encoding="utf-8")
    intent_path = tmp_path / "control" / "operator-intents" / f"{request_id}.json"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_operator_status.py"),
            "--intent",
            str(intent_path),
            "--status",
            str(status_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "OPERATOR_STATUS_SUPERSESSION_INVALID" in result.stderr


def test_superseded_control_status_requires_an_existing_newer_intent(
    tmp_path: Path,
) -> None:
    request_id, status_path, _ = _write_retry_request(tmp_path)
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update(
        state="BLOCKED",
        terminal=True,
        status_reason="SUPERSEDED_BY_NEWER_CONTROL_INTENT",
        superseded_by_request_id="d" * 64,
    )
    status_path.write_text(json.dumps(status), encoding="utf-8")
    intent_path = tmp_path / "control" / "operator-intents" / f"{request_id}.json"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_operator_status.py"),
            "--intent",
            str(intent_path),
            "--status",
            str(status_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "OPERATOR_STATUS_SUPERSESSION_INVALID" in result.stderr


def test_closure_report_checks_completed_control_receipt(tmp_path: Path) -> None:
    from tools.build_closure_report import _valid_completed_control_receipt

    request_id, status_path, _ = _write_retry_request(tmp_path)
    intent_path = tmp_path / "control" / "operator-intents" / f"{request_id}.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    receipt = {
        "schema_version": "alina.operator_control_receipt.v1",
        "request_id": request_id,
        "intent": "retry",
        "intent_digest": status["intent_digest"],
        "target_identity": "retry-target",
        "evidence_digest": "1" * 64,
        "applied": True,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    status.update(
        {
            "state": "COMPLETE",
            "terminal": True,
            "control_receipt": receipt,
            "control_receipt_sha256": hashlib.sha256(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    )

    assert _valid_completed_control_receipt(status, intent_path) is True
    status["control_receipt"]["evidence_digest"] = "2" * 64
    assert _valid_completed_control_receipt(status, intent_path) is False


def test_retry_refuses_manifest_identity_mismatch_without_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    _, status_path, campaign_path = _write_retry_request(tmp_path)
    manifest = json.loads(campaign_path.read_text(encoding="utf-8"))
    manifest["campaign_id"] = "some-other-campaign"
    campaign_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    before = campaign_path.read_bytes()

    try:
        _poll(tmp_path, monkeypatch)
    except SystemExit as exc:
        assert "not a V2 ANALYZE campaign" in str(exc)
    else:
        raise AssertionError("campaign identity mismatch was accepted")

    assert campaign_path.read_bytes() == before
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "DISPATCHED"


def test_operator_dispatch_routes_controls_through_creator_once() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "alina-operator-dispatch.yml"
    ).read_text(encoding="utf-8")
    assert 'control_intents={"pause","resume","retry"}' in workflow
    assert 'phase not in {"IDLE","COLLECT","ANALYZE"}' in workflow
    assert "retry requires the ANALYZE phase" in workflow
    assert "gh workflow run create-resumable-campaigns.yml" in workflow
    assert "gh workflow run resumable-campaign-controller.yml" not in workflow
    creator = (
        ROOT / ".github" / "workflows" / "create-resumable-campaigns.yml"
    ).read_text(encoding="utf-8")
    assert "if: ${{ needs.create.outputs.phase != 'IDLE' }}" in creator


def test_replaying_persisted_operator_request_preserves_terminal_status(tmp_path: Path) -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "alina-operator-intent.yml").read_text(
            encoding="utf-8"
        )
    )
    step = next(
        step
        for step in workflow["jobs"]["persist"]["steps"]
        if step.get("name") == "Persist immutable operator intent"
    )
    match = re.search(r"python\s+-\s+<<['\"]PY['\"]\s*\n(.*?)\n\s*PY\s*$", step["run"], re.S)
    assert match is not None
    persist_script = match.group(1)

    tools_dir = tmp_path / "tools"
    scope_dir = tmp_path / "src" / "hl_observer" / "strategies"
    tools_dir.mkdir()
    scope_dir.mkdir(parents=True)
    shutil.copyfile(ROOT / "tools" / "operator_family_contract.py", tools_dir / "operator_family_contract.py")
    shutil.copyfile(ROOT / "src" / "hl_observer" / "strategies" / "active_scope.py", scope_dir / "active_scope.py")
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    (runner_temp / "alina-phase.json").write_text(
        json.dumps(
            {
                "phase": "COLLECT",
                "epoch": 4,
                "analysis_stage": None,
                "source_collection_epoch": None,
                "collection_cutoff_at_utc": None,
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "INTENT": "pause",
        "REQUEST_ID": "a" * 64,
        "FAMILY": "all",
        "REQUESTED_BY": "test",
        "CONFIG_JSON": "{}",
        "GITHUB_SHA": "b" * 40,
        "GITHUB_RUN_ID": "100",
        "RUNNER_TEMP": str(runner_temp),
    }

    def persist(run_id: str, *, main_code_sha: str = "b" * 40) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", persist_script],
            cwd=tmp_path,
            env={**env, "GITHUB_RUN_ID": run_id, "GITHUB_SHA": main_code_sha},
            capture_output=True,
            text=True,
            check=False,
        )

    first = persist("100")
    assert first.returncode == 0, first.stderr
    intent_path = tmp_path / "control" / "operator-intents" / f"{'a' * 64}.json"
    status_path = tmp_path / "control" / "operator-status" / f"{'a' * 64}.json"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    receipt = {
        "schema_version": "alina.operator_control_receipt.v1",
        "request_id": intent["request_id"],
        "intent": intent["intent"],
        "intent_digest": status["intent_digest"],
        "target_identity": "IDLE",
        "evidence_digest": "c" * 64,
        "applied": True,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "campaign_lease_effect": "PRESERVE_ACTIVE_LEASES",
    }
    status.update(
        {
            "state": "COMPLETE",
            "terminal": True,
            "control_receipt": receipt,
            "control_receipt_sha256": hashlib.sha256(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    )
    status_path.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    completed_bytes = status_path.read_bytes()

    second = persist("101")

    assert second.returncode == 0, second.stderr
    assert status_path.read_bytes() == completed_bytes

    conflicting_sha = persist("102", main_code_sha="c" * 40)
    assert conflicting_sha.returncode != 0
    assert "request id already exists with different payload" in conflicting_sha.stderr
    assert status_path.read_bytes() == completed_bytes


def test_python_heredocs_in_modified_workflows_compile() -> None:
    workflow_paths = [
        ROOT / ".github" / "workflows" / "alina-operator-dispatch.yml",
        ROOT / ".github" / "workflows" / "alina-operator-intent.yml",
        ROOT / ".github" / "workflows" / "create-resumable-campaigns.yml",
    ]
    for workflow_path in workflow_paths:
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        compiled_blocks = 0
        for job_name, job in (workflow.get("jobs") or {}).items():
            for index, step in enumerate(job.get("steps") or []):
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                blocks = re.finditer(
                    r"python(?:3)?\s+[^\n]*<<['\"]PY['\"][^\n]*\n(.*?)\n\s*PY\s*(?:\n|$)",
                    run,
                    re.S,
                )
                for block in blocks:
                    compile(block.group(1), f"{workflow_path}:{job_name}:{index}", "exec")
                    compiled_blocks += 1
        assert compiled_blocks > 0, f"no Python heredocs checked in {workflow_path}"


def test_retry_refuses_offscope_manifest_without_mutation(tmp_path: Path, monkeypatch) -> None:
    _, status_path, campaign_path = _write_retry_request(tmp_path)
    manifest = json.loads(campaign_path.read_text(encoding="utf-8"))
    manifest["cursor"]["strategy_family"] = "lead_lag"
    campaign_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    before = campaign_path.read_bytes()

    try:
        _poll(tmp_path, monkeypatch)
    except ValueError as exc:
        assert "DISABLED_BY_SCOPE" in str(exc)
    else:
        raise AssertionError("off-scope campaign was accepted")

    assert campaign_path.read_bytes() == before
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "DISPATCHED"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("kind", "collection", "unknown campaign kind"),
        ("status", "RUNNING", "not STUCK and has no matching retry receipt"),
    ],
)
def test_retry_refuses_wrong_kind_or_non_stuck_manifest_before_mutation(
    tmp_path: Path, monkeypatch, field: str, value: str, reason: str
) -> None:
    _, status_path, campaign_path = _write_retry_request(tmp_path)
    manifest = json.loads(campaign_path.read_text(encoding="utf-8"))
    manifest[field] = value
    campaign_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    before = campaign_path.read_bytes()

    with pytest.raises(SystemExit, match=reason):
        _poll(tmp_path, monkeypatch)

    assert campaign_path.read_bytes() == before
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "DISPATCHED"


def test_retry_refuses_missing_campaign_id_without_mutating_any_target(
    tmp_path: Path, monkeypatch
) -> None:
    request_id, status_path, campaign_path = _write_retry_request(tmp_path)
    intent_path = tmp_path / "control" / "operator-intents" / f"{request_id}.json"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["config"].pop("campaign_id")
    digest = hashlib.sha256(
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    intent_path.write_text(json.dumps(intent, sort_keys=True), encoding="utf-8")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["intent_digest"] = digest
    status_path.write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    before = campaign_path.read_bytes()

    with pytest.raises(SystemExit, match="path-safe campaign_id"):
        _poll(tmp_path, monkeypatch)

    assert campaign_path.read_bytes() == before
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "DISPATCHED"


def test_retry_refuses_stale_campaign_epoch_without_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    _, status_path, campaign_path = _write_retry_request(tmp_path)
    manifest = json.loads(campaign_path.read_text(encoding="utf-8"))
    manifest["phase_epoch"] = 3
    campaign_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    before = campaign_path.read_bytes()

    try:
        _poll(tmp_path, monkeypatch)
    except SystemExit as exc:
        assert "differs from immutable intent" in str(exc)
    else:
        raise AssertionError("stale campaign epoch was accepted")

    assert campaign_path.read_bytes() == before
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "DISPATCHED"


def test_phase_control_refuses_stale_phase_epoch_without_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    _, status_path, phase_path = _write_phase_request(tmp_path, "pause", "COLLECT")
    current = {"schema_version": "alina.phase.v2", "phase": "ANALYZE", "epoch": 5}
    phase_path.write_text(json.dumps(current), encoding="utf-8")
    before = phase_path.read_bytes()

    try:
        _poll(tmp_path, monkeypatch)
    except SystemExit as exc:
        assert "stale against the canonical phase epoch" in str(exc)
    else:
        raise AssertionError("stale phase request was accepted")

    assert phase_path.read_bytes() == before
    assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "DISPATCHED"

