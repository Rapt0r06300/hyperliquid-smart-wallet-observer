import json

from tools.build_closure_report import (
    _operator_supersession_is_valid,
    _summarize_operator_status,
)


def test_operator_status_report_preserves_supersession_reason_and_target() -> None:
    row = {
        "request_id": "a" * 64,
        "intent": "pause",
        "state": "BLOCKED",
        "terminal": True,
        "workflow_run_id": "run-123",
        "updated_at_utc": "2026-10-27T00:00:00Z",
        "status_reason": "SUPERSEDED_BY_NEWER_CONTROL_INTENT",
        "superseded_by_request_id": "b" * 64,
    }

    summary = _summarize_operator_status(row)

    assert summary == {
        "request_id": "a" * 64,
        "intent": "pause",
        "state": "BLOCKED",
        "terminal": True,
        "workflow_run_id": "run-123",
        "updated_at_utc": "2026-10-27T00:00:00Z",
        "status_reason": "SUPERSEDED_BY_NEWER_CONTROL_INTENT",
        "superseded_by_request_id": "b" * 64,
    }


def test_closure_report_rejects_incomplete_supersession_status() -> None:
    status = {
        "request_id": "a" * 64,
        "intent": "pause",
        "state": "BLOCKED",
        "terminal": True,
        "status_reason": "SUPERSEDED_BY_NEWER_CONTROL_INTENT",
    }

    assert _operator_supersession_is_valid(status) is False


def test_closure_report_accepts_linked_supersession_status(tmp_path) -> None:
    intent_dir = tmp_path / "operator-intents"
    intent_dir.mkdir()
    older_id = "a" * 64
    newer_id = "b" * 64
    current_intent_path = intent_dir / f"{older_id}.json"
    status = {
        "request_id": older_id,
        "intent": "pause",
        "state": "BLOCKED",
        "terminal": True,
        "status_reason": "SUPERSEDED_BY_NEWER_CONTROL_INTENT",
        "superseded_by_request_id": newer_id,
    }
    current_intent_path.write_text(
        json.dumps(
            {
                "schema_version": "alina.operator_intent.v2",
                "request_id": older_id,
                "intent": "pause",
                "requested_at_utc": "2026-10-26T11:00:00Z",
                "paper_only": True,
                "read_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )
    (intent_dir / f"{newer_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "alina.operator_intent.v2",
                "request_id": newer_id,
                "intent": "resume",
                "requested_at_utc": "2026-10-26T13:00:00Z",
                "paper_only": True,
                "read_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )

    assert _operator_supersession_is_valid(status, current_intent_path) is True


def test_closure_report_rejects_dangling_supersession_reference(tmp_path) -> None:
    intent_path = tmp_path / "older.json"
    intent_path.write_text(
        json.dumps(
            {
                "schema_version": "alina.operator_intent.v2",
                "request_id": "a" * 64,
                "intent": "pause",
                "requested_at_utc": "2026-10-26T11:00:00Z",
                "paper_only": True,
                "read_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )
    status = {
        "request_id": "a" * 64,
        "intent": "pause",
        "state": "BLOCKED",
        "terminal": True,
        "status_reason": "SUPERSEDED_BY_NEWER_CONTROL_INTENT",
        "superseded_by_request_id": "b" * 64,
    }

    assert _operator_supersession_is_valid(status, intent_path) is False
