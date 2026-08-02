"""VERROU D'INSTANCE UNIQUE (rectif Flo 23/07) — aucune 2ᵉ copie du collecteur ne doit démarrer.

Au démarrage, `acquerir` écrit un lockfile {pid, run_id, heartbeat_ms}. Si un verrou FRAIS existe déjà
(heartbeat < TTL), la 2ᵉ copie REFUSE de démarrer. Le process vivant rafraîchit son heartbeat ;
un verrou périmé (process mort) est repris. Empêche le double-lancement qui a causé les collisions.

PUR (fichier local). Aucune dépendance réseau.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

TTL_MS = 30_000.0                # un verrou non rafraîchi depuis 30 s est considéré périmé (process mort)


def _p(root: Path, nom: str) -> Path:
    return Path(root) / "runtime" / "data" / ("%s.lock" % nom)


def _lire(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def acquerir_mutex(nom: str) -> tuple[bool | None, object]:
    """VERROU PRINCIPAL sous Windows : mutex NOMMÉ (kernel). Rend (True, handle) si acquis, (False, None)
    si une autre instance le tient déjà (ERROR_ALREADY_EXISTS=183), (None, None) hors Windows (l'appelant
    retombe alors sur le verrou fichier). Le handle DOIT être gardé vivant tant que l'instance tourne."""
    try:
        import ctypes  # noqa: PLC0415
        k = ctypes.windll.kernel32                                # noqa: attr — Windows only
    except (AttributeError, OSError, ImportError):
        return None, None                                         # pas Windows -> fallback fichier
    handle = k.CreateMutexW(None, True, "Global\\hypersmart_%s" % nom)
    if not handle or k.GetLastError() == 183:                     # ERROR_ALREADY_EXISTS
        return False, None
    return True, handle


def acquerir(root: Path, nom: str, *, now_ms: float | None = None,
             ttl_ms: float | None = None) -> tuple[bool, dict]:
    """Tente d'acquérir le verrou. Rend (ok, info). ok=False si une instance FRAÎCHE tient déjà le verrou.
    `ttl_ms` (défaut TTL_MS=30 s) : un collecteur rafraîchit son heartbeat, mais le LANCEUR (item 11) qui
    ne rafraîchit pas pendant le warmup passe un TTL plus long pour couvrir toute la fenêtre de démarrage."""
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    ttl = float(ttl_ms if ttl_ms is not None else TTL_MS)
    p = _p(root, nom)
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = _lire(p)
    if cur and (now - float(cur.get("heartbeat_ms") or 0)) < ttl and cur.get("pid") != os.getpid():
        return False, {"raison": "INSTANCE_DEJA_ACTIVE", "detenteur": cur}
    info = {"pid": os.getpid(), "run_id": "run-" + uuid.uuid4().hex[:12], "acquis_ms": int(now), "heartbeat_ms": int(now)}
    if cur:
        stale = p.with_name(f"{p.name}.stale.{uuid.uuid4().hex}")
        try:
            p.replace(stale)
        except OSError:
            latest = _lire(p)
            return False, {"raison": "INSTANCE_RACE_LOST", "detenteur": latest or {}}
    try:
        with p.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(info, ensure_ascii=False))
    except FileExistsError:
        return False, {"raison": "INSTANCE_RACE_LOST", "detenteur": _lire(p) or {}}
    return True, info


def heartbeat(root: Path, nom: str, info: dict, *, now_ms: float | None = None) -> None:
    """Rafraîchit le heartbeat du verrou (à appeler périodiquement par le process vivant)."""
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    current = _lire(_p(root, nom))
    if not current or current.get("run_id") != info.get("run_id"):
        return
    info["heartbeat_ms"] = int(now)
    try:
        target = _p(root, nom)
        tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def liberer(root: Path, nom: str, info: dict) -> None:
    """Libère le verrou si c'est bien le nôtre (à l'arrêt propre)."""
    p = _p(root, nom)
    cur = _lire(p)
    if (
        cur
        and cur.get("pid") == info.get("pid")
        and cur.get("run_id") == info.get("run_id")
    ):
        try:
            p.unlink()
        except OSError:
            pass


__all__ = ["acquerir", "heartbeat", "liberer", "TTL_MS"]
