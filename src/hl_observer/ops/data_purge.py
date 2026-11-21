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

#: CE QUE LA PURGE NE PEUT PAS TOUCHER, quoi qu'on lui demande.
#:
#: MESURE DU 2026-11-21 qui a motive cette liste. Cette fonction n'etait appelee par aucun code
#: (seul `LANCER_HYPERSMART.cmd` la mentionne en commentaire, « ENG-053 ») et aucun test ne
#: l'atteignait. Lancee a blanc sur le depot, elle annoncait **18 fichiers, 16,3 Mo** -- dont
#: **12 journaux de session archives** sous `logs/.../_archives/session_20261027_*` et
#: `session_20261031_*`. Un dossier nomme `_archives` existe precisement pour CONSERVER ;
#: une purge qui y entre detruit la preuve qu'on garde pour la relire.
#:
#: La regle premiere du depot est de ne rien supprimer : donnees, historiques, preuves. Cette
#: liste est donc une garde qui ne peut QUE empecher une suppression, jamais en provoquer une.
#: Les refus sont COMPTES et RENDUS a l'appelant : un refus invisible n'existe pas.
PROTECTED_PATH_PARTS = (
    "_archives",         # tout ce qui est archive l'est pour etre relu
    "coffre_certifie",   # le coffre SAFE/LOCAL : la source du labo
    "backups",           # les sauvegardes posees avant chaque reparation
    "receipts",          # les recus : la preuve d'execution
    "campaign-history",  # l'historique des campagnes
    "market_ticks",      # le corpus collecte ; meme un shard partiel est une mesure
)


def chemin_protege(relatif: Path) -> str | None:
    """Le nom du dossier protege qui interdit de toucher ce fichier, ou ``None``.

    On compare des COMPOSANTS de chemin, pas une sous-chaine : `logs/mes_backupsfoo.log`
    n'est pas protege, `runtime/backups/x.log` l'est.
    """
    for partie in relatif.parts:
        if partie in PROTECTED_PATH_PARTS:
            return partie
    return None


def purge_stale_files(
    root: str | Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> dict:
    root_path = Path(root).resolve()
    cutoff = time.time() - max_age_days * 86400
    removed: list[str] = []
    protected: list[str] = []
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
            relatif = f.relative_to(root_path)
            garde = chemin_protege(relatif)
            if garde is not None:
                # Refus NOMME : on dit lequel, et on le compte. Jamais un saut silencieux.
                protected.append(f"{relatif.as_posix()} [{garde}]")
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
        "protected_count": len(protected),
        "protected_files": protected[:50],
    }


__all__ = ["purge_stale_files", "chemin_protege", "PROTECTED_PATH_PARTS"]
