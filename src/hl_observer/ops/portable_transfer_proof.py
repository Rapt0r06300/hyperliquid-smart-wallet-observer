"""PC A -> PC B acceptance proof for a complete HyperSmart clone.

The command is intentionally fail-closed.  It cannot mark a clone portable on
the source computer and it requires a full manifest hash verification before
running any target-side smoke or collection command.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Sequence

from hl_observer.ops.portable_clone import machine_fingerprint, verify_clone

REPORT_RELATIVE = Path("runtime") / "reports" / "portability" / "PORTABLE_PC_A_TO_PC_B_PROOF.json"


def _run(command: Sequence[str], *, cwd: Path, timeout: int, env: dict[str, str]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command), cwd=str(cwd), env=env, check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "command": list(command),
            "stdout_tail": (completed.stdout or "")[-4000:],
            "stderr_tail": (completed.stderr or "")[-4000:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False, "returncode": -1, "duration_seconds": round(time.monotonic() - started, 3),
            "command": list(command), "stdout_tail": "", "stderr_tail": str(exc),
        }


def _latest_complete_session(root: Path, *, not_before: float) -> dict[str, Any]:
    candidates: list[tuple[int, Path, dict[str, Any]]] = []
    for catalog in (root / "runtime" / "data" / "sessions").glob("*/DATA_CATALOG.json"):
        try:
            payload = json.loads(catalog.read_text(encoding="utf-8-sig"))
            if str(payload.get("statut") or payload.get("status") or "").upper() != "COMPLETE":
                continue
            modified_ns = catalog.stat().st_mtime_ns
            if modified_ns < int(not_before * 1_000_000_000):
                continue
            candidates.append((modified_ns, catalog, payload))
        except (OSError, json.JSONDecodeError):
            continue
    if not candidates:
        return {"ok": False, "reason": "no_fresh_complete_session"}
    _mtime, catalog, payload = max(candidates, key=lambda row: row[0])
    return {
        "ok": True,
        "catalog": str(catalog),
        "run_id": str(payload.get("run_id") or catalog.parent.name),
        "status": "COMPLETE",
    }


def _health_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return int(getattr(response, "status", 200)) == 200
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _collect_and_stop(root: Path, collection_seconds: int, env: dict[str, str]) -> dict[str, Any]:
    """Run the real launcher, observe a live UI, then send Q for a clean stop."""
    report_dir = root / "runtime" / "reports" / "portability"
    report_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = report_dir / "pc_b_collection_stdout.log"
    stderr_path = report_dir / "pc_b_collection_stderr.log"
    command = ["cmd.exe", "/d", "/c", str(root / "LANCER_HYPERSMART.cmd")]
    started_wall = time.time()
    started = time.monotonic()
    process: subprocess.Popen[str] | None = None
    health_samples = 0
    health_successes = 0
    try:
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, stderr_path.open(
            "w", encoding="utf-8", errors="replace"
        ) as stderr:
            process = subprocess.Popen(
                command,
                cwd=str(root),
                env={**env, "HYPERSMART_NO_PAUSE": "1"},
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            health_url = "http://127.0.0.1:8794/api/simulation/status"
            startup_deadline = time.monotonic() + 300
            while time.monotonic() < startup_deadline:
                if process.poll() is not None:
                    return {
                        "ok": False,
                        "returncode": process.returncode,
                        "reason": "launcher_exited_before_health",
                        "command": command,
                        "stdout_log": str(stdout_path),
                        "stderr_log": str(stderr_path),
                    }
                if _health_ok(health_url):
                    break
                time.sleep(2)
            else:
                return {
                    "ok": False,
                    "returncode": -1,
                    "reason": "ui_health_timeout",
                    "command": command,
                    "stdout_log": str(stdout_path),
                    "stderr_log": str(stderr_path),
                }

            collection_started = time.monotonic()
            next_health = collection_started
            while time.monotonic() - collection_started < collection_seconds:
                if process.poll() is not None:
                    return {
                        "ok": False,
                        "returncode": process.returncode,
                        "reason": "launcher_exited_during_collection",
                        "observed_seconds": round(time.monotonic() - collection_started, 3),
                        "command": command,
                        "stdout_log": str(stdout_path),
                        "stderr_log": str(stderr_path),
                    }
                now = time.monotonic()
                if now >= next_health:
                    health_samples += 1
                    health_successes += int(_health_ok(health_url))
                    next_health = now + 5
                time.sleep(min(1.0, max(0.05, collection_seconds - (now - collection_started))))

            if process.stdin is None:
                raise RuntimeError("launcher_stdin_unavailable")
            process.stdin.write("Q\n")
            process.stdin.flush()
            process.stdin.close()
            returncode = process.wait(timeout=300)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        if process is not None and process.poll() is None:
            # This terminates only the child command created by this proof.  The
            # normal launcher stop path remains the authoritative cleanup path.
            subprocess.run(
                ["cmd.exe", "/d", "/c", str(root / "LANCER_HYPERSMART.cmd"), "stop"],
                cwd=str(root), env=env, check=False, timeout=300,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.terminate()
        return {
            "ok": False,
            "returncode": -1,
            "reason": f"collection_exception:{exc}",
            "command": command,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
        }

    session = _latest_complete_session(root, not_before=started_wall)
    health_ratio = health_successes / max(1, health_samples)
    ok = returncode == 0 and health_samples > 0 and health_ratio >= 0.95 and session.get("ok") is True
    return {
        "ok": ok,
        "returncode": returncode,
        "reason": "collection_and_clean_stop_verified" if ok else "collection_or_session_verification_failed",
        "duration_seconds": round(time.monotonic() - started, 3),
        "collection_seconds": int(collection_seconds),
        "health_samples": health_samples,
        "health_successes": health_successes,
        "health_ratio": round(health_ratio, 4),
        "session": session,
        "command": command,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }


def prove_transferred_clone(
    root: str | Path,
    *,
    collection_seconds: int = 900,
    runner: Callable[..., dict[str, Any]] = _run,
    collection_runner: Callable[[Path, int, dict[str, str]], dict[str, Any]] = _collect_and_stop,
    clone_verifier: Callable[..., dict[str, Any]] = verify_clone,
    current_fingerprint: Callable[[], str] = machine_fingerprint,
) -> dict[str, Any]:
    project = Path(root).resolve()
    manifest_path = project / "PORTABLE_FULL_CLONE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "portable_ready": False, "reason": f"manifest_invalid:{exc}", "steps": []}
    source_machine = str(manifest.get("source_machine_fingerprint") or "")
    target_machine = current_fingerprint()
    if not source_machine:
        return {"ok": False, "portable_ready": False, "reason": "source_machine_proof_missing", "steps": []}
    if source_machine == target_machine:
        return {"ok": False, "portable_ready": False, "reason": "physical_pc_b_required", "steps": []}

    verification = clone_verifier(project, full_hash=True)
    if not verification.get("ok"):
        return {
            "ok": False, "portable_ready": False, "reason": "full_hash_verification_failed",
            "clone_verification": verification, "steps": [],
        }

    python = project / "tools" / "python" / "python.exe"
    launcher = project / "LANCER_HYPERSMART.cmd"
    analyser = project / "ANALYSER_BACKTESTS_REPLAYS.cmd"
    env = os.environ.copy()
    env.update({
        "HYPERSMART_NO_PAUSE": "1", "HYPERSMART_NO_OPEN_REPORT": "1",
        "PYTHONPATH": str(project / "src") + os.pathsep + str(project),
    })
    commands: list[tuple[str, list[str], int]] = [
        ("portable_check", ["cmd.exe", "/d", "/c", str(launcher), "portable-check"], 600),
        ("portable_smoke", [str(python), "-m", "hl_observer.ops.portable_smoke", "--root", str(project), "--json"], 600),
    ]
    steps: list[dict[str, Any]] = []
    for name, command, timeout in commands:
        result = runner(command, cwd=project, timeout=timeout, env=env)
        result["name"] = name
        steps.append(result)
        if not result.get("ok"):
            return {
                "ok": False, "portable_ready": False, "reason": name + "_failed",
                "clone_verification": verification, "steps": steps,
            }

    # The real target proof must collect for at least 15 minutes.  Tests inject
    # a runner and still exercise this exact command graph without waiting.
    runtime = collection_runner(project, int(collection_seconds), env)
    runtime["name"] = "collection_15_minutes_and_clean_stop"
    steps.append(runtime)
    if not runtime.get("ok") or int(collection_seconds) < 900:
        return {
            "ok": False, "portable_ready": False,
            "reason": "collection_proof_failed" if not runtime.get("ok") else "collection_below_900_seconds",
            "clone_verification": verification, "steps": steps,
        }

    for name, mode, timeout in (("replay_full", "full", 7200), ("replay_deep", "deep", 14400)):
        result = runner(["cmd.exe", "/d", "/c", str(analyser), mode], cwd=project, timeout=timeout, env=env)
        result["name"] = name
        steps.append(result)
        if not result.get("ok"):
            return {
                "ok": False, "portable_ready": False, "reason": name + "_failed",
                "clone_verification": verification, "steps": steps,
            }
    return {
        "ok": True, "portable_ready": True, "reason": "pc_a_to_pc_b_full_proof_passed",
        "source_machine_fingerprint": source_machine, "target_machine_fingerprint": target_machine,
        "collection_seconds": int(collection_seconds), "clone_verification": verification, "steps": steps,
    }


def _write_report(root: Path, payload: dict[str, Any]) -> Path:
    path = root / REPORT_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove a complete clone on a distinct Windows PC")
    parser.add_argument("--root", default=".")
    parser.add_argument("--collection-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    result = prove_transferred_clone(args.root, collection_seconds=args.collection_seconds)
    report = _write_report(Path(args.root).resolve(), result)
    print(json.dumps({**result, "report": str(report)}, ensure_ascii=False, indent=2))
    return 0 if result.get("portable_ready") else 6


if __name__ == "__main__":
    raise SystemExit(main())
