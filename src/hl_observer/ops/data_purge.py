"""OPS-5 — Purge des données périmées (logs, replay archives, tmp).

Paper-only, écriture locale uniquement. Supprime les fichiers vieux
de plus de N jours dans les répertoires éphémères.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 14
PURGEABLE_DIRS = [
    "runtime/replay/_archive",
    "runtime/replay/_merged",
    "runtime/data",
    "logs",
]
PURGEABLE_EXTENSIONS = {".log", ".zip", ".tmp", ".captmp", ".mergetmp"}


def purge_stale_files(
    root: str | Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> dict:
    root_path = Path(root).resolve()
    cutoff = time.time() - max_age_days * 86400
    removed: list[str] = []
    freed_bytes = 0

    for rel_dir in PURGEABLE_DIRS:
        target = root_path / rel_dir
        if not target.is_dir():
            continue
        for f in target.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix not in PURGEABLE_EXTENSIONS:
                continue
            try:
                stat = f.stat()
                if stat.st_mtime < cutoff:
                    if not dry_run:
                        f.unlink()
                    removed.append(str(f.relative_to(root_path)))
                    freed_bytes += stat.st_size
            except OSError as exc:
                logger.debug("purge skip %s: %s", f.name, exc)

    return {
        "removed_count": len(removed),
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        "max_age_days": max_age_days,
        "dry_run": dry_run,
        "files": removed[:50],
    }


__all__ = ["purge_stale_files"]
