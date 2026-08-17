from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

from hl_observer.ops.autonomous_research_job import (
    CANONICAL_DATASET_REPOSITORY,
    CANONICAL_RELEASE_ID,
    SCHEMA as WORKER_SCHEMA,
)
from hl_observer.ops.autonomous_research_job_router import validate_request

CONTROL_SCHEMA = "alina.self_hosted_control.v1"
MAX_CYCLE_SECONDS = 18 * 60 * 60
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Commande illisible: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("La commande doit être un objet JSON.")
    return raw


def _strict_bool(raw: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} doit être un booléen JSON.")
    return value


def normalize_control(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("schema") != CONTROL_SCHEMA:
        raise ValueError(f"schema doit être {CONTROL_SCHEMA}")

    job_id = str(raw.get("job_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", job_id):
        raise ValueError("job_id invalide: 1-80 caractères alphanumériques, . _ - uniquement.")

    max_cycle_seconds = int(raw.get("max_cycle_seconds", MAX_CYCLE_SECONDS))
    if max_cycle_seconds < 60 or max_cycle_seconds > MAX_CYCLE_SECONDS:
        raise ValueError(f"max_cycle_seconds doit être compris entre 60 et {MAX_CYCLE_SECONDS}.")

    requested_by = str(raw.get("requested_by") or "GitHub").strip()[:120]
    note = str(raw.get("note") or "").strip()[:500]

    return {
        "schema": CONTROL_SCHEMA,
        "job_id": job_id,
        "suite": str(raw.get("suite") or "").strip(),
        "mode": str(raw.get("mode") or "").strip(),
        "download": _strict_bool(raw, "download", True),
        "max_download_gib": float(raw.get("max_download_gib", 20.0)),
        "stage_timeout_seconds": int(raw.get("stage_timeout_seconds", 3600)),
        "cross_budget_s": float(raw.get("cross_budget_s", 20.0)),
        "lead_history_sources": int(raw.get("lead_history_sources", 8)),
        "force": _strict_bool(raw, "force", False),
        "max_cycle_seconds": max_cycle_seconds,
        "requested_by": requested_by,
        "note": note,
    }


def build_worker_request(control: Mapping[str, Any], *, project_sha: str) -> dict[str, Any]:
    normalized = normalize_control(control)
    sha = str(project_sha).strip().lower()
    if not SHA_RE.fullmatch(sha):
        raise ValueError("project_sha doit être un SHA Git complet de 40 caractères hexadécimaux.")

    # Le plan de contrôle ne peut jamais demander un autre dépôt, une autre release,
    # une autre branche ou activer une exécution réelle. Ces valeurs sont imposées ici.
    worker = {
        "schema": WORKER_SCHEMA,
        "job_id": normalized["job_id"],
        "suite": normalized["suite"],
        "mode": normalized["mode"],
        "project_ref": "main",
        "project_sha": sha,
        "release_id": CANONICAL_RELEASE_ID,
        "dataset_repository": CANONICAL_DATASET_REPOSITORY,
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "download": normalized["download"],
        "max_download_gib": normalized["max_download_gib"],
        "stage_timeout_seconds": normalized["stage_timeout_seconds"],
        "cross_budget_s": normalized["cross_budget_s"],
        "lead_history_sources": normalized["lead_history_sources"],
    }
    return validate_request(worker)


def build_control_bundle(control: Mapping[str, Any], *, project_sha: str) -> dict[str, Any]:
    normalized = normalize_control(control)
    return {
        "schema": "alina.self_hosted_control_bundle.v1",
        "control": normalized,
        "worker_request": build_worker_request(normalized, project_sha=project_sha),
        "guard": {
            "max_cycle_seconds": normalized["max_cycle_seconds"],
            "force": normalized["force"],
        },
        "security": {
            "paper_only": True,
            "real_execution": False,
            "live_collection": False,
            "project_ref": "main",
            "project_sha": str(project_sha).lower(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Transforme une petite commande GitHub en requête worker HyperSmart sûre et reproductible."
    )
    parser.add_argument("--control", required=True)
    parser.add_argument("--project-sha", required=True)
    parser.add_argument("--worker-request", required=True)
    parser.add_argument("--bundle-output")
    args = parser.parse_args(argv)

    control_path = Path(args.control).resolve()
    worker_path = Path(args.worker_request).resolve()
    bundle = build_control_bundle(_load_json(control_path), project_sha=args.project_sha)

    worker_path.parent.mkdir(parents=True, exist_ok=True)
    worker_path.write_text(
        json.dumps(bundle["worker_request"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.bundle_output:
        bundle_path = Path(args.bundle_output).resolve()
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        "ALINA_SELF_HOSTED_CONTROL_READY "
        f"job={bundle['control']['job_id']} suite={bundle['control']['suite']} "
        f"mode={bundle['control']['mode']} max_cycle={bundle['guard']['max_cycle_seconds']}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTROL_SCHEMA",
    "MAX_CYCLE_SECONDS",
    "build_control_bundle",
    "build_worker_request",
    "normalize_control",
]
