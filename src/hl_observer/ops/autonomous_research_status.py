"""État temps réel du laboratoire autonome Alina SmartFlow.

Le fichier CURRENT_STATUS.json est volontairement petit et atomique. Il ne
contient ni données de marché brutes, ni secrets, ni paramètres privés. Il sert
uniquement au cockpit Windows pour expliquer en français ce que le laboratoire
fait à cet instant.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

STATUS_SCHEMA = "alina.autonomous_live_status.v1"
STATUS_RELATIVE_PATH = Path("status") / "CURRENT_STATUS.json"


def status_path(lab_root: str | Path) -> Path:
    return Path(lab_root).resolve() / STATUS_RELATIVE_PATH


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_status(
    path: str | Path,
    *,
    job_id: str | None,
    suite: str | None,
    mode: str | None,
    state: str,
    action_fr: str,
    message_fr: str,
    job_started_unix: float | None = None,
    stage_started_unix: float | None = None,
    step_index: int | None = None,
    step_total: int | None = None,
    next_action_fr: str | None = None,
    log_path: str | None = None,
    last_log_line: str | None = None,
    workspace: str | None = None,
    process_id: int | None = None,
    progress_percent: float | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Écrit un heartbeat lisible par le cockpit, sans jamais exposer la commande brute."""

    now = time.time()
    payload: dict[str, Any] = {
        "schema": STATUS_SCHEMA,
        "heartbeat_unix": now,
        "job_id": job_id,
        "suite": suite,
        "mode": mode,
        "state": str(state),
        "action_fr": str(action_fr),
        "message_fr": str(message_fr),
        "job_elapsed_seconds": (
            round(max(0.0, now - float(job_started_unix)), 1)
            if job_started_unix is not None
            else None
        ),
        "stage_elapsed_seconds": (
            round(max(0.0, now - float(stage_started_unix)), 1)
            if stage_started_unix is not None
            else None
        ),
        "step_index": step_index,
        "step_total": step_total,
        "next_action_fr": next_action_fr,
        "log_path": log_path,
        "last_log_line": (str(last_log_line).strip()[-500:] if last_log_line else None),
        "workspace": workspace,
        "process_id": process_id,
        "progress_percent": (
            max(0.0, min(100.0, float(progress_percent)))
            if progress_percent is not None
            else None
        ),
        "paper_only": True,
        "real_execution": False,
        "live_collection": False,
    }
    if extra:
        # Seulement des métadonnées explicitement fournies par le worker.
        payload["extra"] = dict(extra)
    _atomic_write(Path(path), payload)
    return payload


def mark_waiting(path: str | Path, *, message_fr: str = "Le runner attend un nouveau travail.") -> dict[str, Any]:
    return write_status(
        path,
        job_id=None,
        suite=None,
        mode=None,
        state="WAITING",
        action_fr="En attente",
        message_fr=message_fr,
    )


__all__ = [
    "STATUS_RELATIVE_PATH",
    "STATUS_SCHEMA",
    "mark_waiting",
    "status_path",
    "write_status",
]
