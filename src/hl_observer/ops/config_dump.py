"""OPS-7 — Dump de la configuration active au démarrage.

Journalise toutes les variables HYPERSMART_ dans un fichier JSON
horodaté pour audit post-mortem. Paper-only.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PREFIX = "HYPERSMART_"
SENSITIVE_FRAGMENTS = {"KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL"}


def dump_config(root: str | Path | None = None) -> dict:
    root_path = Path(root or os.environ.get("ALINA_PROJECT_ROOT", ".")).resolve()
    out_dir = root_path / "runtime" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    config: dict[str, str] = {}
    for k, v in sorted(os.environ.items()):
        if k.startswith(PREFIX):
            if any(frag in k.upper() for frag in SENSITIVE_FRAGMENTS):
                config[k] = "***REDACTED***"
            else:
                config[k] = v

    payload = {
        "ts": time.time(),
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "var_count": len(config),
        "config": config,
    }

    out_path = out_dir / "config_dump.json"
    try:
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Config dump: %d HYPERSMART_ vars -> %s", len(config), out_path)
    except OSError as exc:
        logger.warning("Config dump failed: %s", exc)

    return payload


__all__ = ["dump_config"]
