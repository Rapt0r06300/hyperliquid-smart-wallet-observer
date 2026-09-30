from __future__ import annotations

import asyncio
import json
from pathlib import Path

from hl_observer.realtime_monitor.ws_supervisor import WsSupervisor
from hl_observer.runtime.child_process_supervisor import ChildProcessSupervisor
from hl_observer.runtime.persistent_poll_runner import PersistentPollRunner, RunnerConfig
from hl_observer.runtime.status_freshness import (
    stamp_status_fields,
    status_field_is_fresh,
)
from hl_observer.wallets.backfill import _fetch_user_fills_by_time


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.exit_code: int | None = None

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.exit_code = 0

    def kill(self):
        self.exit_code = -9

    def wait(self, timeout=None):
        return self.exit_code


def test_fills_multiplex_death_is_detected_and_recovered(tmp_path):
    processes = [_FakeProcess(101), _FakeProcess(102)]

    def spawn(argv, stdout_file):
        stdout_file.write("child-started\n")
        return processes.pop(0)

    config = RunnerConfig(
        root=tmp_path,
        fills_multiplex=True,
        fills_multiplex_connections=2,
    )
    runner = PersistentPollRunner(
        config,
        popen=spawn,
        now_ms_fn=iter((1_000, 1_001, 2_000, 2_001, 2_002)).__next__,
    )

    supervisor = runner._spawn_fills_multiplex()
    assert supervisor is not None
    assert supervisor.process.pid == 101
    supervisor.process.exit_code = 7

    recovered = runner._check_fills_multiplex(supervisor)

    assert recovered.process.pid == 102
    assert runner.metrics["fills_multiplex_status"] == "RUNNING"
    assert runner.metrics["fills_multiplex_restart_count"] == "1"
    assert runner.metrics["fills_multiplex_last_exit_code"] == "7"
    assert Path(runner.metrics["fills_multiplex_log_path"]).exists()
    runner._terminate_fills_multiplex(recovered)


def test_child_restart_budget_is_bounded(tmp_path):
    created: list[_FakeProcess] = []
    clock = iter((1_000, 1_001, 1_002, 1_003, 1_004, 1_005))

    def spawn(argv, stdout_file):
        proc = _FakeProcess(200 + len(created))
        created.append(proc)
        return proc

    supervisor = ChildProcessSupervisor(
        name="bounded",
        argv=["python", "-V"],
        cwd=tmp_path,
        log_path=tmp_path / "child.log",
        spawn=spawn,
        now_ms=clock.__next__,
        max_restarts=1,
        restart_window_ms=60_000,
    )
    supervisor.start()
    created[-1].exit_code = 1
    assert supervisor.check_and_recover().state == "RUNNING"
    created[-1].exit_code = 2
    blocked = supervisor.check_and_recover()
    assert blocked.state == "RESTART_BUDGET_EXHAUSTED"
    assert len(created) == 2


def test_stale_engine_status_fields_are_not_reused_as_fresh(tmp_path):
    status_path = tmp_path / "runtime" / "data" / "hypersmart_engine_status.json"
    status_path.parent.mkdir(parents=True)
    payload = {
        "updated_at_ms": 10,
        "session_id": "session-a",
        "fusion_runtime_input": {"leader_votes": [{"coin": "BTC"}]},
        "fusion_runtime_input_status": "READY",
        "metrics": {"fusion_runtime_votes": "1"},
    }
    stamp_status_fields(
        payload,
        ("fusion_runtime_group",),
        producer="fusion_heartbeat_input",
        session_id="session-a",
        updated_at_ms=10,
    )
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    runner = PersistentPollRunner(
        RunnerConfig(root=tmp_path),
        now_ms_fn=lambda: 100_000,
    )
    runner._session_id = "session-a"

    runner.write_engine_status("poll_start", "fresh poll")
    written = json.loads(status_path.read_text(encoding="utf-8"))

    assert "fusion_runtime_input" not in written
    assert written["fusion_runtime_input_status"] == "STALE"
    assert "fusion_runtime_votes" not in written["metrics"]


def test_status_field_requires_matching_session_and_age():
    payload: dict[str, object] = {}
    stamp_status_fields(
        payload,
        ("field",),
        producer="producer",
        session_id="session-a",
        updated_at_ms=1_000,
    )
    assert status_field_is_fresh(
        payload,
        "field",
        current_ms=1_500,
        session_id="session-a",
        max_age_ms=1_000,
    )
    assert not status_field_is_fresh(
        payload,
        "field",
        current_ms=1_500,
        session_id="session-b",
        max_age_ms=1_000,
    )
    assert not status_field_is_fresh(
        payload,
        "field",
        current_ms=3_000,
        session_id="session-a",
        max_age_ms=1_000,
    )


class _PagedClient:
    def __init__(self) -> None:
        self.starts: list[int] = []

    async def user_fills_by_time(
        self,
        wallet,
        start,
        end,
        *,
        aggregate_by_time,
    ):
        self.starts.append(start)
        if len(self.starts) == 1:
            return [{"time": index} for index in range(1, 501)]
        return []


def test_wallet_backfill_uses_500_item_timestamp_cursor():
    client = _PagedClient()
    pages = asyncio.run(
        _fetch_user_fills_by_time(
            client,
            "0x" + "1" * 40,
            0,
            2_000,
            0,
            3,
        )
    )
    assert client.starts == [0, 501]
    assert len(pages) == 1
    assert len(pages[0][0]) == 500


def test_ws_reconnect_is_bounded_and_requests_gap_recovery():
    supervisor = WsSupervisor(heartbeat_max_age_ms=100)
    supervisor.last_heartbeat_ms = 1_000
    decision = supervisor.gap_recovery_decision(now_ms=1_101)
    assert decision.needs_gap_recovery is True
    assert decision.reason == "HEARTBEAT_STALE_REST_GAP_RECOVERY"
    first = supervisor.next_reconnect_delay()
    second = supervisor.next_reconnect_delay()
    assert first >= 0
    assert second >= 0
    assert supervisor.reconnect_attempt == 2
