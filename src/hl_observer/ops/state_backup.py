"""OPS-3 — Backup/restore de l'état avec vérification d'intégrité.

Snapshot d'un dict d'état → JSON + checksum; restauration qui REFUSE un backup
corrompu (checksum invalide). Une sauvegarde jamais testée n'est pas une
sauvegarde: restore_state est la moitié qui compte. I/O gardé.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def _checksum(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def backup_state(state: dict, path: str) -> dict:
    body = json.dumps(state, sort_keys=True, ensure_ascii=False)
    envelope = {"created_at_ms": int(time.time() * 1000), "checksum": _checksum(body), "state": state}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(envelope, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)  # écriture atomique: pas de backup à moitié écrit
    return {"ok": True, "path": str(p), "checksum": envelope["checksum"], "bytes": len(body)}


def restore_state(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "reason": "BACKUP_NOT_FOUND", "state": None}
    try:
        env = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "reason": "BACKUP_UNREADABLE", "state": None}
    state = env.get("state")
    body = json.dumps(state, sort_keys=True, ensure_ascii=False)
    if _checksum(body) != env.get("checksum"):
        return {"ok": False, "reason": "CHECKSUM_MISMATCH_CORRUPT", "state": None}
    return {"ok": True, "reason": "OK", "state": state, "created_at_ms": env.get("created_at_ms")}


__all__ = ["backup_state", "restore_state"]
