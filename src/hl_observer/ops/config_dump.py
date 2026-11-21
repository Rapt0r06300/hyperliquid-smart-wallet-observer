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

    # UNE SEULE LECTURE D'HORLOGE, ET ELLE EST EN UTC (corrige le 2026-11-21).
    #
    # Avant : `"ts": time.time()` et `"ts_iso": time.strftime(...)` lisaient l'horloge DEUX
    # fois -- une meme grandeur avec deux valeurs, qui peuvent enjamber une seconde. Et
    # `strftime` sans argument rend l'heure LOCALE sans fuseau : dans un fichier dont le seul
    # role est l'audit post-mortem, deux lignes du changement d'heure deviennent impossibles
    # a ordonner, et personne ne peut savoir si « 02:30 » est avant ou apres « 02:45 ».
    maintenant = time.time()
    payload = {
        "ts": maintenant,
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(maintenant)),
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
