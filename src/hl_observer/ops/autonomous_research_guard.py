from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from pathlib import Path

from hl_observer.ops.autonomous_completion import (
    COMPLETION_EXIT_CODE,
    REGISTRY_EXIT_CODE,
    AutonomousCompletionError,
    finalize_autonomous_completion,
)
from hl_observer.ops.autonomous_research_status import status_path, write_status

LOGGER = logging.getLogger(__name__)
MAX_ALLOWED_SECONDS = 18 * 60 * 60
POLL_SECONDS = 0.2
WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
POSIX_SIGTERM = getattr(signal, "SIGTERM", 15)
POSIX_SIGKILL = getattr(signal, "SIGKILL", 9)


def _request_identity(request: Path) -> tuple[str, str | None, str | None]:
    job_id = request.stem
    suite: str | None = None
    mode: str | None = None
    try:
        raw = json.loads(request.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            if raw.get("job_id"):
                job_id = str(raw["job_id"])
            if raw.get("suite"):
                suite = str(raw["suite"])
            if raw.get("mode"):
                mode = str(raw["mode"])
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "Impossible de lire l'identité du job %s (%s); le nom de fichier est conservé.",
            request,
            type(exc).__name__,
        )
    return job_id, suite, mode


def _write_timeout_report(result_dir: Path, *, request: Path, max_seconds: int, elapsed: float) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    job_id, _, _ = _request_identity(request)
    payload = {
        "schema": "alina.autonomous_research_guard.v3",
        "job_id": job_id,
        "status": "TIMEBOX_REACHED",
        "max_seconds": max_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "resume_expected": True,
        "process_tree_stopped": True,
        "stdout_nonblocking_watchdog": True,
        "paper_only": True,
        "real_execution": False,
        "message": "Le cycle a atteint sa timebox. Tout son arbre de processus est arrêté avant une reprise depuis les checkpoints persistants.",
    }
    (result_dir / "JOB_GUARD_TIMEOUT.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (result_dir / "JOB_GUARD_TIMEOUT.md").write_text(
        "# Alina SmartFlow — cycle autonome interrompu proprement\n\n"
        f"- Job : `{job_id}`\n"
        "- Statut : **TIMEBOX_REACHED**\n"
        f"- Limite du cycle : **{max_seconds} s**\n"
        f"- Durée observée : **{elapsed:.1f} s**\n"
        "- Arbre de processus arrêté : **OUI**\n"
        "- Watchdog indépendant de stdout : **OUI**\n"
        "- Reprise attendue : **OUI**\n"
        "- Exécution réelle : **NON**\n\n"
        "Le prochain cycle peut réutiliser le cache, les workspaces et les checkpoints persistants.\n",
        encoding="utf-8",
    )


def _write_timeout_live_status(lab_root: Path, *, request: Path, elapsed: float) -> None:
    """Remplace immédiatement un éventuel RUNNING devenu obsolète après la timebox globale."""

    job_id, suite, mode = _request_identity(request)
    write_status(
        status_path(lab_root),
        job_id=job_id,
        suite=suite,
        mode=mode,
        state="TIMEBOX_REACHED",
        action_fr="Cycle arrêté proprement après 18 h maximum",
        message_fr=(
            "La limite de ce cycle est atteinte. Tous les processus de calcul ont été arrêtés; "
            "le cache et les checkpoints restent sur le PC pour la reprise automatique."
        ),
        job_started_unix=max(0.0, time.time() - float(elapsed)),
        next_action_fr="Synchroniser ce cycle sur GitHub puis reprendre depuis les checkpoints",
        extra={
            "resume_expected": True,
            "process_tree_stopped": True,
        },
    )


def _popen_process_group_kwargs(platform_name: str | None = None) -> dict[str, object]:
    """Construit l'isolation du processus sans jamais muter ``os.name`` dans les tests."""

    name = os.name if platform_name is None else str(platform_name)
    if name == "nt":
        flag = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", WINDOWS_CREATE_NEW_PROCESS_GROUP))
        return {"creationflags": flag}
    return {"start_new_session": True}


