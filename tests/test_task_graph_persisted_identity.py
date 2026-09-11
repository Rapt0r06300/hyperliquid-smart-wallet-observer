from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from hl_observer.ops.task_graph_contract import (
    TaskGraphNode,
    TaskType,
    acquire_ownership,
    load_task_graph,
    write_task_graph_atomic,
)


def _write_canonical_graph(path: Path) -> None:
    now = datetime(2026, 9, 11, 2, 35, tzinfo=timezone.utc)
    lease = acquire_ownership("H-T-49", "agent-a", now=now, ttl_seconds=60, token="secret-a")
    node = TaskGraphNode(
        task_id="H-T-49",
        owner="agent-a",
        contributors=(),
        status="IN_PROGRESS",
        dependencies=(),
        handoff_from=None,
        handoff_to=None,
        reason="resume canonical task",
        evidence_required=("tests",),
        done_contract="CODE→CALL_PATH→TEST→EVIDENCE→COMMIT",
        budget="bounded",
        lease=lease,
        commit_sha=None,
        task_type=TaskType.AUTO,
    )
    write_task_graph_atomic(path, [node])


@pytest.mark.parametrize(("field", "message"), [("task_id", "task_id must not be empty"), ("owner", "owner must not be empty")])
def test_load_task_graph_rejects_empty_persisted_identity(tmp_path: Path, field: str, message: str) -> None:
    path = tmp_path / "task_graph.json"
    _write_canonical_graph(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tasks"][0][field] = ""
    payload["tasks"][0]["lease"][field] = ""
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_task_graph(path)


@pytest.mark.parametrize("field", ["task_id", "owner"])
@pytest.mark.parametrize("invalid_value", [None, 7])
def test_load_task_graph_rejects_non_string_persisted_identity(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    path = tmp_path / "task_graph.json"
    _write_canonical_graph(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tasks"][0][field] = invalid_value
    payload["tasks"][0]["lease"][field] = invalid_value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=rf"{field} must be a string"):
        load_task_graph(path)


@pytest.mark.parametrize("field", ["contributors", "dependencies", "evidence_required"])
def test_load_task_graph_rejects_non_string_entries_in_persisted_string_lists(
    tmp_path: Path,
    field: str,
) -> None:
    path = tmp_path / "task_graph.json"
    _write_canonical_graph(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tasks"][0][field] = ["valid", 7]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=rf"{field} must be a list of strings"):
        load_task_graph(path)
