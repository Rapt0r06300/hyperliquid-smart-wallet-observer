"""Verified, bounded startup for standalone read-only collection campaigns.

The visible launcher owns its normal collectors.  Economic evidence campaigns
may need a subset of the same registry without the UI, so this module reuses
launcher-owned processes and gives every additional process an expiring lease.
It reports a collector as started only after the wrapper is still alive at the
end of a configurable startup observation window.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol

from .collecteur_registry import COLLECTEURS_CAMPAGNE, REGISTRE
from .collector_lease import DEFAULT_RELPATH as LEASE_RELPATH
from .collector_lease import create_lease, public_lease, validate_lease
from .superviseur_collecteurs import _pid_collecteur_existant, _processus_projet

SCHEMA_VERSION = "hypersmart.bounded_collection_start.v1"
STATE_RELPATH = Path("runtime") / "data" / "economic_collection_pids.json"


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...


Spawner = Callable[[list[str], Path, Mapping[str, str]], ProcessHandle]


def _registry(*, campaign_only: bool = False) -> dict[str, dict[str, Any]]:
    rows = COLLECTEURS_CAMPAGNE if campaign_only else REGISTRE + COLLECTEURS_CAMPAGNE
    return {str(row["nom"]): row for row in rows}


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def resolve_project_python(root: str | Path) -> Path:
    """Prefer the embedded runtime so campaign processes remain portable."""

    project_root = Path(root).resolve()
    candidates = (
        project_root / "portable_runtime" / "python" / "python.exe",
        project_root / "tools" / "python" / "python.exe",
        Path(sys.executable),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("no usable Python executable for bounded collection")


def _default_spawn(
    command: list[str], root: Path, environment: Mapping[str, str]
) -> ProcessHandle:
    flags = 0
    if os.name == "nt":
        flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(  # noqa: S603 - fixed local runner and registry scripts
        command,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=dict(environment),
        creationflags=flags,
    )


def _bounded_process_ids(processes: list[dict[str, Any]]) -> set[int]:
    """Return bounded wrappers and descendants so they are never reused."""

    bounded = {
        int(row["pid"])
        for row in processes
        if isinstance(row.get("pid"), int)
        and "run_bounded_collector.py" in str(row.get("cmd") or "").lower()
    }
    while bounded:
        descendants = {
            int(row["pid"])
            for row in processes
            if isinstance(row.get("pid"), int) and row.get("ppid") in bounded
        }
        new = descendants - bounded
        if not new:
            break
        bounded.update(new)
    return bounded


def _tail(path: Path, *, lines: int = 8) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-max(1, int(lines)) :]


def _active_collector_protocols(
    root: Path, active: Mapping[str, int]
) -> dict[str, str]:
    """Read protocol markers only from heartbeats owned by the active PID."""

    protocols: dict[str, str] = {}
    heartbeat_dir = root / "runtime" / "research_lab" / "heartbeats"
    for name, pid in active.items():
        path = heartbeat_dir / f"{name}.json"
        try:
            heartbeat = json.loads(path.read_text(encoding="utf-8"))
            heartbeat_pid = int(heartbeat.get("pid"))
        except (OSError, ValueError, TypeError):
            continue
        protocol = str(heartbeat.get("protocol") or "").strip()
        if heartbeat_pid == int(pid) and protocol:
            protocols[name] = protocol
    return protocols


def start_bounded_collectors(
    root: str | Path,
    names: Iterable[str],
    *,
    duration_s: float = 24 * 60 * 60,
    startup_wait_s: float = 3.0,
    process_inventory: Callable[[str | Path], list[dict[str, Any]]] | None = None,
    spawner: Spawner | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Start only requested registry collectors and verify wrapper survival.

    Existing launcher-owned collectors are reused.  Existing campaign-owned
    wrappers are deliberately excluded: replacing the lease invalidates them,
    and fresh wrappers are started under the new bounded owner.
    """

    project_root = Path(root).resolve()
    requested = list(dict.fromkeys(str(name) for name in names))
    registry = _registry()
    selected = [registry[name] for name in requested if name in registry]
    unknown = [name for name in requested if name not in registry]
    inventory = process_inventory or _processus_projet
    current = list(inventory(project_root))
    bounded_ids = _bounded_process_ids(current)
    launcher_owned = [row for row in current if row.get("pid") not in bounded_ids]

    reused: dict[str, int] = {}
    pending: list[dict[str, Any]] = []
    for collector in selected:
        existing = _pid_collecteur_existant(collector, launcher_owned)
        if existing is None:
            pending.append(collector)
        else:
            reused[str(collector["nom"])] = int(existing)

    lease_file = None
    lease_payload = None
    handles: dict[str, ProcessHandle] = {}
    launch_errors: dict[str, str] = {}
    python_executable = resolve_project_python(project_root)
    if pending:
        lease_file, lease_payload = create_lease(
            project_root, duration_s=float(duration_s)
        )
        # Give wrappers invalidated by the atomic lease replacement one poll to
        # stop before a persistent worker attempts to reacquire its local lock.
        if bounded_ids:
            sleeper(min(1.5, max(0.0, float(startup_wait_s) / 2.0)))
        runner = project_root / "tools" / "run_bounded_collector.py"
        launch = spawner or _default_spawn
        for collector in pending:
            name = str(collector["nom"])
            command = [
                str(python_executable),
                str(runner),
                "--root",
                str(project_root),
                "--name",
                name,
                "--script",
                str(collector["script"]),
                "--interval-s",
                str(float(collector["intervalle_s"])),
                "--lease-file",
                str(lease_file),
                "--",
                *[str(value) for value in collector.get("args", ())],
            ]
            environment = {
                **os.environ,
                "PYTHONPATH": str(project_root / "src"),
                "PYTHONIOENCODING": "utf-8",
                "HYPERSMART_COLLECTOR_LEASE_TOKEN": str(lease_payload["token"]),
            }
            try:
                handles[name] = launch(command, project_root, environment)
            except Exception as exc:  # noqa: BLE001 - every startup failure is reported
                launch_errors[name] = f"{type(exc).__name__}: {exc}"

    if handles:
        sleeper(max(0.0, float(startup_wait_s)))

    started: dict[str, int] = {}
    returncodes: dict[str, int] = {}
    for name, handle in handles.items():
        returncode = handle.poll()
        if returncode is None:
            started[name] = int(handle.pid)
        else:
            returncodes[name] = int(returncode)

    missing = [
        name
        for name in requested
        if name not in reused and name not in started
    ]
    log_tails = {
        name: _tail(project_root / "runtime" / "logs" / f"economic-{name}.log")
        for name in started
    }
    state = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": int(time.time() * 1000),
        "owner": "economic_evidence_campaign",
        "paper_read_only": True,
        "real_execution": False,
        "requested": requested,
        "selectionnes": len(selected),
        "pids": {**reused, **started},
        "reutilises": sorted(reused),
        "demarres_et_verifies": sorted(started),
        "manquants": missing,
        "inconnus": unknown,
        "launch_errors": launch_errors,
        "early_returncodes": returncodes,
        "startup_wait_s": float(startup_wait_s),
        "python_executable": str(python_executable),
        "lease": public_lease(lease_payload) if lease_payload is not None else None,
        "startup_log_tails": log_tails,
    }
    _atomic_write(project_root / STATE_RELPATH, state)
    return state