def _terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float = 30.0,
    platform_name: str | None = None,
) -> None:
    if process.poll() is not None:
        return
    name = os.name if platform_name is None else str(platform_name)
    if name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            LOGGER.warning("taskkill n'a pas arrêté tout l'arbre PID=%s; kill() de secours.", process.pid)
            process.kill()
            process.wait()
        return

    try:
        os.killpg(process.pid, POSIX_SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        LOGGER.warning("SIGTERM insuffisant pour PGID=%s; passage à SIGKILL.", process.pid)
    try:
        os.killpg(process.pid, POSIX_SIGKILL)
    except ProcessLookupError:
        LOGGER.info("Le groupe de processus %s a disparu avant SIGKILL.", process.pid)
    process.wait()


def _start_stdout_pump(process: subprocess.Popen[str]) -> threading.Thread:
    """Vide stdout dans un thread pour que le watchdog ne bloque jamais sur readline()."""

    def pump() -> None:
        stream = process.stdout
        if stream is None:
            return
        try:
            for line in stream:
                print(line, end="", flush=True)
        except (OSError, ValueError):
            return

    thread = threading.Thread(
        target=pump,
        name=f"alina-stdout-{getattr(process, 'pid', 'process')}",
        daemon=True,
    )
    thread.start()
    return thread


def _finalize_success(
    *,
    request: Path,
    project_root: Path,
    lab_root: Path,
    result_dir: Path,
) -> int:
    """Turn a technical worker success into a fail-closed autonomous completion."""

    try:
        contract = finalize_autonomous_completion(
            request_path=request,
            project_root=project_root,
            lab_root=lab_root,
            result_dir=result_dir,
        )
    except AutonomousCompletionError as exc:
        print(f"ALINA_COMPLETION_NO_GO: {exc}", flush=True)
        result_path = result_dir / "JOB_RESULT.json"
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result = {}
        try:
            code = int(result.get("exit_code") or COMPLETION_EXIT_CODE)
        except (TypeError, ValueError):
            code = COMPLETION_EXIT_CODE
        return code if code in {COMPLETION_EXIT_CODE, REGISTRY_EXIT_CODE} else COMPLETION_EXIT_CODE

    if contract.get("analysis_complete") is True:
        print(
            "ALINA_COMPLETION_OK "
            f"suite={contract.get('suite')} registry={contract.get('completion_registry_path')}",
            flush=True,
        )
    else:
        print("ALINA_PREPARE_ONLY_OK: aucune suite enregistrée comme analysée.", flush=True)
    return 0


def run_guarded(
    command: list[str],
    *,
    max_seconds: int,
    result_dir: Path,
    request: Path,
    lab_root: Path | None = None,
    project_root: Path | None = None,
) -> int:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **_popen_process_group_kwargs(),
    )
    pump = _start_stdout_pump(process)
    timed_out = False
    try:
        while process.poll() is None:
            if time.monotonic() - started >= max_seconds:
                timed_out = True
                _terminate_process_tree(process)
                break
            time.sleep(POLL_SECONDS)
        if process.poll() is None:
            process.wait()
    finally:
        if process.poll() is None:
            _terminate_process_tree(process)
        pump.join(timeout=5)
    elapsed = time.monotonic() - started
    if timed_out:
        _write_timeout_report(result_dir, request=request, max_seconds=max_seconds, elapsed=elapsed)
        if lab_root is not None:
            _write_timeout_live_status(lab_root, request=request, elapsed=elapsed)
        print(f"ALINA_RESEARCH_TIMEBOX_REACHED elapsed={elapsed:.1f}s", flush=True)
        return 124

    worker_code = int(process.returncode or 0)
    if worker_code != 0:
        return worker_code
    if lab_root is None or project_root is None:
        # Kept for low-level tests/callers; the production CLI always supplies both.
        return 0
    return _finalize_success(
        request=request,
        project_root=project_root,
        lab_root=lab_root,
        result_dir=result_dir,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Timebox un cycle du laboratoire autonome avant expiration du token GitHub.")
    parser.add_argument("--request", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--lab-root", required=True)
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--max-seconds", type=int, default=MAX_ALLOWED_SECONDS)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    max_seconds = int(args.max_seconds)
    if max_seconds < 60 or max_seconds > MAX_ALLOWED_SECONDS:
        print(f"ALINA_RESEARCH_GUARD_NO_GO: max-seconds doit être entre 60 et {MAX_ALLOWED_SECONDS}.")
        return 2
    lab_root = Path(args.lab_root).resolve()
    project_root = Path(args.project_root).resolve()
    request = Path(args.request).resolve()
    result_dir = Path(args.result_dir).resolve()
    command = [
        sys.executable,
        "-m",
        "hl_observer.ops.autonomous_research_job_router",
        "--request",
        str(request),
        "--project-root",
        str(project_root),
        "--lab-root",
        str(lab_root),
        "--result-dir",
        str(result_dir),
    ]
    if args.force:
        command.append("--force")
    return run_guarded(
        command,
        max_seconds=max_seconds,
        result_dir=result_dir,
        request=request,
        lab_root=lab_root,
        project_root=project_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
