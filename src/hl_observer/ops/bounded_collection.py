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

from .echec_silencieux import noter as _noter_echec
from .collecteur_registry import COLLECTEURS_CAMPAGNE, REGISTRE
from .collector_lease import DEFAULT_RELPATH as LEASE_RELPATH
from .collector_lease import create_lease, public_lease, validate_lease
from .superviseur_collecteurs import _pid_collecteur_existant, _processus_projet

# EXTRAIT LE 21/11/2026 vers bounded_collection_primitives (invariant #13 : un fichier > son plafond
# devient intouchable). Les definitions ont ete DEPLACEES, pas dupliquees ; cet
# import les relie au meme endroit pour tous les appelants existants.
from .bounded_collection_primitives import (  # noqa: F401
    _atomic_write,
    resolve_project_python,
    _bounded_process_ids,
    _active_collector_protocols,
)

SCHEMA_VERSION = "hypersmart.bounded_collection_start.v1"
STATE_RELPATH = Path("runtime") / "data" / "economic_collection_pids.json"


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...


Spawner = Callable[[list[str], Path, Mapping[str, str]], ProcessHandle]

_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_IDLE_PRIORITY_CLASS = 0x00000040


def _registry(*, campaign_only: bool = False) -> dict[str, dict[str, Any]]:
    rows = COLLECTEURS_CAMPAGNE if campaign_only else REGISTRE + COLLECTEURS_CAMPAGNE
    return {str(row["nom"]): row for row in rows}


_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

#: Part des coeurs logiques reservee aux collecteurs. L operateur a autorise 60 % le
#: 19/11/2026. Mettre 0 (ou une valeur hors ]0, 1]) desactive toute affinite et rend
#: le comportement d avant : priorite IDLE, tous les coeurs, cede des qu une
#: application normale demande le processeur.
FRACTION_COEURS_DEFAUT = 0.6
VAR_FRACTION_COEURS = "HL_COLLECTEURS_FRACTION_COEURS"


def fraction_coeurs(environnement: Mapping[str, str] | None = None) -> float:
    """Fraction des coeurs reservee aux collecteurs, bornee a ]0, 1]."""
    brut = (environnement or os.environ).get(VAR_FRACTION_COEURS, "")
    try:
        valeur = float(str(brut).strip().replace(",", ".")) if str(brut).strip() else FRACTION_COEURS_DEFAUT
    except ValueError:
        return FRACTION_COEURS_DEFAUT
    return valeur if 0.0 < valeur <= 1.0 else 0.0


def coeurs_autorises(*, total: int | None = None,
                     environnement: Mapping[str, str] | None = None) -> tuple[int, ...]:
    """Les coeurs logiques reserves aux collecteurs, ou () si aucune affinite.

    POURQUOI UNE AFFINITE ET PAS SEULEMENT UNE PRIORITE. La priorite IDLE laisse les
    collecteurs prendre TOUS les coeurs quand la machine est libre, mais les affame des
    que l operateur travaille : leur debit s ecroule au pire moment. Reserver une PART
    des coeurs donne les deux garanties a la fois -- ils travaillent vraiment sur leur
    part, et ne touchent JAMAIS le reste, donc la machine reste reactive.

    On prend les coeurs du HAUT : les premiers portent par convention les threads
    systeme et l interface, ceux que l operateur sent en premier.
    """
    fraction = fraction_coeurs(environnement)
    if fraction <= 0.0:
        return ()
    n_total = int(total if total is not None else (os.cpu_count() or 1))
    if n_total <= 1:
        return ()
    n = max(1, min(n_total, int(n_total * fraction)))
    if n >= n_total:
        return ()   # rien a reserver : tout est deja autorise
    return tuple(range(n_total - n, n_total))


