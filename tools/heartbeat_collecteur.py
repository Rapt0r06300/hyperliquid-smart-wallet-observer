"""HEARTBEAT DE COLLECTEUR (Flo 26/07, PT-1/PT-9). Chaque collecteur écrit un battement à chaque passe :
horodatage, PID, nombre de passes, dernier exchange_ts vu, compte d'écritures. Le superviseur le lit pour
distinguer un collecteur VIVANT-mais-FIGÉ (process up, mais heartbeat vieux / aucun message neuf) d'un
collecteur sain. Fichier atomique sous runtime/research_lab/heartbeats/. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping


_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def chemin(root: Path, nom: str) -> Path:
    return Path(root) / "runtime" / "research_lab" / "heartbeats" / ("%s.json" % nom)


def _local_lock(p: Path) -> threading.RLock:
    key = str(p.resolve())
    with _LOCAL_LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _verrou_interprocessus(p: Path, *, timeout_s: float = 5.0):
    """Serialize heartbeat readers and writers, including separate Python processes."""
    verrou = p.with_name(p.name + ".lock")
    verrou.parent.mkdir(parents=True, exist_ok=True)
    handle = verrou.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            while not locked:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("heartbeat lock timeout: %s" % p)
                    time.sleep(0.01)
        else:
            import fcntl

            while not locked:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("heartbeat lock timeout: %s" % p)
                    time.sleep(0.01)
        yield
    finally:
        if locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


@contextmanager
def _verrou_heartbeat(p: Path):
    with _local_lock(p):
        with _verrou_interprocessus(p):
            yield


def _ecrire_atomique(p: Path, contenu: str, *, tentatives: int = 8) -> None:
    """Replace a heartbeat without sharing one temporary file between processes."""
    tmp = p.with_name(
        ".%s.%d.%d.%d.tmp"
        % (p.name, os.getpid(), threading.get_ident(), time.time_ns())
    )
    try:
        tmp.write_text(contenu, encoding="utf-8")
        for tentative in range(max(1, int(tentatives))):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                if tentative + 1 >= tentatives:
                    raise
                time.sleep(0.01 * (tentative + 1))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


# Clés de qualité de flux persistées dans le heartbeat (LANCEUR item 2). Un heartbeat FRAIS ne doit
# jamais masquer un de ces signaux : le collecteur les reporte à chaque passe, la preuve de vie les lit.
CLES_METRIQUES = (
    "gaps_critiques",       # trous critiques détectés (feed_quality)
    "carnet_desync",        # carnet local désynchronisé du snapshot exchange
    "sequence_invalide",    # séquence exchange rompue (ex. U/u Binance non contigus)
    "resync_en_attente",    # resynchronisation demandée, pas encore aboutie
    "reconnects",           # reconnexions WS cumulées (quota/limite probable)
    "stale",                # dernière donnée trop vieille malgré un process vivant
    "hors_ordre",           # événements reçus hors ordre (horodatage régressif)
)


def _metriques_propres(m: Mapping[str, Any] | None) -> dict:
    """Ne garde que les clés de qualité connues (bornage + robustesse). Types normalisés."""
    if not m:
        return {}
    out: dict = {}
    for cle in CLES_METRIQUES:
        if cle in m:
            v = m[cle]
            out[cle] = int(v) if cle in ("gaps_critiques", "reconnects", "hors_ordre") else bool(v)
    return out


def battre(root: Path, nom: str, *, n_ecrites: int = 0, dernier_exchange_ts=None, note: str = "",
           metriques: Mapping[str, Any] | None = None, pid: int | None = None,
           souscription_ack: bool | None = None, protocol: str | None = None) -> dict:
    """Écrit (atomiquement) le heartbeat du collecteur `nom`. Renvoie le dict écrit.

    `metriques` (LANCEUR item 2) : qualité RÉELLE du flux (gaps_critiques, carnet_desync,
    sequence_invalide, resync_en_attente, reconnects, stale, hors_ordre). Fournie → écrite telle quelle
    (état courant) ; None → l'état précédent est conservé (on ne « nettoie » pas un problème connu par
    simple oubli). `evaluer_depuis_disque` relit ces métriques et bloque un heartbeat frais qui masquerait
    un gap/désync/séquence invalide/resync/stale/hors-ordre.
    """
    p = chemin(root, nom)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _verrou_heartbeat(p):
        prev = _lire_sans_verrou(p)
        heartbeat_pid = int(pid if pid is not None else os.getpid())
        try:
            previous_pid = int(prev.get("pid"))
        except (TypeError, ValueError):
            previous_pid = None
        if previous_pid != heartbeat_pid:
            prev = {}
        m = _metriques_propres(metriques) if metriques is not None else dict(prev.get("metriques") or {})
        hb = {"nom": nom, "pid": heartbeat_pid, "ts_ms": int(time.time() * 1000),
              "n_passes": int(prev.get("n_passes", 0)) + 1,
              "n_ecrites_cumul": int(prev.get("n_ecrites_cumul", 0)) + int(n_ecrites),
              "dernier_exchange_ts": (
                  dernier_exchange_ts
                  if dernier_exchange_ts is not None
                  else prev.get("dernier_exchange_ts")
              ),
              "note": note[:120],
              "metriques": m}
        if souscription_ack is not None:
            hb["souscription_ack"] = bool(souscription_ack)
        elif "souscription_ack" in prev:
            hb["souscription_ack"] = bool(prev.get("souscription_ack"))
        if protocol is not None:
            hb["protocol"] = str(protocol)[:160]
        elif "protocol" in prev:
            hb["protocol"] = str(prev.get("protocol") or "")[:160]
        _ecrire_atomique(p, json.dumps(hb, ensure_ascii=False))
    return hb


def _lire_sans_verrou(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def lire(root: Path, nom: str) -> dict:
    p = chemin(root, nom)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _verrou_heartbeat(p):
        return _lire_sans_verrou(p)


def age_ms(root: Path, nom: str, *, maintenant_ms=None) -> float | None:
    """Âge du heartbeat en ms (None si absent). Sert au superviseur à détecter un collecteur figé."""
    hb = lire(root, nom)
    ts = hb.get("ts_ms")
    if ts is None:
        return None
    return (int(maintenant_ms if maintenant_ms is not None else time.time() * 1000)) - int(ts)


__all__ = ["chemin", "battre", "lire", "age_ms", "CLES_METRIQUES"]
