"""[PORTABILITE items 1 & 5] Résolveur CANONIQUE de la racine du projet — depuis l'emplacement du
FICHIER, jamais depuis le répertoire courant.

Objectif (item 1) : « aucune dépendance au répertoire courant ». Où qu'on lance `python -m hl_observer`
(depuis un autre dossier, un service, une tâche planifiée), la racine du projet est celle qui CONTIENT
ce paquet — calculée en remontant depuis `__file__` jusqu'à un marqueur stable (pyproject.toml ou les
deux fichiers maîtres). `Path.cwd()` n'est plus qu'un ultime filet de sécurité, jamais la source.

Item 5 : toutes les écritures runtime dérivent de cette racine (runtime/ sous le projet), jamais d'un
profil utilisateur, d'AppData, du registre ou d'un chemin machine. `chemin_runtime(...)` compose ces
chemins de façon portable. 0 réseau, 0 dépendance système.
"""
from __future__ import annotations

from pathlib import Path

# Marqueurs qui identifient de façon fiable la racine d'un dossier « Projet invest », quel que soit le
# PC, le disque ou le chemin. pyproject.toml est présent dans le dépôt ; les deux .cmd maîtres sont la
# signature du projet même dans une archive dépourvue de pyproject.
_MARQUEURS_FICHIER = ("pyproject.toml",)
_MARQUEURS_MAITRES = ("LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd")


def _est_racine(dossier: Path) -> bool:
    if any((dossier / m).exists() for m in _MARQUEURS_FICHIER):
        return True
    return all((dossier / m).exists() for m in _MARQUEURS_MAITRES)


def racine_projet(depart: str | Path | None = None) -> Path:
    """Racine du projet, calculée en REMONTANT depuis ce fichier (ou `depart`) jusqu'à un marqueur.
    Ne dépend JAMAIS du répertoire courant (item 1). Filet de sécurité ultime : le parent de `src/`
    relatif à ce module, puis `Path.cwd()` — seulement si aucun marqueur n'est trouvé."""
    ici = Path(depart).resolve() if depart is not None else Path(__file__).resolve()
    for parent in (ici, *ici.parents):
        if parent.is_dir() and _est_racine(parent):
            return parent
    # ce module est <racine>/src/hl_observer/portabilite.py -> parents[2] == <racine> même sans marqueur.
    try:
        candidat = Path(__file__).resolve().parents[2]
        if candidat.is_dir():
            return candidat
    except IndexError:
        pass
    return Path.cwd()


def chemin_runtime(*parties: str, racine: str | Path | None = None) -> Path:
    """Chemin sous `<racine>/runtime/...`, portable et confiné au projet (item 5). Ne crée rien."""
    base = Path(racine) if racine is not None else racine_projet()
    return base.joinpath("runtime", *parties)


__all__ = ["racine_projet", "chemin_runtime"]
