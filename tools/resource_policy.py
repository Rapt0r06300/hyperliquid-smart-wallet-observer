"""Politique de ressources Windows pour les processus HyperSmart.

Le calcul ne s'arrete jamais et n'est jamais place en priorite ``Idle``. Tous
les processus HyperSmart utilisent ``BelowNormal``. Quand Salad est actif, les
lots et le nombre de workers diminuent; aucune pause n'est injectee dans le
travail.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import threading
import time
from typing import Iterable

SALAD_PROCESS_NAMES = {
    "salad.exe",
    "salad.bowl.service.exe",
    "salad.bootstrapper.exe",
}
HYPERSMART_COMMAND_MARKERS = (
    "hl_observer",
    "hypersmart",
    "recherche_continue.py",
    "collecter_lab_",
    "resource_policy.py",
)


def _normaliser_nom(value: object) -> str:
    return str(value or "").strip().lower()


def salad_running(process_names: Iterable[str] | None = None) -> bool:
    """Indique si Salad tourne, sans modifier ni inspecter ses ressources."""
    if process_names is not None:
        return any(
            _normaliser_nom(name) in SALAD_PROCESS_NAMES
            or _normaliser_nom(name).startswith("salad")
            for name in process_names
        )
    try:
        import psutil  # type: ignore

        for process in psutil.process_iter(["name"]):
            try:
                name = _normaliser_nom(process.info.get("name"))
                if name in SALAD_PROCESS_NAMES or name.startswith("salad"):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:  # noqa: BLE001
        return False
    return False


def effective_policy(*, salad_active: bool | None = None) -> dict:
    """Politique effective.

    ``BelowNormal`` est invariant. La presence de Salad ne change que les
    plafonds de concurrence et la taille des lots disque.
    """
    active = salad_running() if salad_active is None else bool(salad_active)
    return {
        "salad_active": active,
        "priority": "BELOW_NORMAL",
        "never_idle": True,
        "pause_workload": False,
        "max_cpu_percent": 25.0 if active else 45.0,
        "max_ram_gb": 5.0 if active else 8.0,
        "max_workers": 1 if active else 2,
        "max_sources_per_bootstrap": 64 if active else 256,
        "max_bootstrap_megabytes": 128 if active else 512,
        "dashboard_refresh_ms": 1000,
        "guardian_interval_s": 15.0,
    }


def apply_environment_caps(*, salad_active: bool | None = None) -> dict:
    """Pose des plafonds conservateurs pour le processus et ses futurs enfants."""
    policy = effective_policy(salad_active=salad_active)
    values = {
        "HYPERSMART_18H_MAX_CPU_PERCENT": policy["max_cpu_percent"],
        "HYPERSMART_18H_MAX_RAM_GB": policy["max_ram_gb"],
        "HYPERSMART_18H_MAX_WORKERS": policy["max_workers"],
        "HYPERSMART_18H_MAX_SOURCES_PER_BOOTSTRAP": policy["max_sources_per_bootstrap"],
        "HYPERSMART_18H_MAX_BOOTSTRAP_MEGABYTES": policy["max_bootstrap_megabytes"],
        "HYPERSMART_DASHBOARD_REFRESH_MS": policy["dashboard_refresh_ms"],
        "HYPERSMART_RESOURCE_PRIORITY": policy["priority"],
        "HYPERSMART_RESOURCE_NEVER_IDLE": "1",
        "HYPERSMART_SALAD_ACTIVE": "1" if policy["salad_active"] else "0",
    }
    for key, value in values.items():
        os.environ[key] = str(value)
    return policy


def _set_below_normal(process, *, salad_active: bool | None = None) -> bool:
    """Applique BelowNormal, une E/S basse et une affinité CPU adaptative.

    L'affinité est le seul ralentissement dynamique : aucun processus n'est
    suspendu et la classe ``Idle`` n'est jamais utilisée.
    """
    try:
        import psutil  # type: ignore

        process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        try:
            process.ionice(psutil.IOPRIO_LOW)
        except (AttributeError, OSError, psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        try:
            total = max(1, int(psutil.cpu_count(logical=True) or 1))
            if bool(salad_active):
                usable = max(1, total // 4)
                target = list(range(usable))
            else:
                target = list(range(total))
            process.cpu_affinity(target)
        except (AttributeError, OSError, ValueError, psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


def apply_process_tree_priority(pid: int | None = None) -> dict:
    """Place le processus cible et ses enfants en BelowNormal, jamais en Idle."""
    active = salad_running()
    try:
        import psutil  # type: ignore

        root = psutil.Process(int(pid or os.getpid()))
        processes = [root, *root.children(recursive=True)]
    except Exception as exc:  # noqa: BLE001
        return {"changed": 0, "errors": 1, "error": str(exc)[:160], "priority": "BELOW_NORMAL"}
    changed = errors = 0
    for process in processes:
        if _set_below_normal(process, salad_active=active):
            changed += 1
        else:
            errors += 1
    return {
        "changed": changed,
        "errors": errors,
        "priority": "BELOW_NORMAL",
        "never_idle": True,
        "salad_active": active,
    }


def _est_dans_projet(path: object, root: Path) -> bool:
    try:
        Path(str(path)).resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _is_hypersmart_process(
    command_line: str,
    *,
    root: Path | None,
    cwd: object = None,
) -> bool:
    text = str(command_line or "").lower()
    if not any(marker in text for marker in HYPERSMART_COMMAND_MARKERS):
        return False
    if root is None:
        return True
    return str(root).lower() in text or _est_dans_projet(cwd, root)


def enforce_matching_processes(root: str | Path | None = None) -> dict:
    """Applique BelowNormal uniquement aux processus HyperSmart du projet."""
    project_root = Path(root).resolve() if root else None
    changed = errors = matched = 0
    active = salad_running()
    try:
        import psutil  # type: ignore

        for process in psutil.process_iter(["pid", "cmdline", "cwd"]):
            try:
                if int(process.info["pid"]) == os.getpid():
                    continue
                command_line = " ".join(process.info.get("cmdline") or [])
                if not _is_hypersmart_process(
                    command_line,
                    root=project_root,
                    cwd=process.info.get("cwd"),
                ):
                    continue
                matched += 1
                if _set_below_normal(process, salad_active=active):
                    changed += 1
                else:
                    errors += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                errors += 1
    except Exception as exc:  # noqa: BLE001
        return {"matched": matched, "changed": changed, "errors": errors + 1, "error": str(exc)[:160]}
    return {
        "matched": matched,
        "changed": changed,
        "errors": errors,
        "priority": "BELOW_NORMAL",
        "never_idle": True,
        "salad_active": active,
    }


def start_guardian(
    *,
    stop_event: threading.Event | None = None,
    root: str | Path | None = None,
    interval_s: float = 15.0,
) -> threading.Thread:
    """Maintient les priorites sans suspendre le moteur."""
    event = stop_event or threading.Event()

    def loop() -> None:
        previous_salad = None
        while not event.is_set():
            active = salad_running()
            if active != previous_salad:
                apply_environment_caps(salad_active=active)
                previous_salad = active
            apply_process_tree_priority()
            if root is not None:
                enforce_matching_processes(root)
            event.wait(max(5.0, float(interval_s)))

    thread = threading.Thread(target=loop, name="hypersmart-resource-guardian", daemon=True)
    thread.start()
    return thread


def subprocess_creation_flags(base_flags: int = 0) -> int:
    """Drapeaux Windows pour lancer un enfant directement en BelowNormal."""
    if os.name != "nt":
        return int(base_flags)
    import subprocess

    return int(base_flags) | int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))


def _watch(root: Path, interval_s: float) -> int:
    apply_environment_caps()
    apply_process_tree_priority()
    while True:
        enforce_matching_processes(root)
        time.sleep(max(5.0, interval_s))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HyperSmart low-resource priority guardian")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    policy = apply_environment_caps()
    apply_process_tree_priority()
    if args.status:
        print(policy)
        return 0
    if args.watch:
        return _watch(Path(args.root).resolve(), args.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "apply_environment_caps",
    "apply_process_tree_priority",
    "effective_policy",
    "enforce_matching_processes",
    "salad_running",
    "start_guardian",
    "subprocess_creation_flags",
]
