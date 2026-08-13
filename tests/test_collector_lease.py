from __future__ import annotations

import json
import sys
from pathlib import Path

from hl_observer.ops.bounded_collection import (
    inspect_bounded_collectors,
    start_bounded_collectors,
)
from hl_observer.ops.collector_lease import (
    create_lease,
    public_lease,
    validate_lease,
)


class _FakeProcess:
    def __init__(self, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode

    def poll(self) -> int | None:
        return self.returncode


def test_lease_is_bounded_replaced_and_never_publicly_exposes_token(tmp_path: Path) -> None:
    lease_file, first = create_lease(
        tmp_path, duration_s=60.0, now=100.0, token="first-token"
    )
    assert validate_lease(lease_file, "first-token", tmp_path, now=159.999)[0] is True
    assert validate_lease(lease_file, "first-token", tmp_path, now=160.0)[:2] == (
        False,
        "COLLECTOR_LEASE_EXPIRED",
    )

    _, second = create_lease(
        tmp_path, duration_s=60.0, now=200.0, token="second-token"
    )
    assert validate_lease(lease_file, "first-token", tmp_path, now=201.0)[:2] == (
        False,
        "COLLECTOR_LEASE_REPLACED",
    )
    assert validate_lease(lease_file, "second-token", tmp_path, now=201.0)[0] is True
    assert "token" not in public_lease(second)
    assert public_lease(second)["paper_read_only"] is True
    assert public_lease(second)["real_execution"] is False
    assert first["lease_id"] != second["lease_id"]


def test_lease_fails_closed_for_wrong_root_and_safety_tampering(tmp_path: Path) -> None:
    lease_file, payload = create_lease(
        tmp_path, duration_s=60.0, now=100.0, token="token"
    )
    assert validate_lease(lease_file, "token", tmp_path / "other", now=101.0)[:2] == (
        False,
        "COLLECTOR_LEASE_ROOT_MISMATCH",
    )
    payload["real_execution"] = True
    lease_file.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_lease(lease_file, "token", tmp_path, now=101.0)[:2] == (
        False,
        "COLLECTOR_LEASE_SAFETY_INVALID",
    )


def test_bounded_start_reuses_launcher_collector_and_starts_only_missing(
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []
    sleeps: list[float] = []

    def inventory(_root: str | Path) -> list[dict[str, object]]:
        return [
            {
                "pid": 41,
                "ppid": 1,
                "name": "python.exe",
                "cmd": "python tools/collecter_allmids.py --une-fois",
            }
        ]

    def spawn(command: list[str], _root: Path, environment: dict[str, str]) -> _FakeProcess:
        commands.append(command)
        environments.append(environment)
        return _FakeProcess(90)

    result = start_bounded_collectors(
        tmp_path,
        ["allmids-collector", "bbo-collector"],
        duration_s=60.0,
        startup_wait_s=2.0,
        process_inventory=inventory,
        spawner=spawn,
        sleeper=sleeps.append,
    )

    assert result["reutilises"] == ["allmids-collector"]
    assert result["demarres_et_verifies"] == ["bbo-collector"]
    assert result["pids"] == {"allmids-collector": 41, "bbo-collector": 90}
    assert result["manquants"] == []
    assert sleeps == [2.0]
    assert len(commands) == 1
    assert commands[0][0] == str(Path(sys.executable).resolve())
    assert "run_bounded_collector.py" in commands[0][1]
    assert "--lease-token" not in commands[0]
    assert environments[0]["HYPERSMART_COLLECTOR_LEASE_TOKEN"]
    assert "token" not in result["lease"]
    persisted = json.loads(
        (tmp_path / "runtime/data/economic_collection_pids.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["pids"] == result["pids"]
    assert "token" not in json.dumps(persisted)


def test_bounded_start_never_reports_process_that_dies_during_startup(
    tmp_path: Path,
) -> None:
    def spawn(_command: list[str], _root: Path, _environment: dict[str, str]) -> _FakeProcess:
        return _FakeProcess(91, returncode=7)

    result = start_bounded_collectors(
        tmp_path,
        ["bbo-collector"],
        duration_s=60.0,
        startup_wait_s=0.25,
        process_inventory=lambda _root: [],
        spawner=spawn,
        sleeper=lambda _seconds: None,
    )

    assert result["pids"] == {}
    assert result["demarres_et_verifies"] == []
    assert result["manquants"] == ["bbo-collector"]
    assert result["early_returncodes"] == {"bbo-collector": 7}


def test_old_bounded_wrapper_is_not_reused_after_lease_replacement(tmp_path: Path) -> None:
    spawned: list[list[str]] = []

    def inventory(_root: str | Path) -> list[dict[str, object]]:
        return [
            {
                "pid": 50,
                "ppid": 1,
                "name": "python.exe",
                "cmd": "python tools/run_bounded_collector.py --name bbo-collector",
            }
        ]

    def spawn(command: list[str], _root: Path, _environment: dict[str, str]) -> _FakeProcess:
        spawned.append(command)
        return _FakeProcess(51)

    result = start_bounded_collectors(
        tmp_path,
        ["bbo-collector"],
        duration_s=60.0,
        startup_wait_s=0.1,
        process_inventory=inventory,
        spawner=spawn,
        sleeper=lambda _seconds: None,
    )

    assert spawned
    assert result["reutilises"] == []
    assert result["pids"] == {"bbo-collector": 51}


def test_inspection_preserves_verified_active_campaign_without_restart(tmp_path: Path) -> None:
    def spawn(_command: list[str], _root: Path, _environment: dict[str, str]) -> _FakeProcess:
        return _FakeProcess(91)

    started = start_bounded_collectors(
        tmp_path,
        ["bbo-collector"],
        duration_s=60.0,
        startup_wait_s=0.0,
        process_inventory=lambda _root: [],
        spawner=spawn,
        sleeper=lambda _seconds: None,
    )
    lease = json.loads(
        (tmp_path / "runtime/data/economic_collection_lease.json").read_text(
            encoding="utf-8"
        )
    )
    now = float(lease["issued_at_ms"]) / 1000.0 + 1.0
    inspected = inspect_bounded_collectors(
        tmp_path,
        process_inventory=lambda _root: [
            {
                "pid": 91,
                "ppid": 1,
                "name": "python.exe",
                "cmd": "python tools/run_bounded_collector.py --name bbo-collector",
            }
        ],
        now=now,
    )

    assert inspected is not None
    assert inspected["status"] == "ACTIVE"
    assert inspected["actifs"] == {"bbo-collector": 91}
    assert inspected["arretes"] == []
    assert inspected["lease_valid"] is True
    assert "token" not in json.dumps(inspected)
    assert inspected["pids"] == started["pids"]


def test_inspection_exposes_protocol_only_for_heartbeat_owned_by_active_pid(
    tmp_path: Path,
) -> None:
    def spawn(_command: list[str], _root: Path, _environment: dict[str, str]) -> _FakeProcess:
        return _FakeProcess(191)

    start_bounded_collectors(
        tmp_path,
        ["bbo-collector"],
        duration_s=60.0,
        startup_wait_s=0.0,
        process_inventory=lambda _root: [],
        spawner=spawn,
        sleeper=lambda _seconds: None,
    )
    heartbeat_dir = tmp_path / "runtime/research_lab/heartbeats"
    heartbeat_dir.mkdir(parents=True, exist_ok=True)
    heartbeat = heartbeat_dir / "bbo-collector.json"
    heartbeat.write_text(
        json.dumps({"pid": 191, "protocol": "bbo-causal-v2"}),
        encoding="utf-8",
    )
    lease = json.loads(
        (tmp_path / "runtime/data/economic_collection_lease.json").read_text(
            encoding="utf-8"
        )
    )
    now = float(lease["issued_at_ms"]) / 1000.0 + 1.0
    def inventory(_root: Path) -> list[dict[str, object]]:
        return [
            {
                "pid": 191,
                "ppid": 1,
                "name": "python.exe",
                "cmd": "python tools/run_bounded_collector.py --name bbo-collector",
            }
        ]

    inspected = inspect_bounded_collectors(tmp_path, process_inventory=inventory, now=now)
    assert inspected["protocols"] == {"bbo-collector": "bbo-causal-v2"}

    heartbeat.write_text(
        json.dumps({"pid": 999, "protocol": "forged-protocol"}),
        encoding="utf-8",
    )
    inspected = inspect_bounded_collectors(tmp_path, process_inventory=inventory, now=now)
    assert inspected["protocols"] == {}


def test_inspection_reports_expired_or_missing_process_fail_closed(tmp_path: Path) -> None:
    def spawn(_command: list[str], _root: Path, _environment: dict[str, str]) -> _FakeProcess:
        return _FakeProcess(92)

    start_bounded_collectors(
        tmp_path,
        ["bbo-collector"],
        duration_s=60.0,
        startup_wait_s=0.0,
        process_inventory=lambda _root: [],
        spawner=spawn,
        sleeper=lambda _seconds: None,
    )
    lease = json.loads(
        (tmp_path / "runtime/data/economic_collection_lease.json").read_text(
            encoding="utf-8"
        )
    )
    after_expiry = float(lease["expires_at_ms"]) / 1000.0 + 1.0
    inspected = inspect_bounded_collectors(
        tmp_path,
        process_inventory=lambda _root: [],
        now=after_expiry,
    )

    assert inspected is not None
    assert inspected["status"] == "DEGRADED"
    assert inspected["actifs"] == {}
    assert inspected["arretes"] == ["bbo-collector"]
    assert inspected["lease_valid"] is False
    assert inspected["lease_reason"] == "COLLECTOR_LEASE_EXPIRED"


def test_inspection_rejects_replaced_lease_and_pid_reuse(tmp_path: Path) -> None:
    def spawn(_command: list[str], _root: Path, _environment: dict[str, str]) -> _FakeProcess:
        return _FakeProcess(93)

    start_bounded_collectors(
        tmp_path,
        ["bbo-collector"],
        duration_s=60.0,
        startup_wait_s=0.0,
        process_inventory=lambda _root: [],
        spawner=spawn,
        sleeper=lambda _seconds: None,
    )
    _, replacement = create_lease(
        tmp_path,
        duration_s=60.0,
        now=200.0,
        token="replacement-token",
    )
    inspected = inspect_bounded_collectors(
        tmp_path,
        process_inventory=lambda _root: [
            {
                "pid": 93,
                "ppid": 1,
                "name": "python.exe",
                "cmd": "python unrelated.py --name bbo-collector",
            }
        ],
        now=201.0,
    )

    assert inspected is not None
    assert inspected["status"] == "DEGRADED"
    assert inspected["actifs"] == {}
    assert inspected["arretes"] == ["bbo-collector"]
    assert inspected["lease_valid"] is False
    assert inspected["lease_reason"] == "COLLECTOR_LEASE_REPLACED"
    assert inspected["lease"]["lease_id"] == replacement["lease_id"]
    assert "token" not in json.dumps(inspected)
