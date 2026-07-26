"""HEARTBEAT DE COLLECTEUR (Flo 26/07, PT-1/PT-9). Chaque collecteur écrit un battement à chaque passe :
horodatage, PID, nombre de passes, dernier exchange_ts vu, compte d'écritures. Le superviseur le lit pour
distinguer un collecteur VIVANT-mais-FIGÉ (process up, mais heartbeat vieux / aucun message neuf) d'un
collecteur sain. Fichier atomique sous runtime/research_lab/heartbeats/. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def chemin(root: Path, nom: str) -> Path:
    return Path(root) / "runtime" / "research_lab" / "heartbeats" / ("%s.json" % nom)


def battre(root: Path, nom: str, *, n_ecrites: int = 0, dernier_exchange_ts=None, note: str = "") -> dict:
    """Écrit (atomiquement) le heartbeat du collecteur `nom`. Renvoie le dict écrit."""
    p = chemin(root, nom)
    p.parent.mkdir(parents=True, exist_ok=True)
    prev = lire(root, nom)
    hb = {"nom": nom, "pid": os.getpid(), "ts_ms": int(time.time() * 1000),
          "n_passes": int(prev.get("n_passes", 0)) + 1, "n_ecrites_cumul": int(prev.get("n_ecrites_cumul", 0)) + int(n_ecrites),
          "dernier_exchange_ts": (dernier_exchange_ts if dernier_exchange_ts is not None else prev.get("dernier_exchange_ts")),
          "note": note[:120]}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(hb, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return hb


def lire(root: Path, nom: str) -> dict:
    try:
        return json.loads(chemin(root, nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def age_ms(root: Path, nom: str, *, maintenant_ms=None) -> float | None:
    """Âge du heartbeat en ms (None si absent). Sert au superviseur à détecter un collecteur figé."""
    hb = lire(root, nom)
    ts = hb.get("ts_ms")
    if ts is None:
        return None
    return (int(maintenant_ms if maintenant_ms is not None else time.time() * 1000)) - int(ts)


__all__ = ["chemin", "battre", "lire", "age_ms"]
