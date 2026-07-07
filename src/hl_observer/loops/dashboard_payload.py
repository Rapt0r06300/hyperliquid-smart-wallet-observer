from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl_observer.loops.memory import default_loop_memory_dir


def build_loop_dashboard_payload(memory_dir: Path | None = None) -> dict[str, Any]:
    root = memory_dir or default_loop_memory_dir(Path.cwd())
    latest_json = root / "latest_loop_result.json"
    latest_report = root / "latest_loop_report.md"
    latest_trace = root / "latest_decision_trace.json"
    latest_input_diagnostics = root / "latest_loop_input_diagnostics.json"
    payload: dict[str, Any] = {
        "status": "EMPTY",
        "memory_dir": str(root),
        "latest_result_path": str(latest_json),
        "latest_report_path": str(latest_report),
        "latest_trace_path": str(latest_trace),
        "latest_input_diagnostics_path": str(latest_input_diagnostics),
        "has_latest_result": latest_json.exists(),
        "has_latest_report": latest_report.exists(),
        "has_latest_trace": latest_trace.exists(),
        "has_latest_input_diagnostics": latest_input_diagnostics.exists(),
        "latest_result": None,
        "latest_report_preview": "",
        "latest_decision_trace": [],
        "latest_input_diagnostics": None,
    }
    if latest_json.exists():
        try:
            payload["latest_result"] = json.loads(latest_json.read_text(encoding="utf-8"))
            payload["status"] = "READY"
        except Exception as exc:  # noqa: BLE001 - dashboard payload should degrade honestly.
            payload["status"] = "ERROR"
            payload["error"] = f"latest_loop_result_unreadable:{exc}"
    if latest_report.exists():
        try:
            text = latest_report.read_text(encoding="utf-8")
            payload["latest_report_preview"] = text[:4_000]
        except Exception as exc:  # noqa: BLE001
            payload["report_error"] = f"latest_loop_report_unreadable:{exc}"
    if latest_trace.exists():
        try:
            trace = json.loads(latest_trace.read_text(encoding="utf-8"))
            payload["latest_decision_trace"] = trace if isinstance(trace, list) else []
        except Exception as exc:  # noqa: BLE001
            payload["trace_error"] = f"latest_decision_trace_unreadable:{exc}"
    if latest_input_diagnostics.exists():
        try:
            payload["latest_input_diagnostics"] = json.loads(latest_input_diagnostics.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            payload["input_diagnostics_error"] = f"latest_loop_input_diagnostics_unreadable:{exc}"
    return payload
