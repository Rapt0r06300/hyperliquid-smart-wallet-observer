from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.dashboard_truth.fake_data_detector import detect_placeholder_values
from hl_observer.dashboard_truth.metric_provenance import REQUIRED_SIMULATION_METRICS, get_nested
from hl_observer.simulation.decision_replay_analyzer import default_logs_to_send_dir


@dataclass(frozen=True, slots=True)
class DashboardTruthAudit:
    ok: bool
    snapshot_path: Path
    missing_metrics: tuple[str, ...]
    placeholder_findings: tuple[str, ...]
    provenance_rows: tuple[str, ...]


def run_dashboard_truth_audit(log_dir: Path | None = None) -> DashboardTruthAudit:
    log_dir = log_dir or default_logs_to_send_dir()
    snapshot_path = log_dir / "simulation_snapshot_latest.json"
    payload = _read_json(snapshot_path)
    missing: list[str] = []
    provenance: list[str] = []
    for metric in REQUIRED_SIMULATION_METRICS:
        value = get_nested(payload, metric.json_path)
        if value is None:
            missing.append(metric.metric)
        else:
            provenance.append(f"{metric.metric}: {metric.expected_source}:{metric.json_path}")
    placeholders = detect_placeholder_values(payload)
    return DashboardTruthAudit(
        ok=not missing and not placeholders,
        snapshot_path=snapshot_path,
        missing_metrics=tuple(missing),
        placeholder_findings=tuple(placeholders),
        provenance_rows=tuple(provenance),
    )


def format_dashboard_truth_audit(audit: DashboardTruthAudit) -> str:
    lines = [
        "dashboard_truth_audit=local_read_only",
        f"snapshot={audit.snapshot_path}",
        f"ok={str(audit.ok).lower()}",
        f"missing_metrics={len(audit.missing_metrics)}",
        f"placeholder_findings={len(audit.placeholder_findings)}",
    ]
    if audit.missing_metrics:
        lines.append("missing:")
        lines.extend(f"- {item}" for item in audit.missing_metrics)
    if audit.placeholder_findings:
        lines.append("placeholders:")
        lines.extend(f"- {item}" for item in audit.placeholder_findings)
    lines.append("provenance:")
    lines.extend(f"- {row}" for row in audit.provenance_rows)
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}

