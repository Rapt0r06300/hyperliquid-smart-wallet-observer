"""CONFIG RESSOURCES du labo 18 h (Flo 26/07). Limites CONFIGURABLES avec défauts PRUDENTS auto-calculés
selon la machine, pour tourner à pleine capacité UTILE sans saturer Windows (ne jamais tuer les collecteurs
ni corrompre les données). Tout est surchargeable par variable d'environnement.

Objectif directeur : chercher LARGE (max d'hypothèses) puis RENFORCER les survivants — mais jamais au prix de
la vérité économique ni de la stabilité de la machine. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import os
import shutil

CLES = ("MAX_CPU_PERCENT", "MAX_RAM_GB", "MAX_WORKERS", "MIN_FREE_DISK_GB")


def _cpu_count() -> int:
    try:
        return max(1, os.cpu_count() or 1)
    except Exception:  # noqa: BLE001
        return 1


def _ram_gb() -> float:
    try:
        import psutil  # type: ignore
        return psutil.virtual_memory().total / 1e9
    except Exception:  # noqa: BLE001
        pass
    try:  # repli POSIX
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except Exception:  # noqa: BLE001
        return 8.0


def _disk_libre_gb(chemin: str = ".") -> float:
    try:
        return shutil.disk_usage(chemin).free / 1e9
    except Exception:  # noqa: BLE001
        return 0.0


def _envf(cle: str, defaut: float) -> float:
    v = os.environ.get("HYPERSMART_18H_%s" % cle)
    if v is None:
        return float(defaut)
    try:
        return float(v)
    except ValueError:
        return float(defaut)


def limites(chemin: str = ".") -> dict:
    """Limites effectives (défauts prudents auto ou surcharge env HYPERSMART_18H_*).
    Défauts : CPU 75 % · RAM = total−4 Go (min 2) · workers = cœurs−1 (min 1, cap 12) · disque libre ≥ 5 Go."""
    ncpu = _cpu_count()
    ram = _ram_gb()
    return {
        "MAX_CPU_PERCENT": _envf("MAX_CPU_PERCENT", 75.0),
        "MAX_RAM_GB": _envf("MAX_RAM_GB", round(max(2.0, ram - 4.0), 1)),
        "MAX_WORKERS": int(_envf("MAX_WORKERS", min(12, max(1, ncpu - 1)))),
        "MIN_FREE_DISK_GB": _envf("MIN_FREE_DISK_GB", 5.0),
        "machine": {"cpu_logiques": ncpu, "ram_totale_gb": round(ram, 1),
                    "disque_libre_gb": round(_disk_libre_gb(chemin), 1)},
    }


def disque_ok(chemin: str = ".") -> tuple[bool, str]:
    lim = limites(chemin)
    libre = _disk_libre_gb(chemin)
    if libre < lim["MIN_FREE_DISK_GB"]:
        return False, "DISQUE_INSUFFISANT (%.1f Go < %.1f Go requis)" % (libre, lim["MIN_FREE_DISK_GB"])
    return True, "OK (%.1f Go libres)" % libre


__all__ = ["limites", "disque_ok", "CLES"]
