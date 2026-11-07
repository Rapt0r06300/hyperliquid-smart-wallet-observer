"""OPS-3 — Rotation des logs collecteurs cachés.

Tronque les gros fichiers .log et supprime les archives lourdes .zip.
Paper-only, lecture/écriture locale uniquement.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 Mo
DEFAULT_MAX_AGE_DAYS = 7


def rotate_logs(
    log_dir: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> dict:
    """Rotation best-effort des logs dans un répertoire."""
    log_path = Path(log_dir)
    if not log_path.is_dir():
        return {"status": "NO_DIR", "dir": str(log_dir)}

    truncated = []
    removed = []
    cutoff = time.time() - max_age_days * 86400

    for f in log_path.iterdir():
        try:
            if f.suffix == ".zip" and f.stat().st_mtime < cutoff:
                f.unlink()
                removed.append(f.name)
            elif f.suffix == ".log" and f.stat().st_size > max_bytes:
                tail = f.read_bytes()[-max_bytes:]
                f.write_bytes(tail)
                truncated.append(f.name)
        except OSError as exc:
            logger.warning("log_rotation: %s — %s", f.name, exc)

    return {
        "status": "OK",
        "truncated": truncated,
        "removed": removed,
        "dir": str(log_path),
    }


__all__ = ["rotate_logs"]
