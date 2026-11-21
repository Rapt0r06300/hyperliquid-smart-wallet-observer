"""Primitives de la collecte bornee : ecriture atomique, python du projet, PID, protocoles.

EXTRAIT DE bounded_collection.py LE 21/11/2026 (875 lignes pour un plafond de 800).
L'invariant #13 du depot refuse qu'un fichier depasse son plafond : au-dela il devient
intouchable (l'edition le tronque). La regle est d'EXTRAIRE, jamais de relever le plafond.

POURQUOI CES QUATRE-LA, et pas inspect_bounded_collectors qui etait pourtant le plus gros
bloc (136 lignes) : celui-la depend de cinq noms internes du module d'origine
(SCHEMA_VERSION, STATE_RELPATH, _active_collector_protocols, _mapping_lease_id, _registry)
et il figure dans __all__. Le sortir aurait exige un import circulaire -- le nouveau module
lisant l'ancien pendant que l'ancien le re-exporte -- ou la rupture d'une API publique.
Ces quatre fonctions, elles, ne dependent d'AUCUN nom interne (mesure avant de deplacer) :
le nouveau module ne lit donc rien de l'ancien, et la dependance ne va que dans un sens.

Elles forment le socle sur lequel tout le cycle de vie repose : poser un etat sans jamais
laisser de fichier a moitie ecrit, trouver l'interpreteur du projet, lister les PID bornes,
lister les protocoles actifs. resolve_project_python reste dans __all__ via le re-export.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .echec_silencieux import noter as _noter_echec



def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    # Windows : os.replace peut echouer transitoirement (WinError 5 / PermissionError)
    # quand la cible est momentanement verrouillee (antivirus, lecteur concurrent).
    # On retente brievement au lieu de faire planter le cycle du collecteur.
    import time as _t
    derniere: OSError | None = None
    for tentative in range(8):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            derniere = exc
            _t.sleep(0.05 * (tentative + 1))
    try:
        temporary.unlink()
    except OSError as exc:
        _noter_echec("ops/bounded_collection.py:temporary_cleanup", exc)
    if derniere is not None:
        raise derniere

def resolve_project_python(root: str | Path) -> Path:
    """Prefer the embedded runtime so campaign processes remain portable."""

    project_root = Path(root).resolve()
    portable_root = project_root / "portable_runtime"
    backups = sorted(
        portable_root.glob("python_backup_*/python.exe"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    candidates = (
        project_root / "portable_runtime" / "python" / "python.exe",
        *backups,
        project_root / "tools" / "python" / "python.exe",
        Path(sys.executable),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("no usable Python executable for bounded collection")

def _bounded_process_ids(processes: list[dict[str, Any]]) -> set[int]:
    """Return bounded wrappers and descendants so they are never reused."""

    bounded = {
        int(row["pid"])
        for row in processes
        if isinstance(row.get("pid"), int)
        and "run_bounded_collector.py" in str(row.get("cmd") or "").lower()
    }
    while bounded:
        descendants = {
            int(row["pid"])
            for row in processes
            if isinstance(row.get("pid"), int) and row.get("ppid") in bounded
        }
        new = descendants - bounded
        if not new:
            break
        bounded.update(new)
    return bounded

def _active_collector_protocols(
    root: Path,
    active: Mapping[str, int],
    *,
    processes: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, str]:
    """Read fresh protocol markers owned by an active wrapper or its descendants.

    Windows Python launchers and venv shims may add child processes between
    the recorded Popen PID and the PID stored in a collector heartbeat.
    """

    protocols: dict[str, str] = {}
    heartbeat_dir = root / "runtime" / "research_lab" / "heartbeats"
    children: dict[int, set[int]] = {}
    for row in processes or ():
        try:
            child_pid = int(row.get("pid"))
            parent_pid = int(row.get("ppid"))
        except (TypeError, ValueError, OverflowError):
            continue
        children.setdefault(parent_pid, set()).add(child_pid)
    now_ms = int((time.time() if now is None else float(now)) * 1000)
    for name, pid in active.items():
        owned_pids = {int(pid)}
        pending = [int(pid)]
        while pending:
            parent_pid = pending.pop()
            for child_pid in children.get(parent_pid, ()):
                if child_pid not in owned_pids:
                    owned_pids.add(child_pid)
                    pending.append(child_pid)
        path = heartbeat_dir / f"{name}.json"
        try:
            heartbeat = json.loads(path.read_text(encoding="utf-8"))
            heartbeat_pid = int(heartbeat.get("pid"))
            heartbeat_ts_ms = int(heartbeat.get("ts_ms"))
        except (OSError, ValueError, TypeError):
            continue
        protocol = str(heartbeat.get("protocol") or "").strip()
        age_ms = now_ms - heartbeat_ts_ms
        if heartbeat_pid in owned_pids and 0 <= age_ms <= 60_000 and protocol:
            protocols[name] = protocol
    return protocols
