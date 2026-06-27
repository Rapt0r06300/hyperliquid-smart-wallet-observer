from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from hyper_smart_observer.app.config import AppConfig

# Dossier cible unique pour TOUS les logs
_LOG_DIR_NAME = "logs à envoyer"


def _resolve_project_root() -> Path:
    """Remonte depuis ce fichier jusqu'a la racine du projet (contient pyproject.toml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def configure_logging(config: AppConfig) -> None:
    """Configure console + fichier logging. Tous les logs vont dans logs/logs a envoyer/."""

    level = getattr(logging, config.log_level.upper(), logging.INFO)
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    formatter = logging.Formatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
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
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        root.warning("Impossible d'ecrire les logs dans %s", log_dir)

    # Reduire le bruit des libs HTTP
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def ensure_log_dir(path: str | Path = "logs") -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
