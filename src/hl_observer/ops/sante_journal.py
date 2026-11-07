"""Q-241 — Journal de santé append-only (un seul writer).

Enregistre les événements de santé (heartbeat, dégradation, reconnexion,
halt, crash) dans un fichier JSONL append-only pour audit et diagnostic.

PAPER / READ-ONLY — aucun effet de bord sur le moteur.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

_DEFAULT_PATH = Path(
    os.environ.get("HYPERSMART_RUNTIME_ROOT", "runtime")
) / "logs" / "sante_journal.jsonl"

_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 Mo


def _journal_path() -> Path:
    return Path(os.environ.get("HYPERSMART_SANTE_JOURNAL", str(_DEFAULT_PATH)))


def append(
    event_type: str,
    *,
    source: str = "",
    detail: dict[str, Any] | None = None,
    level: str = "INFO",
) -> None:
    """Ajoute un événement au journal. Thread-safe, append-only."""
    entry = {
        "ts": time.time(),
        "type": event_type,
        "source": source,
        "level": level,
    }
    if detail:
        entry["detail"] = detail

    path = _journal_path()
    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > _MAX_FILE_SIZE_BYTES:
                rotated = path.with_suffix(f".{int(time.time())}.jsonl")
                path.rename(rotated)
                logger.info("Journal santé rotationné → %s", rotated)

            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Impossible d'écrire dans le journal santé : %s", exc)


def read_recent(n: int = 100) -> list[dict[str, Any]]:
    """Lit les n dernières entrées du journal."""
    path = _journal_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines[-n:]]
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Lecture journal santé échouée : %s", exc)
        return []


__all__ = ["append", "read_recent"]
