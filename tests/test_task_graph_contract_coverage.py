from __future__ import annotations

from datetime import datetime
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


def _now() -> datetime:
    return datetime.fromisoformat("2026-09-10T17:30:00+00:00")


def test_acquire_ownership_rejects_invalid_lease_inputs() -> None:
    with pytest.raises(ValueError, match="timestamps must be timezone-aware"):
        acquire_ownership(
            "H-T-49",
            "agent-a",
            now=datetime(2026, 9, 10, 17, 30),
            ttl_seconds=60,
            token="secret-a",
        )
    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        acquire_ownership(
            "H-T-49",
            "agent-a",
            now=_now(),
            ttl_seconds=0,
            token="secret-a",
        )


def test_write_task_graph_atomic_cleans_temp_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="secret-a")
    node = TaskGraphNode(
        task_id="H-T-49", owner="agent-a", contributors=(), status="IN_PROGRESS",
        dependencies=(), handoff_from=None, handoff_to=None, reason="atomic cleanup proof",
        evidence_required=("tests",), done_contract="CODE→CALL_PATH→TEST→EVIDENCE→COMMIT",
        budget="bounded", lease=lease, commit_sha=None, task_type=TaskType.AUTO,
    )
    destination = tmp_path / "task_graph.json"

    def fail_replace(_source: str, _destination: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr("hl_observer.ops.task_graph_contract.os.replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        write_task_graph_atomic(destination, [node])

    assert destination.exists() is False
    assert list(tmp_path.iterdir()) == []


def test_write_task_graph_atomic_records_cleanup_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="secret-a")
    node = TaskGraphNode(
        task_id="H-T-49", owner="agent-a", contributors=(), status="IN_PROGRESS",
        dependencies=(), handoff_from=None, handoff_to=None, reason="cleanup race proof",
        evidence_required=("tests",), done_contract="CODE→CALL_PATH→TEST→EVIDENCE→COMMIT",
        budget="bounded", lease=lease, commit_sha=None, task_type=TaskType.AUTO,
    )
    recorded: list[tuple[str, BaseException]] = []

    def remove_then_fail(source: str, _destination: Path) -> None:
        Path(source).unlink()
        raise OSError("synthetic replace race")

    monkeypatch.setattr("hl_observer.ops.task_graph_contract.os.replace", remove_then_fail)
    monkeypatch.setattr(
        "hl_observer.ops.task_graph_contract._noter_echec",
        lambda key, exc: recorded.append((key, exc)),
    )

    with pytest.raises(OSError, match="synthetic replace race"):
        write_task_graph_atomic(tmp_path / "task_graph.json", [node])

    assert recorded and recorded[0][0].endswith(":atomic_cleanup")
    assert isinstance(recorded[0][1], FileNotFoundError)


def test_load_task_graph_rejects_non_list_tasks(tmp_path: Path) -> None:
    path = tmp_path / "task_graph.json"
    path.write_text(json.dumps({"schema_version": 1, "tasks": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="task graph tasks must be a list"):
        load_task_graph(path)


def test_load_task_graph_rejects_invalid_node_shape(tmp_path: Path) -> None:
    path = tmp_path / "task_graph.json"
    path.write_text(json.dumps({"schema_version": 1, "tasks": [None]}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid task graph node"):
        load_task_graph(path)


@pytest.mark.parametrize(
    ("lease_field", "value", "message"),
    [
        ("task_id", 49, "task_id must be a string"),
        ("owner", 49, "owner must be a string"),
        ("lease_started", None, "lease timestamps are required"),
    ],
)
def test_load_task_graph_rejects_invalid_persisted_lease_scalars(
    tmp_path: Path,
    lease_field: str,
    value: object,
    message: str,
) -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="secret-a")
    node = TaskGraphNode(
        task_id="H-T-49", owner="agent-a", contributors=(), status="IN_PROGRESS",
        dependencies=(), handoff_from=None, handoff_to=None, reason="persisted lease validation",
        evidence_required=("tests",), done_contract="CODE→CALL_PATH→TEST→EVIDENCE→COMMIT",
        budget="bounded", lease=lease, commit_sha=None, task_type=TaskType.AUTO,
    )
    path = tmp_path / "task_graph.json"
    write_task_graph_atomic(path, [node])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tasks"][0]["lease"][lease_field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_task_graph(path)
