from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from hl_observer.ops.task_graph_contract import (
    AutonomousAction,
    DoneContractEvidence,
    TaskGraphNode,
    TaskType,
    Transition,
    acquire_ownership,
    assert_autonomous_action_allowed,
    can_mutate_task,
    load_task_graph,
    transfer_ownership,
    validate_done_contract,
    write_task_graph_atomic,
)


def _now() -> datetime:
    return datetime(2026, 9, 10, 17, 30, tzinfo=timezone.utc)


def test_ownership_token_and_lease_are_required_for_canonical_mutation() -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="secret-a")
    assert can_mutate_task(lease, owner="agent-a", token="secret-a", now=_now()) is True
    assert can_mutate_task(lease, owner="agent-b", token="secret-a", now=_now()) is False
    assert can_mutate_task(lease, owner="agent-a", token="wrong", now=_now()) is False
    assert can_mutate_task(
        lease,
        owner="agent-a",
        token="secret-a",
        now=_now() + timedelta(seconds=61),
    ) is False


def test_handoff_invalidates_old_owner_and_grants_new_owner() -> None:
    old = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="old")
    new, receipt = transfer_ownership(
        old,
        current_owner="agent-a",
        current_token="old",
        new_owner="agent-b",
        now=_now() + timedelta(seconds=10),
        ttl_seconds=90,
        new_token="new",
    )
    assert receipt.old_owner == "agent-a"
    assert receipt.new_owner == "agent-b"
    assert can_mutate_task(old, owner="agent-a", token="old", now=_now() + timedelta(seconds=20)) is False
    assert can_mutate_task(new, owner="agent-b", token="new", now=_now() + timedelta(seconds=20)) is True


def test_autonomous_envelope_allows_safe_work_and_rejects_hard_boundaries() -> None:
    assert_autonomous_action_allowed(AutonomousAction.RUN_TESTS)
    assert_autonomous_action_allowed(AutonomousAction.UPDATE_TASK_STATE)
    with pytest.raises(PermissionError):
        assert_autonomous_action_allowed("real_execution")
    with pytest.raises(PermissionError):
        assert_autonomous_action_allowed("weaken_safety")
    with pytest.raises(PermissionError):
        assert_autonomous_action_allowed("alter_hidden_oos")


def test_done_contract_is_fail_closed_and_does_not_depend_on_profit_target() -> None:
    complete = DoneContractEvidence(
        code=True,
        real_call_path=True,
        valid_input=True,
        effect_or_decision=True,
        artifact_or_ledger=True,
        tests=True,
        evidence=True,
        commit_sha="a" * 40,
    )
    assert validate_done_contract(complete) == []

    incomplete = DoneContractEvidence(
        code=True,
        real_call_path=True,
        valid_input=True,
        effect_or_decision=False,
        artifact_or_ledger=True,
        tests=True,
        evidence=True,
        commit_sha="a" * 40,
    )
    assert "effect_or_decision" in validate_done_contract(incomplete)
    assert not hasattr(complete, "pnl_target_usd")


def test_task_graph_state_roundtrip_is_resumable_and_does_not_persist_bearer_token(tmp_path: Path) -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="secret-a")
    node = TaskGraphNode(
        task_id="H-T-49",
        owner="agent-a",
        contributors=("reviewer",),
        status="IN_PROGRESS",
        dependencies=("H-T-48",),
        handoff_from=None,
        handoff_to=None,
        reason="implement canonical task graph contract",
        evidence_required=("tests", "commit"),
        done_contract="CODE→CALL_PATH→TEST→EVIDENCE→COMMIT",
        budget="bounded",
        lease=lease,
        commit_sha=None,
        task_type=TaskType.AUTO,
        transition=Transition.PAUSE,
    )
    path = tmp_path / "task_graph.json"
    write_task_graph_atomic(path, [node])
    raw = path.read_text(encoding="utf-8")
    assert "secret-a" not in raw
    restored = load_task_graph(path)
    assert restored[0].task_id == "H-T-49"
    assert restored[0].owner == "agent-a"
    assert restored[0].dependencies == ("H-T-48",)
    assert restored[0].transition is Transition.PAUSE


def test_load_task_graph_rejects_lease_bound_to_another_task(tmp_path: Path) -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="secret-a")
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
    payload["tasks"][0]["lease"]["task_id"] = "H-T-OTHER"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="lease task_id does not match node task_id"):
        load_task_graph(path)


def test_load_task_graph_rejects_lease_owned_by_another_agent(tmp_path: Path) -> None:
    lease = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="secret-a")
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
    payload["tasks"][0]["lease"]["owner"] = "agent-b"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="lease owner does not match node owner"):
        load_task_graph(path)


def test_load_task_graph_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    first = acquire_ownership("H-T-49", "agent-a", now=_now(), ttl_seconds=60, token="secret-a")
    second = acquire_ownership("H-T-49", "agent-b", now=_now(), ttl_seconds=60, token="secret-b")
    nodes = [
        TaskGraphNode(
            task_id="H-T-49", owner="agent-a", contributors=(), status="IN_PROGRESS",
            dependencies=(), handoff_from=None, handoff_to=None, reason="first canonical row",
            evidence_required=("tests",), done_contract="CODE→CALL_PATH→TEST→EVIDENCE→COMMIT",
            budget="bounded", lease=first, commit_sha=None, task_type=TaskType.AUTO,
        ),
        TaskGraphNode(
            task_id="H-T-49", owner="agent-b", contributors=(), status="PAUSED",
            dependencies=(), handoff_from=None, handoff_to=None, reason="ambiguous duplicate row",
            evidence_required=("tests",), done_contract="CODE→CALL_PATH→TEST→EVIDENCE→COMMIT",
            budget="bounded", lease=second, commit_sha=None, task_type=TaskType.AUTO,
        ),
    ]
    path = tmp_path / "task_graph.json"
    write_task_graph_atomic(path, nodes)

    with pytest.raises(ValueError, match="duplicate task_id"):
        load_task_graph(path)


def test_done_contract_rejects_invalid_commit_sha() -> None:
    evidence = DoneContractEvidence(
        code=True,
        real_call_path=True,
        valid_input=True,
        effect_or_decision=True,
        artifact_or_ledger=True,
        tests=True,
        evidence=True,
        commit_sha="not-a-sha",
    )
    assert "commit_sha" in validate_done_contract(evidence)
