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

from .collecteur_registry import REGISTRE
from .collector_lease import create_lease, public_lease
from .superviseur_collecteurs import _pid_collecteur_existant, _processus_projet


SCHEMA_VERSION = "hypersmart.bounded_collection_start.v1"
STATE_RELPATH = Path("runtime") / "data" / "economic_collection_pids.json"


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...


Spawner = Callable[[list[str], Path, Mapping[str, str]], ProcessHandle]


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
    registry = {str(row["nom"]): row for row in REGISTRE}
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


__all__ = [
    "SCHEMA_VERSION",
    "STATE_RELPATH",
    "resolve_project_python",
    "start_bounded_collectors",
]