def attach_bounded_collectors(
    root: str | Path,
    names: Iterable[str],
    *,
    startup_wait_s: float = 3.0,
    process_inventory: Callable[[str | Path], list[dict[str, Any]]] | None = None,
    spawner: Spawner | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    now: float | None = None,
) -> dict[str, Any]:
    """Attach campaign-only collectors to the current lease without replacing it.

    This path exists for evidence companions that must start while a verified
    bounded campaign is already collecting. It fails closed unless every
    recorded process is still owned and the persisted bearer lease is valid.
    The lease ID, expiry and existing PID set are preserved byte-for-byte.
    """

    project_root = Path(root).resolve()
    requested = list(dict.fromkeys(str(name) for name in names))
    campaign_registry = _registry(campaign_only=True)
    unknown = [name for name in requested if name not in campaign_registry]
    if unknown:
        raise ValueError("campaign collector unknown: %s" % ",".join(unknown))

    inventory = process_inventory or _processus_projet
    inspected = inspect_bounded_collectors(
        project_root,
        process_inventory=inventory,
        now=now,
    )
    if not isinstance(inspected, dict) or inspected.get("status") != "ACTIVE":
        status = inspected.get("status") if isinstance(inspected, dict) else "MISSING"
        raise RuntimeError(f"COLLECTOR_ATTACH_REQUIRES_ACTIVE_CAMPAIGN:{status}")

    state_path = project_root / STATE_RELPATH
    lease_file = project_root / LEASE_RELPATH
    try:
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        lease_payload = json.loads(lease_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"COLLECTOR_ATTACH_STATE_UNREADABLE:{type(exc).__name__}") from exc
    token = str(lease_payload.get("token") or "")
    valid, reason, validated = validate_lease(
        lease_file,
        token,
        project_root,
        now=now,
    )
    if not valid or not isinstance(validated, dict):
        raise RuntimeError(f"COLLECTOR_ATTACH_LEASE_INVALID:{reason}")
    expected_lease_id = _mapping_lease_id(persisted.get("lease"))
    if not expected_lease_id or expected_lease_id != str(validated.get("lease_id") or ""):
        raise RuntimeError("COLLECTOR_ATTACH_LEASE_REPLACED")

    active = {
        str(name): int(pid)
        for name, pid in dict(inspected.get("actifs") or {}).items()
        if isinstance(pid, int)
    }
    already_attached = {name: active[name] for name in requested if name in active}
    pending = [campaign_registry[name] for name in requested if name not in active]
    python_executable = resolve_project_python(project_root)
    runner = project_root / "tools" / "run_bounded_collector.py"
    launch = spawner or _default_spawn
    handles: dict[str, ProcessHandle] = {}
    launch_errors: dict[str, str] = {}
    for collector in pending:
        name = str(collector["nom"])
        command = [
            str(python_executable),
            str(runner),
            "--root",
            str(project_root),
            "--name",
            name,
            "--script",
            str(collector["script"]),
            "--interval-s",
            str(float(collector["intervalle_s"])),
            "--lease-file",
            str(lease_file),
            "--",
            *[str(value) for value in collector.get("args", ())],
        ]
        environment = {
            **os.environ,
            "PYTHONPATH": str(project_root / "src"),
            "PYTHONIOENCODING": "utf-8",
            "HYPERSMART_COLLECTOR_LEASE_TOKEN": token,
        }
        try:
            handles[name] = launch(command, project_root, environment)
        except Exception as exc:  # noqa: BLE001 - every startup failure is reported
            launch_errors[name] = f"{type(exc).__name__}: {exc}"
    if handles:
        sleeper(max(0.0, float(startup_wait_s)))

    started: dict[str, int] = {}
    returncodes: dict[str, int] = {}
    for name, handle in handles.items():
        returncode = handle.poll()
        if returncode is None:
            started[name] = int(handle.pid)
        else:
            returncodes[name] = int(returncode)

    old_pids = {
        str(name): int(pid)
        for name, pid in dict(persisted.get("pids") or {}).items()
        if isinstance(pid, int)
    }
    old_started = set(persisted.get("demarres_et_verifies") or [])
    old_requested = list(persisted.get("requested") or [])
    combined_requested = list(dict.fromkeys([*old_requested, *requested]))
    combined_pids = {**old_pids, **started}
    missing = [name for name in combined_requested if name not in combined_pids]
    log_tails = dict(persisted.get("startup_log_tails") or {})
    log_tails.update({
        name: _tail(project_root / "runtime" / "logs" / f"economic-{name}.log")
        for name in started
    })
    state = {
        **persisted,
        "generated_at_ms": int((time.time() if now is None else float(now)) * 1000),
        "requested": combined_requested,
        "selectionnes": len(combined_requested) - len(missing),
        "pids": combined_pids,
        "demarres_et_verifies": sorted(old_started | set(started)),
        "manquants": missing,
        "launch_errors": {**dict(persisted.get("launch_errors") or {}), **launch_errors},
        "early_returncodes": {
            **dict(persisted.get("early_returncodes") or {}),
            **returncodes,
        },
        "startup_wait_s": float(startup_wait_s),
        "python_executable": str(python_executable),
        "lease": public_lease(validated),
        "startup_log_tails": log_tails,
        "last_attachment": {
            "requested": requested,
            "already_attached": sorted(already_attached),
            "started": sorted(started),
            "missing": [name for name in requested if name not in combined_pids],
        },
    }
    _atomic_write(state_path, state)
    return {
        **{key: value for key, value in state.items() if key != "startup_log_tails"},
        "attached_without_lease_replacement": True,
    }


