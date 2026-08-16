from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from hl_observer.datasets.archive_library import resolve_current_workspace, suite_names
from hl_observer.datasets.replay_workspace import prepare_replay_workspace
from hl_observer.ops.autonomous_research_guard import (
    _popen_process_group_kwargs,
    _terminate_process_tree,
)
from hl_observer.ops.autonomous_research_status import status_path, write_status

SCHEMA = "alina.autonomous_research_job.v1"
CANONICAL_RELEASE_ID = 371149058
CANONICAL_DATASET_REPOSITORY = "Rapt0r06300/hypersmart-datasets"
ALLOWED_MODES = {"prepare-only", "economic", "historical", "historical-full", "historical-deep"}
ECONOMIC_SUITES = {"economic-core", "economic-full"}
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
MAX_SMALL_REPORT_BYTES = 5 * 1024 * 1024
POLL_SECONDS = 0.2
LIVE_HEARTBEAT_SECONDS = 1.0


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
    timeout_seconds: int | float | None = None,
    live_status_path: Path | None = None,
    live_context: Mapping[str, Any] | None = None,
    action_fr: str | None = None,
    next_action_fr: str | None = None,
    step_index: int | None = None,
    step_total: int | None = None,
) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}.log"
    started_wall = time.time()
    started_mono = time.monotonic()
    timed_out = False
    latest_line = {"value": None}
    line_lock = threading.Lock()
    context = dict(live_context or {})

    def publish(state: str, message_fr: str, *, process_id: int | None = None) -> None:
        if live_status_path is None:
            return
        with line_lock:
            last = latest_line["value"]
        write_status(
            live_status_path,
            job_id=context.get("job_id"),
            suite=context.get("suite"),
            mode=context.get("mode"),
            state=state,
            action_fr=action_fr or name,
            message_fr=message_fr,
            job_started_unix=context.get("job_started_unix"),
            stage_started_unix=started_wall,
            step_index=step_index,
            step_total=step_total,
            next_action_fr=next_action_fr,
            log_path=str(log_path),
            last_log_line=last,
            workspace=context.get("workspace"),
            process_id=process_id,
        )

    publish("STARTING", "L'étape démarre.")
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
            **_popen_process_group_kwargs(),
        )

        def pump_stdout() -> None:
            stream = process.stdout
            if stream is None:
                return
            try:
                for line in stream:
                    with line_lock:
                        latest_line["value"] = line.strip()
                    print(line, end="", flush=True)
                    handle.write(line)
                    handle.flush()
            except (OSError, ValueError):
                return

        pump = threading.Thread(
            target=pump_stdout,
            name=f"alina-stage-log-{name}",
            daemon=True,
        )
        pump.start()
        deadline = None if timeout_seconds is None else started_mono + float(timeout_seconds)
        next_heartbeat = started_mono
        try:
            while process.poll() is None:
                now_mono = time.monotonic()
                if now_mono >= next_heartbeat:
                    publish("RUNNING", "Le moteur travaille normalement.", process_id=process.pid)
                    next_heartbeat = now_mono + LIVE_HEARTBEAT_SECONDS
                if deadline is not None and now_mono >= deadline:
                    timed_out = True
                    publish("STOPPING", "Le timeout de cette étape est atteint; arrêt propre en cours.", process_id=process.pid)
                    _terminate_process_tree(process)
                    break
                time.sleep(POLL_SECONDS)
            if process.poll() is None:
                process.wait()
        finally:
            if process.poll() is None:
                _terminate_process_tree(process)
            pump.join(timeout=5)
        return_code = 124 if timed_out else int(process.returncode or 0)

    if return_code == 0:
        publish("STEP_DONE", "Étape terminée correctement.")
    elif timed_out:
        publish("TIMEOUT", "Étape arrêtée après avoir atteint sa limite de temps.")
    else:
        publish("STEP_ERROR", f"Étape terminée avec le code {return_code}.")
    return {
        "name": name,
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_seconds": round(max(0.0, time.time() - started_wall), 3),
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
    live_path = status_path(lab_root)
    job_started = time.time()
    live_context: dict[str, Any] = {
        "job_id": request["job_id"],
        "suite": request["suite"],
        "mode": request["mode"],
        "job_started_unix": job_started,
        "workspace": None,
    }
    write_status(
        live_path,
        job_id=request["job_id"],
        suite=request["suite"],
        mode=request["mode"],
        state="STARTING",
        action_fr="Vérification du job",
        message_fr="Alina vérifie la sécurité, le SHA du code et la demande avant de calculer.",
        job_started_unix=job_started,
        step_index=1,
        step_total=4,
        next_action_fr="Préparer les données et le workspace",
    )

    completion = result_dir / "JOB_RESULT.json"
    if completion.is_file() and not force:
        try:
            previous = json.loads(completion.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if isinstance(previous, Mapping) and previous.get("request_digest") == digest and previous.get("status") == "SUCCESS":
            print(f"[CACHE JOB OK] {request['job_id']} déjà terminé avec le même digest.", flush=True)
            write_status(
                live_path,
                job_id=request["job_id"],
                suite=request["suite"],
                mode=request["mode"],
                state="SUCCESS_CACHED",
                action_fr="Aucun calcul nécessaire",
                message_fr="Ce job a déjà été terminé avec exactement la même demande.",
                job_started_unix=job_started,
                step_index=4,
                step_total=4,
            )
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
        step = _run_logged(
            "01_prepare_dataset",
            prepare_cmd,
            cwd=project_root,
            log_dir=log_dir,
            live_status_path=live_path,
            live_context=live_context,
            action_fr="Préparation des données FULL/COLD",
            next_action_fr="Vérifier et ouvrir le workspace",
            step_index=2,
            step_total=4,
        )
        steps.append(step)
        if step["return_code"] != 0:
            primary_rc = int(step["return_code"] or 2)
    else:
        write_status(
            live_path,
            job_id=request["job_id"],
            suite=request["suite"],
            mode=request["mode"],
            state="RUNNING",
            action_fr="Réutilisation des données locales",
            message_fr="Aucun téléchargement demandé; Alina réutilise le cache persistant.",
            job_started_unix=job_started,
            step_index=2,
            step_total=4,
            next_action_fr="Vérifier et ouvrir le workspace",
        )

    if primary_rc == 0:
        try:
            workspace = resolve_current_workspace(lab_root, request["suite"])
        except Exception as exc:
            if not request["download"]:
                raise RuntimeError("Aucun workspace préparé et download=false.") from exc
            raise
        prepare_replay_workspace(project_root, materialized_root=workspace)
        live_context["workspace"] = str(workspace)
        write_status(
            live_path,
            job_id=request["job_id"],
            suite=request["suite"],
            mode=request["mode"],
            state="RUNNING",
            action_fr="Workspace prêt",
            message_fr="Les données utiles sont prêtes. Le calcul principal peut commencer.",
            job_started_unix=job_started,
            step_index=2,
            step_total=4,
            next_action_fr=(
                "Lancer les campagnes économiques"
                if request["mode"] == "economic"
                else "Lancer le laboratoire historique"
            ),
            workspace=str(workspace),
        )

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
            live_status_path=live_path,
            live_context=live_context,
            action_fr="Backtests économiques Copy-Vault, Lead-Lag et Cross-Venue",
            next_action_fr="Auditer le raccordement et préparer les rapports",
            step_index=3,
            step_total=4,
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
            live_status_path=live_path,
            live_context=live_context,
            action_fr="Replays, walk-forward et recherche historique",
            next_action_fr="Auditer le raccordement et préparer les rapports",
            step_index=3,
            step_total=4,
        )
        steps.append(step)
        primary_rc = int(step["return_code"])
    elif primary_rc == 0 and request["mode"] == "prepare-only":
        write_status(
            live_path,
            job_id=request["job_id"],
            suite=request["suite"],
            mode=request["mode"],
            state="RUNNING",
            action_fr="Préparation terminée",
            message_fr="Le job demandait uniquement de préparer les données; aucun backtest n'est lancé.",
            job_started_unix=job_started,
            step_index=3,
            step_total=4,
            next_action_fr="Écrire le rapport final",
            workspace=str(workspace) if workspace else None,
        )

    if primary_rc == 0 and workspace is not None and request["mode"] != "prepare-only":
        step = _run_logged(
            "03_connection_audit",
            [sys.executable, "-m", "hl_observer.ops.dataset_connection_audit", "--root", str(workspace)],
            cwd=project_root,
            log_dir=log_dir,
            timeout_seconds=1800,
            live_status_path=live_path,
            live_context=live_context,
            action_fr="Vérification finale des sources et des raccordements",
            next_action_fr="Copier les petits rapports utiles vers GitHub",
            step_index=4,
            step_total=4,
        )
        steps.append(step)
        if step["return_code"] != 0:
            primary_rc = int(step["return_code"])

    write_status(
        live_path,
        job_id=request["job_id"],
        suite=request["suite"],
        mode=request["mode"],
        state="FINALIZING",
        action_fr="Préparation du résultat",
        message_fr="Alina rassemble uniquement les petits rapports et garde les gros fichiers localement.",
        job_started_unix=job_started,
        step_index=4,
        step_total=4,
        workspace=str(workspace) if workspace else None,
    )
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
    write_status(
        live_path,
        job_id=request["job_id"],
        suite=request["suite"],
        mode=request["mode"],
        state=status,
        action_fr=("Job terminé" if primary_rc == 0 else "Job arrêté en NO_GO"),
        message_fr=(
            "Le pipeline demandé est terminé techniquement. Les rapports peuvent maintenant être analysés."
            if primary_rc == 0
            else "Une étape a échoué ou a refusé de continuer. Consulte le dernier message et le log indiqué."
        ),
        job_started_unix=job_started,
        step_index=4,
        step_total=4,
        workspace=str(workspace) if workspace else None,
        log_path=str(log_dir),
    )
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
        try:
            write_status(
                status_path(Path(args.lab_root)),
                job_id=None,
                suite=None,
                mode=None,
                state="ERROR",
                action_fr="Job refusé ou interrompu",
                message_fr=f"{type(exc).__name__}: {exc}",
            )
        except OSError:
            pass
        print(f"ALINA_AUTONOMOUS_RESEARCH_NO_GO: {type(exc).__name__}: {exc}", flush=True)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
