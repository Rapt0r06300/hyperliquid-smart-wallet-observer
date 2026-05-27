from __future__ import annotations

import logging
from pathlib import Path

from hyper_smart_observer.app.config import AppConfig


def configure_logging(config: AppConfig) -> None:
    """Configure console logging without leaking secrets."""

    level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def ensure_log_dir(path: str | Path = "logs") -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
