from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Dossier cible unique pour TOUS les logs
_LOG_DIR_NAME = "logs à envoyer"


class JsonFormatter(logging.Formatter):
    """Small JSON formatter to avoid adding a logging dependency in the MVP."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, Mapping):
            payload.update(extra)
        return json.dumps(payload, sort_keys=True, default=str)


def _resolve_project_root() -> Path:
    """Remonte depuis ce fichier jusqu'a la racine du projet (contient pyproject.toml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    # Console handler (JSON sur stderr)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(JsonFormatter())
    root.addHandler(console)

    # File handler — RotatingFileHandler dans logs/logs a envoyer/
    log_dir = _resolve_project_root() / "logs" / _LOG_DIR_NAME
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "hypersmart_observer.log",
            maxBytes=10 * 1024 * 1024,  # 10 Mo
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)
    except OSError:
        root.warning("Impossible d'ecrire les logs dans %s", log_dir)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