def inspect_bounded_collectors(
    root: str | Path,
    *,
    process_inventory: Callable[[str | Path], list[dict[str, Any]]] | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Read and verify the current collection campaign without restarting it.

    Reports generated with ``--no-start-collection`` must not erase evidence
    that an existing bounded campaign is still alive.  This function verifies
    the persisted safety contract, PID ownership and lease expiry, and never
    exposes the lease bearer token.
    """

    project_root = Path(root).resolve()
    state_path = project_root / STATE_RELPATH
    try:
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "STATE_UNREADABLE",
            "paper_read_only": True,
            "real_execution": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if not isinstance(persisted, dict) or persisted.get("schema_version") != SCHEMA_VERSION:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "STATE_SCHEMA_INVALID",
            "paper_read_only": True,
            "real_execution": False,
        }
    if persisted.get("paper_read_only") is not True or persisted.get("real_execution") is not False:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "STATE_SAFETY_INVALID",
            "paper_read_only": True,
            "real_execution": False,
        }

    inventory = process_inventory or _processus_projet
    live_rows = list(inventory(project_root))
    rows_by_pid = {
        int(row["pid"]): row
        for row in live_rows
        if isinstance(row.get("pid"), int)
    }
    recorded = {
        str(name): int(pid)
        for name, pid in dict(persisted.get("pids") or {}).items()
        if isinstance(pid, int)
    }
    started_names = set(persisted.get("demarres_et_verifies") or [])
    reused_names = set(persisted.get("reutilises") or [])

    def owns_recorded_collector(name: str, pid: int) -> bool:
        row = rows_by_pid.get(pid)
        if row is None:
            return False
        command = str(row.get("cmd") or "").lower()
        if name in started_names:
            return "run_bounded_collector.py" in command and f"--name {name}" in command
        registry = _registry()
        if name in reused_names and name in registry:
            collector = registry[name]
            return _pid_collecteur_existant(collector, [row]) == pid
        return False

    active = {
        name: pid
        for name, pid in recorded.items()
        if owns_recorded_collector(name, pid)
    }
    stopped = sorted(name for name in recorded if name not in active)
    protocols = _active_collector_protocols(project_root, active)

    lease_public = persisted.get("lease") if isinstance(persisted.get("lease"), dict) else None
    lease_required = bool(persisted.get("demarres_et_verifies"))
    lease_valid = not lease_required
    lease_reason = ""
    if lease_required:
        try:
            lease_payload = json.loads(
                (project_root / LEASE_RELPATH).read_text(encoding="utf-8")
            )
            token = str(lease_payload.get("token") or "")
            lease_valid, lease_reason, validated = validate_lease(
                project_root / LEASE_RELPATH,
                token,
                project_root,
                now=now,
            )
            if isinstance(validated, dict):
                current_public = public_lease(validated)
                expected_lease_id = str(_mapping_lease_id(lease_public))
                current_lease_id = str(current_public.get("lease_id") or "")
                if expected_lease_id and expected_lease_id != current_lease_id:
                    lease_valid = False
                    lease_reason = "COLLECTOR_LEASE_REPLACED"
                lease_public = current_public
        except (OSError, ValueError, TypeError) as exc:
            lease_valid = False
            lease_reason = f"COLLECTOR_LEASE_UNREADABLE:{type(exc).__name__}"

    expected = set(recorded)
    status = (
        "ACTIVE"
        if expected and set(active) == expected and lease_valid
        else "INACTIVE"
        if not expected
        else "DEGRADED"
    )
    return {
        **{
            key: value
            for key, value in persisted.items()
            if key not in {"pids", "lease", "startup_log_tails"}
        },
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "pids": recorded,
        "actifs": active,
        "arretes": stopped,
        "protocols": protocols,
        "lease": lease_public,
        "lease_valid": bool(lease_valid),
        "lease_reason": lease_reason,
        "inspected_at_ms": int((time.time() if now is None else float(now)) * 1000),
    }


def _mapping_lease_id(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    return str(value.get("lease_id") or "")


__all__ = [
    "SCHEMA_VERSION",
    "STATE_RELPATH",
    "attach_bounded_collectors",
    "inspect_bounded_collectors",
    "resolve_project_python",
    "start_bounded_collectors",
]
