from __future__ import annotations

import json

from hl_observer.core.error_handler import ErrorHandler


def test_error_handler_records_context_and_jsonl(tmp_path):
    path = tmp_path / "errors.jsonl"
    handler = ErrorHandler(path)

    event = handler.record(
        module="monitor",
        function="fetch_all_mids",
        severity="warning",
        error_type="TimeoutError",
        message="temporary read timeout",
        context={"source": "hyperliquid_info"},
        impact="source degraded",
        action_taken="retry scheduled",
        recovered=False,
        next_retry_at_ms=123,
    )

    assert event.severity == "WARNING"
    assert event.context["source"] == "hyperliquid_info"
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["next_retry_at_ms"] == 123


def test_error_handler_records_exception_stack():
    handler = ErrorHandler()

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        event = handler.record_exception(exc, module="copy", function="run")

    assert event.error_type == "RuntimeError"
    assert "boom" in event.message
    assert event.stack and "RuntimeError" in event.stack
