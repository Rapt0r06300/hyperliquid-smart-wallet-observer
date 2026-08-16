from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterable

MAX_ALLOWED_SECONDS = 18 * 60 * 60
POLL_SECONDS = 0.2
WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200


def _write_timeout_report(result_dir: Path, *, request: Path, max_seconds: int, elapsed: float) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    job_id = request.stem
    try:
        raw = json.loads(request.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("job_id"):
            job_id = str(raw["job_id"])
    except (OSError, json.JSONDecodeError):
        pass
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


def _popen_process_group_kwargs(platform_name: str | None = None) -> dict[str, object]:
    """Construit l'isolation du processus sans jamais muter ``os.name`` dans les tests."""

    name = os.name if platform_name is None else str(platform_name)
    if name == "nt":
        # subprocess.CREATE_NEW_PROCESS_GROUP n'existe que sur Windows.
        # Le fallback 0x200 est la valeur Win32 officielle et permet de tester
        # la branche Windows depuis la CI Linux sans modifier l'état global.
        flag = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", WINDOWS_CREATE_NEW_PROCESS_GROUP))
        return {"creationflags": flag}
    return {"start_new_session": True}


def _terminate_process_tree(process: subprocess.Popen[str], *, grace_seconds: float = 30.0) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # taskkill /T est nécessaire : terminer seulement le parent Python peut
        # laisser un backtest enfant actif sur le workspace persistant.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
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
            # La fermeture du pipe pendant taskkill/killpg est normale.
            return

    thread = threading.Thread(
        target=pump,
        name=f"alina-stdout-{getattr(process, 'pid', 'process')}",
        daemon=True,
    )
    thread.start()
    return thread


def run_guarded(command: list[str], *, max_seconds: int, result_dir: Path, request: Path) -> int:
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
        print(f"ALINA_RESEARCH_TIMEBOX_REACHED elapsed={elapsed:.1f}s", flush=True)
        return 124
    return int(process.returncode or 0)


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
    command = [
        sys.executable,
        "-m",
        "hl_observer.ops.autonomous_research_job",
        "--request",
        str(Path(args.request).resolve()),
        "--project-root",
        str(Path(args.project_root).resolve()),
        "--lab-root",
        str(Path(args.lab_root).resolve()),
        "--result-dir",
        str(Path(args.result_dir).resolve()),
    ]
    if args.force:
        command.append("--force")
    return run_guarded(
        command,
        max_seconds=max_seconds,
        result_dir=Path(args.result_dir).resolve(),
        request=Path(args.request).resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
