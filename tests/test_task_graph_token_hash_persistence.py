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


def test_load_task_graph_rejects_malformed_persisted_token_hash(tmp_path: Path) -> None:
    now = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
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
    path = tmp_path / "task_graph.json"
    write_task_graph_atomic(path, [node])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tasks"][0]["lease"]["token_hash"] = "not-a-sha256"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="token_hash"):
        load_task_graph(path)