def appliquer_budget_cpu(processus: Any, *, psutil_mod: Any = None,
                         environnement: Mapping[str, str] | None = None,
                         total_coeurs: int | None = None) -> dict[str, Any]:
    """Reserve la part de coeurs au processus, et ne releve sa priorite QUE si ca a marche.

    FAIL-SAFE : sans affinite (psutil absent, plateforme sans affinite, droits refuses),
    on GARDE la priorite IDLE. Relever la priorite sans avoir borne les coeurs rendrait
    la machine moins reactive -- exactement ce que l operateur ne demande pas.
    """
    audit: dict[str, Any] = {"coeurs": [], "priorite": "IDLE", "raison": ""}
    coeurs = coeurs_autorises(total=total_coeurs, environnement=environnement)
    if not coeurs:
        audit["raison"] = "aucune affinite demandee"
        return audit
    if psutil_mod is None:
        try:
            import psutil as psutil_mod   # type: ignore[no-redef]
        except ImportError:
            audit["raison"] = "psutil absent"
            return audit
    pid = getattr(processus, "pid", None)
    if not pid:
        audit["raison"] = "processus sans pid"
        return audit
    try:
        poignee = psutil_mod.Process(int(pid))
        poignee.cpu_affinity(list(coeurs))
    except Exception as exc:                      # noqa: BLE001 - jamais fatal au lancement
        audit["raison"] = "affinite refusee: %s" % type(exc).__name__
        return audit
    audit["coeurs"] = list(coeurs)
    try:
        poignee.nice(getattr(psutil_mod, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        audit["priorite"] = "BELOW_NORMAL"
    except Exception as exc:                      # noqa: BLE001
        audit["raison"] = "priorite inchangee: %s" % type(exc).__name__
    return audit

def _background_creation_flags(platform_name: str = os.name) -> int:
    if platform_name != "nt":
        return 0
    # The campaign may run for days beside user workloads such as Salad. Idle
    # priority still consumes every otherwise-free CPU cycle, but yields as
    # soon as normal-priority applications need the processor. Child collector
    # workers inherit the class from their bounded wrapper.
    return (
        _CREATE_NO_WINDOW
        | _CREATE_NEW_PROCESS_GROUP
        | _CREATE_BREAKAWAY_FROM_JOB
        | _IDLE_PRIORITY_CLASS
    )


def _default_spawn(
    command: list[str], root: Path, environment: Mapping[str, str]
) -> ProcessHandle:
    flags = _background_creation_flags()
    kwargs = {
        "cwd": str(root),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": dict(environment),
    }
    try:
        processus = subprocess.Popen(  # noqa: S603 - fixed local runner and registry scripts
            command,
            creationflags=flags,
            **kwargs,
        )
    except OSError as exc:
        # Some locked-down Windows jobs forbid explicit breakaway. Collection
        # can still run in the caller's job, so retry with the previous safe
        # no-window/process-group contract instead of failing startup.
        if os.name != "nt" or getattr(exc, "winerror", None) not in {5, 87}:
            raise
        processus = subprocess.Popen(  # noqa: S603 - same fixed local command
            command,
            creationflags=flags & ~_CREATE_BREAKAWAY_FROM_JOB,
            **kwargs,
        )
    # Budget CPU de l operateur (60 % des coeurs par defaut) applique APRES le lancement :
    # creationflags ne sait pas poser une affinite. Jamais fatal -- si ca echoue, le
    # processus reste en IDLE sur tous les coeurs, c est-a-dire le comportement d avant.
    appliquer_budget_cpu(processus)
    return processus


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
    return {
        **state,
        "protocols": _active_collector_protocols(
            project_root,
            state["pids"],
            processes=inventory(project_root),
        ),
    }


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
    """Attach missing registered collectors to the current lease without replacing it.

    This path also repairs one failed normal collector while its siblings keep
    collecting. It fails closed unless the persisted bearer lease is valid and
    at least one recorded process is still owned. The lease ID and expiry are
    preserved byte-for-byte.
    """

    project_root = Path(root).resolve()
    requested = list(dict.fromkeys(str(name) for name in names))
    registry = _registry()
    unknown = [name for name in requested if name not in registry]
    if unknown:
        raise ValueError(f"collector unknown: {','.join(unknown)}")

    inventory = process_inventory or _processus_projet
    inspected = inspect_bounded_collectors(
        project_root,
        process_inventory=inventory,
        now=now,
    )
    if (
        not isinstance(inspected, dict)
        or inspected.get("status") not in {"ACTIVE", "DEGRADED"}
        or inspected.get("lease_valid") is not True
        or not inspected.get("actifs")
    ):
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
    pending = [registry[name] for name in requested if name not in active]
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

    old_started = set(persisted.get("demarres_et_verifies") or [])
    old_requested = list(persisted.get("requested") or [])
    combined_requested = list(dict.fromkeys([*old_requested, *requested]))
    combined_pids = {**active, **started}
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
    active_protocols = _active_collector_protocols(
        project_root,
        combined_pids,
        processes=inventory(project_root),
        now=now,
    )
    return {
        **{key: value for key, value in state.items() if key != "startup_log_tails"},
        "status": "ACTIVE" if not missing else "DEGRADED",
        "actifs": combined_pids,
        "arretes": [],
        "lease_valid": True,
        "lease_reason": "OK",
        "protocols": active_protocols,
        "attached_without_lease_replacement": True,
    }


def ensure_bounded_collectors(
    root: str | Path,
    names: Iterable[str],
    *,
    duration_s: float = 24 * 60 * 60,
    startup_wait_s: float = 3.0,
    process_inventory: Callable[[str | Path], list[dict[str, Any]]] | None = None,
    spawner: Spawner | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    now: float | None = None,
) -> dict[str, Any]:
    """Ensure requested collectors while never replacing a surviving campaign.

    Any missing registered collector is attached under the active lease. A new
    lease is issued only when no verified campaign process survives or the old
    lease is invalid.
    """

    project_root = Path(root).resolve()
    requested = list(dict.fromkeys(str(name) for name in names))
    current = inspect_bounded_collectors(
        project_root,
        process_inventory=process_inventory,
        now=now,
    )
    if (
        not isinstance(current, dict)
        or current.get("lease_valid") is not True
        or not current.get("actifs")
    ):
        return start_bounded_collectors(
            project_root,
            requested,
            duration_s=duration_s,
            startup_wait_s=startup_wait_s,
            process_inventory=process_inventory,
            spawner=spawner,
            sleeper=sleeper,
        )

    active = set(_mapping_keys(current.get("actifs")))
    missing = [name for name in requested if name not in active]
    if missing:
        current = attach_bounded_collectors(
            project_root,
            missing,
            startup_wait_s=startup_wait_s,
            process_inventory=process_inventory,
            spawner=spawner,
            sleeper=sleeper,
            now=now,
        )
    return current


def _mapping_keys(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(str(key) for key in value)


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
    protocols = _active_collector_protocols(
        project_root, active, processes=live_rows, now=now
    )

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


def renew_bounded_collection_lease(
    root: str | Path,
    lease_id: str,
    *,
    duration_s: float,
    now: float | None = None,
) -> dict[str, Any]:
    """Extend only the currently recorded campaign lease, without changing its identity.

    A short TTL lets the watchdog keep collectors alive while it is present and
    makes them stop automatically shortly after the watchdog is closed.
    """

    project_root = Path(root).resolve()
    state_path = project_root / STATE_RELPATH
    lease_path = project_root / LEASE_RELPATH
    try:
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        current = json.loads(lease_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {"renewed": False, "reason": f"LEASE_STATE_UNREADABLE:{type(exc).__name__}"}

    expected_id = str(lease_id or "").strip()
    persisted_lease = persisted.get("lease") if isinstance(persisted, dict) else None
    persisted_id = _mapping_lease_id(persisted_lease)
    if not expected_id or persisted_id != expected_id:
        return {"renewed": False, "reason": "LEASE_STATE_ID_MISMATCH"}
    if not isinstance(current, dict) or str(current.get("lease_id") or "") != expected_id:
        return {"renewed": False, "reason": "LEASE_REPLACED"}

    token = str(current.get("token") or "")
    valid, reason, validated = validate_lease(
        lease_path,
        token,
        project_root,
        now=now,
    )
    if not valid or not isinstance(validated, dict):
        return {"renewed": False, "reason": reason or "LEASE_INVALID"}

    try:
        ttl = float(duration_s)
    except (TypeError, ValueError, OverflowError):
        return {"renewed": False, "reason": "LEASE_TTL_INVALID"}
    if not 30.0 <= ttl <= 7 * 24 * 60 * 60:
        return {"renewed": False, "reason": "LEASE_TTL_OUT_OF_RANGE"}

    issued_s = time.time() if now is None else float(now)
    updated = dict(validated)
    updated["expires_at_ms"] = int((issued_s + ttl) * 1000)
    _atomic_write(lease_path, updated)
    return {"renewed": True, "lease": public_lease(updated), "reason": "OK"}


def _mapping_lease_id(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    return str(value.get("lease_id") or "")


__all__ = [
    "SCHEMA_VERSION",
    "STATE_RELPATH",
    "attach_bounded_collectors",
    "ensure_bounded_collectors",
    "inspect_bounded_collectors",
    "renew_bounded_collection_lease",
    "resolve_project_python",
    "start_bounded_collectors",
]
