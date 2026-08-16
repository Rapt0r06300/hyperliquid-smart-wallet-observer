from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from hl_observer.datasets.archive_library import resolve_current_workspace, suite_names
from hl_observer.datasets.replay_workspace import prepare_replay_workspace

SCHEMA = "alina.autonomous_research_job.v1"
CANONICAL_RELEASE_ID = 371149058
CANONICAL_DATASET_REPOSITORY = "Rapt0r06300/hypersmart-datasets"
ALLOWED_MODES = {"prepare-only", "economic", "historical", "historical-full", "historical-deep"}
ECONOMIC_SUITES = {"economic-core", "economic-full"}
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
MAX_SMALL_REPORT_BYTES = 5 * 1024 * 1024


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _load_request(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Requête illisible: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("La requête doit être un objet JSON.")
    return raw


def validate_request(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("schema") != SCHEMA:
        raise ValueError(f"schema doit être {SCHEMA}")

    job_id = str(raw.get("job_id") or "").strip()
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id invalide: 1-80 caractères alphanumériques, . _ - uniquement")

    suite = str(raw.get("suite") or "").strip()
    if suite not in suite_names():
        raise ValueError(f"suite inconnue: {suite}")

    mode = str(raw.get("mode") or "").strip()
    if mode not in ALLOWED_MODES:
        raise ValueError(f"mode inconnu: {mode}")
    if mode == "economic" and suite not in ECONOMIC_SUITES:
        raise ValueError("Le mode economic exige economic-core ou economic-full.")

    project_sha = str(raw.get("project_sha") or "").strip().lower()
    if not SHA_RE.fullmatch(project_sha):
        raise ValueError("project_sha doit contenir exactement 40 caractères hexadécimaux.")

    project_ref = str(raw.get("project_ref") or "main").strip()
    if project_ref != "main":
        raise ValueError("Seule la branche main est autorisée pour les jobs autonomes.")

    release_id = int(raw.get("release_id") or CANONICAL_RELEASE_ID)
    if release_id != CANONICAL_RELEASE_ID:
        raise ValueError(f"release_id doit rester {CANONICAL_RELEASE_ID}.")

    repository = str(raw.get("dataset_repository") or CANONICAL_DATASET_REPOSITORY).strip()
    if repository != CANONICAL_DATASET_REPOSITORY:
        raise ValueError(f"dataset_repository doit rester {CANONICAL_DATASET_REPOSITORY}.")

    if raw.get("paper_only") is not True:
        raise ValueError("paper_only=true est obligatoire.")
    if raw.get("real_execution") is not False:
        raise ValueError("real_execution=false est obligatoire.")
    if raw.get("start_live_collection") is not False:
        raise ValueError("start_live_collection=false est obligatoire.")

    download = bool(raw.get("download", True))
    max_download_gib = float(raw.get("max_download_gib", 20.0))
    if max_download_gib <= 0 or max_download_gib > 220:
        raise ValueError("max_download_gib doit être > 0 et <= 220 Gio.")

    stage_timeout_seconds = int(raw.get("stage_timeout_seconds", 3600))
    if stage_timeout_seconds < 60 or stage_timeout_seconds > 86_400:
        raise ValueError("stage_timeout_seconds doit être compris entre 60 et 86400.")

    cross_budget_s = float(raw.get("cross_budget_s", 20.0))
    if cross_budget_s < 0 or cross_budget_s > 3600:
        raise ValueError("cross_budget_s doit être compris entre 0 et 3600.")

    lead_history_sources = int(raw.get("lead_history_sources", 8))
    if lead_history_sources < 0 or lead_history_sources > 100_000:
        raise ValueError("lead_history_sources hors plage autorisée.")

    return {
        "schema": SCHEMA,
        "job_id": job_id,
        "suite": suite,
        "mode": mode,
        "project_ref": project_ref,
        "project_sha": project_sha,
        "release_id": release_id,
        "dataset_repository": repository,
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "download": download,
        "max_download_gib": max_download_gib,
        "stage_timeout_seconds": stage_timeout_seconds,
        "cross_budget_s": cross_budget_s,
        "lead_history_sources": lead_history_sources,
    }


def _git_head(project_root: Path) -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        raise RuntimeError("Impossible de lire le SHA Git du projet.")
    value = process.stdout.strip().lower()
    if not SHA_RE.fullmatch(value):
        raise RuntimeError(f"SHA Git inattendu: {value}")
    return value


def _assert_execution_disabled() -> None:
    forbidden_true = []
    for key in ("HL_ENABLE_MAINNET_EXECUTION", "HL_ENABLE_TESTNET_EXECUTION", "REAL_MAINNET_TRADING"):
        value = str(os.getenv(key, "0")).strip().casefold()
        if value in {"1", "true", "yes", "on", "oui"}:
            forbidden_true.append(key)
    if forbidden_true:
        raise RuntimeError("Exécution réelle/testnet activée dans l'environnement: " + ", ".join(forbidden_true))


def _safe_environment() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "HL_ENABLE_MAINNET_EXECUTION": "0",
            "HL_ENABLE_TESTNET_EXECUTION": "0",
            "REAL_MAINNET_TRADING": "false",
            "TESTNET_ONLY": "true",
            "HYPERSMART_ANALYSIS_LOCAL_ONLY": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def _run_logged(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    log_dir: Path,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}.log"
    started = time.time()
    timed_out = False
    return_code = 2
    with log_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("COMMAND=" + json.dumps(command, ensure_ascii=False) + "\n")
        handle.flush()
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=_safe_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        try:
            assert process.stdout is not None
            while True:
                line = process.stdout.readline()
                if line:
                    print(line, end="", flush=True)
                    handle.write(line)
                    handle.flush()
                if process.poll() is not None:
                    for rest in process.stdout:
                        print(rest, end="", flush=True)
                        handle.write(rest)
                    break
                if deadline is not None and time.monotonic() > deadline:
                    timed_out = True
                    process.terminate()
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
            return_code = int(process.wait())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return {
        "name": name,
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_seconds": round(max(0.0, time.time() - started), 3),
        "log_path": str(log_path),
        "command": command,
    }


def _copy_if_small(source: Path, destination_dir: Path, copied: list[str]) -> None:
    if not source.is_file():
        return
    try:
        size = source.stat().st_size
    except OSError:
        return
    if size > MAX_SMALL_REPORT_BYTES:
        return
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        stem = source.stem
        destination = destination_dir / f"{stem}_{hashlib.sha256(str(source).encode()).hexdigest()[:8]}{source.suffix}"
    shutil.copy2(source, destination)
    copied.append(str(destination))


def _collect_small_reports(project_root: Path, workspace: Path, result_dir: Path, suite: str) -> list[str]:
    copied: list[str] = []
    candidates = [
        workspace / "runtime" / "reports" / "economic_campaigns" / "HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md",
        workspace / "runtime" / "reports" / "datasets" / "SOURCE_CONSUMPTION_COVERAGE.md",
        workspace / "runtime" / "reports" / "datasets" / "SOURCE_CONSUMPTION_COVERAGE.json",
        workspace / "runtime" / "reports" / "datasets" / "DATASET_CONNECTION_AUDIT.md",
        workspace / "runtime" / "reports" / "datasets" / "DATASET_CONNECTION_AUDIT.json",
        workspace / "runtime" / "reports" / "datasets" / "SQLITE_INVENTORY.md",
        workspace / "runtime" / "reports" / "datasets" / "SQLITE_INVENTORY.json",
        workspace / "runtime" / "reports" / "datasets" / "SQLITE_RESEARCH_CATALOG.md",
        workspace / "runtime" / "reports" / "datasets" / "SQLITE_RESEARCH_CATALOG.json",
        workspace / "runtime" / "reports" / "datasets" / "RESEARCH_LAB_STREAM_PROFILE.md",
        workspace / "runtime" / "reports" / "datasets" / "RESEARCH_LAB_STREAM_PROFILE.json",
    ]
    historical = project_root / "runtime" / "reports" / "datasets" / "historical" / suite
    if historical.is_dir():
        candidates.extend(sorted(historical.glob("RAPPORT_DATASET_LATEST.*")))
        candidates.extend(sorted(historical.glob("report_dataset_latest.*")))
    for source in candidates:
        _copy_if_small(source, result_dir / "reports", copied)
    return copied


def _write_result(result_dir: Path, payload: Mapping[str, Any]) -> tuple[Path, Path]:
    result_dir.mkdir(parents=True, exist_ok=True)
    json_path = result_dir / "JOB_RESULT.json"
    md_path = result_dir / "JOB_RESULT.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Alina SmartFlow — résultat du job autonome",
        "",
        f"- Job : `{payload.get('job_id')}`",
        f"- Statut : **{payload.get('status')}**",
        f"- Suite : `{payload.get('suite')}`",
        f"- Mode : `{payload.get('mode')}`",
        f"- SHA projet : `{payload.get('project_sha')}`",
        f"- Digest requête : `{payload.get('request_digest')}`",
        f"- Workspace : `{payload.get('workspace')}`",
        "- Exécution réelle : **NON**",
        "- Collecte live : **NON**",
        "",
        "## Étapes",
        "",
        "| Étape | Code | Durée (s) | Timeout |",
        "|---|---:|---:|---|",
    ]
    for step in payload.get("steps", []):
        if isinstance(step, Mapping):
            lines.append(
                f"| {step.get('name')} | {step.get('return_code')} | {step.get('duration_seconds')} | {step.get('timed_out')} |"
            )
    lines.extend(["", "## Rapports légers copiés", ""])
    reports = payload.get("copied_reports") if isinstance(payload.get("copied_reports"), list) else []
    lines.extend([f"- `{item}`" for item in reports] or ["- Aucun."])
    lines.extend([
        "",
        "> Un statut SUCCESS signifie que le pipeline demandé s'est exécuté sans erreur technique. Il ne signifie pas PnL positif ni stratégie rentable.",
        "",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def execute_job(
    request_file: Path,
    *,
    project_root: Path,
    lab_root: Path,
    result_dir: Path,
    force: bool = False,
) -> int:
    request = validate_request(_load_request(request_file))
    digest = request_digest(request)
    project_root = project_root.resolve()
    lab_root = lab_root.resolve()
    result_dir = result_dir.resolve()
    lab_root.mkdir(parents=True, exist_ok=True)

    completion = result_dir / "JOB_RESULT.json"
    if completion.is_file() and not force:
        try:
            previous = json.loads(completion.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if isinstance(previous, Mapping) and previous.get("request_digest") == digest and previous.get("status") == "SUCCESS":
            print(f"[CACHE JOB OK] {request['job_id']} déjà terminé avec le même digest.", flush=True)
            return 0

    _assert_execution_disabled()
    actual_sha = _git_head(project_root)
    if actual_sha != request["project_sha"]:
        raise RuntimeError(
            f"SHA projet différent: requête={request['project_sha']} checkout={actual_sha}. Refus reproductible."
        )

    log_dir = lab_root / "job_logs" / request["job_id"]
    steps: list[dict[str, Any]] = []
    workspace: Path | None = None
    primary_rc = 0

    if request["download"]:
        prepare_cmd = [
            sys.executable,
            "-m",
            "hl_observer.ops.dataset_bridge",
            "prepare",
            "--root",
            str(lab_root),
            "--repo",
            request["dataset_repository"],
            "--release-id",
            str(request["release_id"]),
            "--suite",
            request["suite"],
            "--download",
            "--max-download-gib",
            str(request["max_download_gib"]),
            "--heartbeat-seconds",
            "1",
        ]
        step = _run_logged("01_prepare_dataset", prepare_cmd, cwd=project_root, log_dir=log_dir)
        steps.append(step)
        if step["return_code"] != 0:
            primary_rc = int(step["return_code"] or 2)
    if primary_rc == 0:
        try:
            workspace = resolve_current_workspace(lab_root, request["suite"])
        except Exception as exc:
            if not request["download"]:
                raise RuntimeError("Aucun workspace préparé et download=false.") from exc
            raise
        prepare_replay_workspace(project_root, materialized_root=workspace)

    if primary_rc == 0 and request["mode"] == "economic":
        command = [
            sys.executable,
            str(project_root / "tools" / "run_dataset_economic_campaigns.py"),
            "--root",
            str(workspace),
            "--no-start-collection",
            "--cross-budget-s",
            str(request["cross_budget_s"]),
            "--lead-history-sources",
            str(request["lead_history_sources"]),
        ]
        step = _run_logged(
            "02_economic_campaigns",
            command,
            cwd=project_root,
            log_dir=log_dir,
            timeout_seconds=request["stage_timeout_seconds"],
        )
        steps.append(step)
        primary_rc = int(step["return_code"])
    elif primary_rc == 0 and request["mode"].startswith("historical"):
        command = [
            sys.executable,
            "-m",
            "hl_observer.ops.dataset_research_runner",
            "--root",
            str(project_root),
            "--data-root",
            str(workspace),
            "--suite",
            request["suite"],
            "--stage-timeout-seconds",
            str(request["stage_timeout_seconds"]),
        ]
        if request["mode"] == "historical-full":
            command.append("--full")
        elif request["mode"] == "historical-deep":
            command.append("--deep")
        step = _run_logged(
            "02_historical_lab",
            command,
            cwd=project_root,
            log_dir=log_dir,
            timeout_seconds=None,
        )
        steps.append(step)
        primary_rc = int(step["return_code"])

    if primary_rc == 0 and workspace is not None and request["mode"] != "prepare-only":
        step = _run_logged(
            "03_connection_audit",
            [sys.executable, "-m", "hl_observer.ops.dataset_connection_audit", "--root", str(workspace)],
            cwd=project_root,
            log_dir=log_dir,
            timeout_seconds=1800,
        )
        steps.append(step)
        if step["return_code"] != 0:
            primary_rc = int(step["return_code"])

    copied_reports = _collect_small_reports(project_root, workspace, result_dir, request["suite"]) if workspace else []
    status = "SUCCESS" if primary_rc == 0 else "NO_GO"
    payload = {
        "schema": "alina.autonomous_research_result.v1",
        "job_id": request["job_id"],
        "status": status,
        "suite": request["suite"],
        "mode": request["mode"],
        "request_digest": digest,
        "project_sha": actual_sha,
        "release_id": request["release_id"],
        "dataset_repository": request["dataset_repository"],
        "workspace": str(workspace) if workspace else None,
        "steps": steps,
        "copied_reports": copied_reports,
        "persistent_log_dir": str(log_dir),
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "network_market_data_used": False,
        "network_dataset_download_used": bool(request["download"]),
        "exit_code": primary_rc,
    }
    _write_result(result_dir, payload)
    return primary_rc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exécute un job autonome FULL/COLD validé en paper/read-only strict.")
    parser.add_argument("--request", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--lab-root", required=True)
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return execute_job(
            Path(args.request),
            project_root=Path(args.project_root),
            lab_root=Path(args.lab_root),
            result_dir=Path(args.result_dir),
            force=bool(args.force),
        )
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"ALINA_AUTONOMOUS_RESEARCH_NO_GO: {type(exc).__name__}: {exc}", flush=True)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
