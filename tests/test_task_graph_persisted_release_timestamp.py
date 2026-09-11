from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def test_load_task_graph_rejects_release_before_lease_start(tmp_path: Path) -> None:
    path = tmp_path / "task_graph.json"
    started = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    lease = acquire_ownership(
        "H-T-49",
        "asf-e5",
        now=started,
        ttl_seconds=60,
        token="runtime-only",
    )
    node = TaskGraphNode(
        task_id="H-T-49",
        owner="asf-e5",
        contributors=(),
        status="IN_PROGRESS",
        dependencies=(),
        handoff_from=None,
        handoff_to=None,
        reason="resume persisted runtime state",
        evidence_required=("tests",),
        done_contract="CODE→CALL_PATH→TEST→EVIDENCE→COMMIT",
        budget="bounded",
        lease=lease,
        commit_sha=None,
        task_type=TaskType.AUTO,
    )
    write_task_graph_atomic(path, [node])

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tasks"][0]["lease"]["released_at"] = (
        started - timedelta(seconds=1)
    ).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"released_at must not precede lease start"):
        load_task_graph(path)
